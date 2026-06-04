/*********************                                                  */
/*! \file ic3base.cpp
** \verbatim
** Top contributors (to current version):
**   Makai Mann, Ahmed Irfan, Florian Lonsing
** This file is part of the pono project.
** Copyright (c) 2019 by the authors listed in the file AUTHORS
** in the top-level source directory) and their institutional affiliations.
** All rights reserved.  See the file LICENSE in the top-level source
** directory for licensing information.\endverbatim
**
** \brief Abstract base class implementation of IC3 parameterized by
**        the unit used in frames, pre-image computation, and inductive
**        and predecessor generalization techniques.
**
**/

#include "engines/ic3base.h"

#include <cassert>
#include <cstddef>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "core/prop.h"
#include "core/proverresult.h"
#include "core/refineresult.h"
#include "core/ts.h"
#include "engines/llm_generalizer.h"
#include "options/options.h"
#include "smt-switch/smt.h"
#include "smt/available_solvers.h"
#include "utils/exceptions.h"
#include "utils/logger.h"

#include <fstream>
#include <cstdlib>

using namespace smt;
using namespace std;

namespace pono {

// Forward declarations for dump functions
namespace {
void dump_ic3ia_cti(const CTIContext & ctx, const smt::TermVec & children);
void dump_ic3ia_frame_clause(const IC3Base * engine,
                             size_t frame_idx,
                             const IC3Formula & clause,
                             const smt::TermVec & literals);
}

// helper functions

/** Less than comparison of the hash of two terms
 *  for use in sorting
 *  @param t0 the first term
 *  @param t1 the second term
 *  @return true iff t0's hash is less than t1's hash
 */
static bool term_hash_lt(const smt::Term & t0, const smt::Term & t1)
{
  return (t0->hash() < t1->hash());
}

/** Syntactic subsumption check for clauses: ? a subsumes b ?
 *  @param IC3Formula a
 *  @param IC3Formula b
 *  returns true iff 'a subsumes b'
 */
static bool subsumes(const IC3Formula & a, const IC3Formula & b)
{
  assert(a.disjunction);
  assert(a.disjunction == b.disjunction);
  const TermVec & ac = a.children;
  const TermVec & bc = b.children;
  // NOTE: IC3Formula children are sorted on construction
  //       Uses unique id of term, from term->get_id()
  return ac.size() <= bc.size()
         && std::includes(bc.begin(), bc.end(), ac.begin(), ac.end());
}

/** ProofGoalQueue */

ProofGoalQueue::~ProofGoalQueue() { clear(); }

void ProofGoalQueue::clear()
{
  for (auto p : store_) {
    delete p;
  }
  store_.clear();
  while (!queue_.empty()) {
    queue_.pop();
  }
}

void ProofGoalQueue::new_proof_goal(const IC3Formula & c,
                                    unsigned int t,
                                    const ProofGoal * n)
{
  ProofGoal * pg = new ProofGoal(c, t, n);
  queue_.push(pg);
  store_.push_back(pg);
}

ProofGoal * ProofGoalQueue::top() { return queue_.top(); }

void ProofGoalQueue::pop() { queue_.pop(); }

bool ProofGoalQueue::empty() const { return queue_.empty(); }

/** IC3Base */

IC3Base::IC3Base(const SafetyProperty & p,
                 const TransitionSystem & ts,
                 const SmtSolver & solver,
                 PonoOptions opt,
                 Engine engine)
    : super(p, ts, solver, opt, engine),
      reducer_(
          create_reducer(solver->get_solver_enum(), opt.logging_smt_solver_)),
      solver_context_(0),
      num_check_sat_since_reset_(0),
      failed_to_reset_solver_(false),
      approx_pregen_(false)
{
}

void IC3Base::initialize()
{
  if (initialized_) {
    return;
  }

  boolsort_ = solver_->make_sort(BOOL);
  solver_true_ = solver_->make_term(true);

  // abstract the transition relation if this is a CEGAR implementation
  // otherwise it is a No-Op
  abstract();

  super::initialize();

  // check whether this flavor of IC3 can be applied to this transition system
  check_ts();

  assert(solver_context_ == 0);  // expecting to be at base context level

  frames_.clear();
  frame_labels_.clear();
  // first frame is always the initial states
  push_frame();
  // can't use constrain_frame for initial states because not guaranteed to be
  // an IC3Formula it's handled specially
  solver_->assert_formula(
      solver_->make_term(Implies, frame_labels_.at(0), ts_.init()));
  push_frame();

  // set semantics of TS labels
  assert(!init_label_);
  assert(!trans_label_);
  assert(!bad_label_);
  // frame 0 label is identical to init label
  init_label_ = frame_labels_[0];

  trans_label_ = solver_->make_symbol("__trans_label", boolsort_);
  solver_->assert_formula(
      solver_->make_term(Implies, trans_label_, ts_.trans()));

  bad_label_ = solver_->make_symbol("__bad_label", boolsort_);
  solver_->assert_formula(solver_->make_term(Implies, bad_label_, bad_));
}

ProverResult IC3Base::check_until(int k)
{
  initialize();
  // make sure derived class implemented initialize and called
  // this version of initialize with super::initialize or
  // (for experts only) set the initialized_ flag without
  // ever initializing base classes
  assert(initialized_);

  ProverResult res;
  RefineResult ref_res;
  int i = reached_k_ + 1;
  assert(reached_k_ + 1 >= 0);
  while (i <= k) {
    process_llm_candidates();  // non-blocking poll for LLM candidates

    res = step(i);

    if (res == ProverResult::FALSE) {
      assert(cex_.size());
      RefineResult s = refine();
      if (s == REFINE_SUCCESS) {
        continue;
      } else if (s == REFINE_NONE) {
        // this is a real counterexample
        assert(cex_.size());
        return ProverResult::FALSE;
      } else {
        assert(s == REFINE_FAIL);
        logger.log(1, "IC3Base: refinement failure, returning unknown");
        return ProverResult::UNKNOWN;
      }
    } else {
      ++i;
    }

    if (res != ProverResult::UNKNOWN) {
      return res;
    }
  }

  final_llm_poll();
  return ProverResult::UNKNOWN;
}

void IC3Base::final_llm_poll()
{
  process_llm_candidates();
}

bool IC3Base::witness(vector<UnorderedTermMap> & out)
{
  compute_witness();
  return super::witness(out);
}

size_t IC3Base::witness_length() const
{
  // expecting there to have been a witness computed
  assert(cex_.size());
  return cex_.size() - 1;
}

// Protected Methods

bool IC3Base::compute_witness() { return compute_witness(ts_); }

bool IC3Base::compute_witness(const TransitionSystem & ts)
{
  assert(solver_ == ts.solver());
  if (failed_to_reset_solver_) {
    logger.log(1, "IC3Base: cannot reset solver, witness computation aborted");
    return false;
  }
  solver_->reset_assertions();

  // construct base BMC query
  const size_t wit_len = witness_length();
  solver_->assert_formula(unroller_.at_time(ts.init(), 0));
  for (size_t t = 0; t < wit_len; ++t) {
    solver_->assert_formula(unroller_.at_time(ts.trans(), t));
  }
  solver_->assert_formula(unroller_.at_time(bad_, wit_len));

  // make stored cex additional constraint to guide the search
  TermVec state_constraints;
  state_constraints.reserve(wit_len);
  for (size_t t = 0; t < wit_len; ++t) {
    state_constraints.push_back(unroller_.at_time(cex_.at(t), t));
  }

  Result r = solver_->check_sat_assuming(state_constraints);
  if (!r.is_sat()) {
    logger.log(1,
               "IC3Base: failed to reconstruct CEX path with state "
               "constraints, falling back to plain BMC");
    r = solver_->check_sat();
  }

  if (!r.is_sat()) {
    logger.log(1, "IC3Base: failed to compute witness");
    return false;
  }

  return super::compute_witness();
}

IC3Formula IC3Base::ic3formula_disjunction(const TermVec & c) const
{
  assert(c.size());
  Term term = c.at(0);
  for (size_t i = 1; i < c.size(); ++i) {
    term = solver_->make_term(Or, term, c[i]);
  }
  return IC3Formula(term, c, true);
}

IC3Formula IC3Base::ic3formula_conjunction(const TermVec & c) const
{
  assert(c.size());
  Term term = c.at(0);
  for (size_t i = 1; i < c.size(); ++i) {
    term = solver_->make_term(And, term, c[i]);
  }
  return IC3Formula(term, c, false);
}

IC3Formula IC3Base::ic3formula_negate(const IC3Formula & u) const
{
  const TermVec & children = u.children;
  assert(!u.is_null());
  assert(children.size());

  TermVec neg_children;
  neg_children.reserve(children.size());
  Term nc = smart_not(children.at(0));

  bool is_clause = u.disjunction;
  Term term = nc;
  neg_children.push_back(nc);
  for (size_t i = 1; i < children.size(); ++i) {
    nc = smart_not(children[i]);
    neg_children.push_back(nc);
    if (is_clause) {
      // negation is a cube
      term = solver_->make_term(And, term, nc);
    } else {
      // negation is a clause
      term = solver_->make_term(Or, term, nc);
    }
  }
  return IC3Formula(term, neg_children, !is_clause);
}

IC3Formula IC3Base::inductive_generalization(size_t i, const IC3Formula & c)
{
  assert(!solver_context_);
  assert(i <= frontier_idx());
  assert(!c.disjunction);  // expecting a cube
  // be default will try to find a minimal cube
  // NOTE: not necessarily minimum (e.g. it's a local minimum)

  logger.log(
      3, "trying to generalize an IC3Formula of size {}", c.children.size());

  // TODO use unsat core reducer
  // TODO use ic3_gen_max_iter_ option or remove it
  //      maybe default zero could mean unbounded
  //      seems like a good compromise

  UnorderedTermSet necessary;  // populated with children we
                               // can't drop

  IC3Formula gen = c;
  IC3Formula out;
  Term dropped;
  size_t j = 0;
  while (j < gen.children.size() && gen.children.size() > 1) {
    // TODO use random_seed_ if set for shuffling
    //      order of drop attempts

    // try dropping j
    dropped = gen.children.at(j);
    if (necessary.find(dropped) != necessary.end()) {
      // can't drop this one
      j++;
      continue;
    }

    gen.children.erase(gen.children.begin() + j);

    // TODO: decide if it's too expensive to create fresh
    //       IC3Formula each time -- which sorts the elements
    //       if so, could consider not automatically sorting
    //       and instead only doing it for subsumption checks
    gen = ic3formula_conjunction(gen.children);

    if (!check_intersects_initial(gen.term)
        && rel_ind_check(i, gen, out, false)) {
      // we can drop this literal

      // out was generalized with an unsat core in
      // rel_ind_check
      // we can't rely on the order of the children
      // being the same
      gen = out;
      j = 0;  // start iteration over
    } else {
      // could not drop this child
      necessary.insert(dropped);
      // NOTE gen.term won't be updated
      //      but gen will be reconstructed in
      //      next iteration anyway
      gen.children.push_back(dropped);

      // NOTE: don't need to increment j because
      //       the one at position j was put at
      //       end of vector
      assert(j + 1 == gen.children.size() || gen.children.at(j) != dropped);
    }
  }

  // reconstruct the IC3Formula -- need to make sure term is valid
  // since we've been modifying gen.children
  gen = ic3formula_conjunction(gen.children);
  assert(!check_intersects_initial(gen.term));
  IC3Formula block = ic3formula_negate(gen);
  assert(block.disjunction);
  return block;
}

bool IC3Base::resolve_frame_literal_for_dump(const smt::Term & lit,
                                              std::string & resolved_expr,
                                              bool & is_negated) const {
  is_negated = false;
  // Base implementation: cannot resolve, return false
  return false;
}

void IC3Base::predecessor_generalization(size_t i,
                                         const Term & c,
                                         IC3Formula & pred)
{
  // by default does no generalization
  return;
}

bool IC3Base::reaches_bad(IC3Formula & out)
{
  push_solver_context();
  // assert the last frame (conjunction over clauses)
  assert_frame_labels(frontier_idx());
  // see if it can reach bad in one step
  solver_->assert_formula(ts_.next(bad_));
  solver_->assert_formula(trans_label_);
  Result r = check_sat();

  if (r.is_sat()) {
    out = get_model_ic3formula();
    assert(out.term);
    assert(out.children.size());
    assert(ic3formula_check_valid(out));

    // CTI capture for LLM generalization (works for all IC3 variants)
    capture_cti_context(frontier_idx(), out);

    if (options_.ic3_pregen_) {
      // try to generalize if predecessor generalization enabled
      predecessor_generalization_and_fix(frames_.size(), bad_, out);
      assert(out.term);
      assert(out.children.size());
      assert(ic3formula_check_valid(out));
    }
  }

  pop_solver_context();

  if (r.is_unknown()) {
    throw PonoException("Bad state check in IC3 returned unknown");
  }

  return r.is_sat();
}

ProverResult IC3Base::step(int i)
{
  if (i <= reached_k_) {
    return ProverResult::UNKNOWN;
  }

  if (reached_k_ < 1) {
    return step_01();
  }

  // reached_k_ is the number of transitions that have been checked
  // at this point there are reached_k_ + 1 frames that don't
  // intersect bad, and reached_k_ + 2 frames overall
  assert(reached_k_ == frontier_idx());
  logger.log(1, "Blocking phase at frame {}", i);
  if (!block_all()) {
    // counter-example
    return ProverResult::FALSE;
  }

  // Flush batched CTI contexts for this frame to LLM
  if (llm_gen_ && llm_gen_->is_async_cti()
      && llm_gen_->has_buffered_cti(frontier_idx())) {
    string snapshot = serialize_frame_snapshot_json(frontier_idx());
    llm_gen_->flush_frame_batch(frontier_idx(), snapshot);
    if (options_.llm_sync_after_flush_ && options_.llm_batch_cti_) {
      const string & bid = llm_gen_->last_flushed_batch_id();
      if (!bid.empty()) {
        llm_gen_->wait_for_batch_responses(bid,
                                           options_.llm_parallel_samples_,
                                           static_cast<unsigned>(
                                               options_.llm_batch_wait_sec_));
      }
    }
  }

  process_llm_candidates();  // poll for LLM candidates after blocking phase

  logger.log(1, "Propagation phase at frame {}", i);
  // propagation phase
  push_frame();
  for (size_t j = 1; j < frontier_idx(); ++j) {
    if (propagate(j)) {
      assert(j + 1 < frames_.size());
      // save the invariant
      // which is the frame that just had all terms
      // from the previous frames propagated
      invar_ = get_frame_term(j + 1);
      return ProverResult::TRUE;
    }
  }

  reset_solver();

  ++reached_k_;

  return ProverResult::UNKNOWN;
}

ProverResult IC3Base::step_01()
{
  assert(reached_k_ < 1);
  if (reached_k_ < 0) {
    logger.log(1, "Checking if initial states satisfy property");

    push_solver_context();
    solver_->assert_formula(init_label_);
    solver_->assert_formula(bad_);
    Result r = check_sat();
    if (r.is_sat()) {
      pop_solver_context();
      // trace is only one bad state that intersects with initial
      cex_.clear();
      cex_.push_back(bad_);
      return ProverResult::FALSE;
    } else {
      assert(r.is_unsat());
      reached_k_ = 0;  // keep reached_k_ aligned with number of frames
    }
    pop_solver_context();
  }

  assert(reached_k_ == 0);
  logger.log(1, "Checking if property can be violated in one-step");

  push_solver_context();
  solver_->assert_formula(init_label_);
  solver_->assert_formula(trans_label_);
  solver_->assert_formula(ts_.next(bad_));
  Result r = check_sat();
  if (r.is_sat()) {
    const IC3Formula & c = get_model_ic3formula();
    pop_solver_context();
    ProofGoal * pg = new ProofGoal(c, 0, nullptr);
    reconstruct_trace(pg, cex_);
    delete pg;
    return ProverResult::FALSE;
  } else {
    assert(r.is_unsat());
    reached_k_ = 1;  // keep reached_k_ aligned with number of frames
  }
  pop_solver_context();

  return ProverResult::UNKNOWN;
}

bool IC3Base::rel_ind_check(size_t i,
                            const IC3Formula & c,
                            IC3Formula & out,
                            bool get_pred,
                            const vector<IC3FrameDisjunct> * witness_refs,
                            string * witness_ref_out,
                            string * witness_val_out)
{
  assert(i > 0);
  assert(i < frames_.size());
  // expecting to be the polarity for proof goals, not frames
  // e.g. a conjunction
  assert(!c.disjunction);

  assert(solver_context_ == 0);
  push_solver_context();

  // F[i-1]
  assert_frame_labels(i - 1);
  // -c
  solver_->assert_formula(solver_->make_term(Not, c.term));
  // Trans
  assert_trans_label();

  // use assumptions for c' so we can get cheap initial
  // generalization if the check is unsat

  // NOTE: relying on same order between assumps_ and c.children
  assumps_.clear();
  {
    // TODO shuffle assumps and (a copy of) c.children
    //      if random seed is set
    Term lbl, ccnext;
    for (const auto & cc : c.children) {
      ccnext = ts_.next(cc);
      lbl = label(ccnext);
      if (lbl != ccnext && !is_global_label(lbl)) {
        // only need to add assertion if the label is not the same as ccnext
        // could be the same if ccnext is already a literal
        // and is not already in a global assumption
        solver_->assert_formula(solver_->make_term(Implies, lbl, ccnext));
      }
      assumps_.push_back(lbl);
    }
  }

  Result r = check_sat_assuming(assumps_);
  if (r.is_sat()) {
    if (get_pred) {
      out = get_model_ic3formula();
      if (options_.ic3_pregen_) {
        predecessor_generalization_and_fix(i, c.term, out);
        assert(out.term);
        assert(out.children.size());
        assert(!out.disjunction);  // expecting a conjunction
      }
    }
    assert(ic3formula_check_valid(out));
  } else if (options_.ic3_unsatcore_gen_) {
    assert(r.is_unsat());  // not expecting to get unknown

    // Use unsat core to get cheap generalization
    UnorderedTermSet core;
    solver_->get_unsat_assumptions(core);
    assert(core.size());

    TermVec gen;  // cheap unsat-core generalization of c
    TermVec rem;  // conjuncts removed by unsat core
    // might need to be re-added if it
    // ends up intersecting with initial
    assert(assumps_.size() == c.children.size());
    for (size_t i = 0; i < assumps_.size(); ++i) {
      if (core.find(assumps_.at(i)) == core.end()) {
        rem.push_back(c.children.at(i));
      } else {
        gen.push_back(c.children.at(i));
      }
    }

    fix_if_intersects_initial(gen, rem);
    assert(gen.size() >= core.size());

    // keep it as a conjunction for now
    out = ic3formula_conjunction(gen);
  } else {
    assert(r.is_unsat());  // not expecting to get unknown
    // don't generalize with an unsat core, just keep c
    out = c;
  }

  if (r.is_sat() && witness_refs && witness_ref_out && witness_val_out) {
    try_extract_witness_from_refs(
        *witness_refs, true, *witness_ref_out, *witness_val_out);
  }

  pop_solver_context();
  assert(!solver_context_);

  if (r.is_sat() && get_pred) {
    assert(out.term);
    assert(out.children.size());

    // this check needs to be here after the solver context has been popped
    // if i == 1 and there's a predecessor, then it should be an initial state
    assert(i != 1 || check_intersects_initial(out.term));

    // should never intersect with a frame before F[i-1]
    // otherwise, this predecessor should have been found
    // in a previous step (before a new frame was pushed)
    assert(i < 2 || !check_intersects(out.term, get_frame_term(i - 2)));
  }

  assert(!r.is_unknown());
  return r.is_unsat();
}

// Helper methods

bool IC3Base::block_all()
{
  assert(!solver_context_);
  ProofGoalQueue proof_goals;
  IC3Formula goal;
  size_t inner_iters = 0;
  while (reaches_bad(goal)) {
    assert(goal.term);            // expecting non-null
    assert(proof_goals.empty());  // bad should be the first goal each iteration
    proof_goals.new_proof_goal(goal, frontier_idx(), nullptr);

    // Poll for LLM candidates after capturing CTI contexts
    process_llm_candidates();

    while (!proof_goals.empty()) {
      // Periodically poll for LLM candidates during blocking
      if (++inner_iters % 50 == 0) {
        process_llm_candidates();
      }
      const ProofGoal * pg = proof_goals.top();

      if (!pg->idx) {
        // went all the way back to initial
        // need to create a new proof goal that's not managed by the queue
        reconstruct_trace(pg, cex_);

        // in case this is spurious, clear the queue of proof goals
        // which might not have been precise
        // TODO might have to change this if there's an algorithm
        // that refines but can keep proof goals around
        proof_goals.clear();

        return false;
      }

      if (is_blocked(pg)) {
        logger.log(3,
                   "Skipping already blocked proof goal <{}, {}>",
                   pg->target.term,
                   pg->idx);
        // remove the proof goal since it has already been blocked
        assert(pg == proof_goals.top());
        proof_goals.pop();
        continue;
      }

      IC3Formula collateral;  // populated by rel_ind_check
      if (rel_ind_check(pg->idx, pg->target, collateral)) {
        // this proof goal can be blocked
        assert(!solver_context_);
        assert(collateral.term);
        logger.log(
            3, "Blocking term at frame {}: {}", pg->idx, pg->target.term);

        // remove the proof goal now that it has been blocked
        assert(pg == proof_goals.top());
        proof_goals.pop();

        if (options_.ic3_indgen_) {
          collateral = inductive_generalization(pg->idx, collateral);
        } else {
          // just negate the term
          collateral = ic3formula_negate(collateral);
        }

        size_t idx = find_highest_frame(pg->idx, collateral);
        assert(idx >= pg->idx);

        assert(collateral.disjunction);
        assert(collateral.term);
        assert(collateral.children.size());
        constrain_frame(idx, collateral);

        // re-add the proof goal at a higher frame if not blocked
        // up to the frontier
        if (idx < frontier_idx()) {
          assert(!pg->target.disjunction);
          proof_goals.new_proof_goal(pg->target, idx + 1, pg->next);
        }

      } else {
        // could not block this proof goal
        assert(collateral.term);
        proof_goals.new_proof_goal(collateral, pg->idx - 1, pg);
      }
    }  // end while(!proof_goals.empty())

    assert(!(goal = IC3Formula()).term);  // in debug mode, reset it
  }  // end while(reaches_bad(goal))

  assert(proof_goals.empty());
  return true;
}

bool IC3Base::is_blocked(const ProofGoal * pg)
{
  // syntactic check
  for (size_t i = pg->idx; i < frames_.size(); ++i) {
    const vector<IC3Formula> & Fi = frames_.at(i);
    for (size_t j = 0; j < Fi.size(); ++j) {
      if (subsumes(Fi[j], ic3formula_negate(pg->target))) {
        return true;
      }
    }
  }

  // now semantic check
  assert(solver_context_ == 0);

  push_solver_context();
  assert_frame_labels(pg->idx);
  solver_->assert_formula(pg->target.term);
  Result r = check_sat();
  pop_solver_context();

  return r.is_unsat();
}

bool IC3Base::propagate(size_t i)
{
  assert(!solver_context_);
  assert(i < frontier_idx());

  vector<IC3Formula> & Fi = frames_.at(i);

  size_t k = 0;
  IC3Formula gen;
  for (size_t j = 0; j < Fi.size(); ++j) {
    const IC3Formula & c = Fi.at(j);
    assert(c.disjunction);
    assert(c.term);
    assert(c.children.size());

    // NOTE: rel_ind_check works on conjunctions
    //       need to negate
    if (rel_ind_check(i + 1, ic3formula_negate(c), gen, false)) {
      // can push to next frame
      // got unsat-core based generalization
      assert(gen.term);
      assert(gen.children.size());
      constrain_frame(i + 1, ic3formula_negate(gen), false);
    } else {
      // have to keep this one at this frame
      Fi[k++] = c;
    }
  }

  // get rid of garbage at end of frame
  Fi.resize(k);

  return Fi.empty();
}

void IC3Base::predecessor_generalization_and_fix(size_t i,
                                                 const Term & c,
                                                 IC3Formula & pred)
{
  TermVec orig_pred_children;
  if (approx_pregen_) {
    assert(!pred.disjunction);
    // save original predecessor conjuncts
    orig_pred_children = pred.children;
    assert(orig_pred_children.size());
  }

  predecessor_generalization(i, c, pred);

  if (approx_pregen_ && i >= 2) {
    TermVec dropped;
    assert(orig_pred_children.size());
    TermVec pred_children = pred.children;
    UnorderedTermSet reduced_pred_children(pred_children.begin(),
                                           pred_children.end());
    for (const auto & cc : orig_pred_children) {
      if (reduced_pred_children.find(cc) == reduced_pred_children.end()) {
        dropped.push_back(cc);
      }
    }
    // if predecessor generalization is approximate
    // need to make sure it does not intersect with F[i-2]
    Term formula = get_frame_term(i - 2);
    formula = solver_->make_term(And, formula, pred.term);
    bool unsat =
        reducer_.reduce_assump_unsatcore(formula, dropped, pred_children);
    assert(unsat);
    pred = ic3formula_conjunction(pred_children);
  }

  assert(pred.term);
  assert(pred.children.size());
  assert(!pred.disjunction);  // expecting a conjunction
}

void IC3Base::push_frame()
{
  assert(frame_labels_.size() == frames_.size());
  // pushes an empty frame
  frame_labels_.push_back(
      solver_->make_symbol("__frame_label_" + std::to_string(frames_.size()),
                           solver_->make_sort(BOOL)));
  frames_.push_back({});

  if (frames_.size() > 1) {
    // always start (non-initial) frame with property
    // not actually adding to frames_ because might not be a valid IC3Formula
    // plus we don't need to do extra work to propagate it
    Term prop = smart_not(bad_);
    solver_->assert_formula(
        solver_->make_term(Implies, frame_labels_.back(), prop));
  }
}

void IC3Base::constrain_frame(size_t i,
                              const IC3Formula & constraint,
                              bool new_constraint)
{
  assert(solver_context_ == 0);
  assert(i < frame_labels_.size());
  assert(constraint.disjunction);
  assert(ts_.only_curr(constraint.term));

  if (new_constraint) {
    for (size_t j = 1; j <= i; ++j) {
      vector<IC3Formula> & Fj = frames_.at(j);
      size_t k = 0;
      for (size_t l = 0; l < Fj.size(); ++l) {
        if (!subsumes(constraint, Fj[l])) {
          Fj[k++] = Fj[l];
        }
      }
      Fj.resize(k);
    }
  }

  assert(i > 0);  // there's a special case for frame 0

  constrain_frame_label(i, constraint);
  frames_.at(i).push_back(constraint);

  dump_ic3ia_frame_clause(this, i, constraint, constraint.children);
}

void IC3Base::constrain_frame_label(size_t i, const IC3Formula & constraint)
{
  assert(frame_labels_.size() == frames_.size());

  solver_->assert_formula(
      solver_->make_term(Implies, frame_labels_.at(i), constraint.term));
}

void IC3Base::assert_frame_labels(size_t i) const
{
  // never expecting to assert a frame at base context
  assert(solver_context_ > 0);
  assert(frame_labels_.size() == frames_.size());
  Term assump;
  for (size_t j = 0; j < frame_labels_.size(); ++j) {
    assump = frame_labels_[j];
    if (j < i) {
      // optimization: disable the unused constraints
      // by asserting the negated label
      assump = solver_->make_term(Not, assump);
    }
    assert(assump);  // assert that it's non-null
    solver_->assert_formula(assump);
  }
}

Term IC3Base::get_frame_term(size_t i) const
{
  // TODO: decide if frames should hold IC3Formulas or terms
  //       need to special case initial state if using IC3Formulas
  if (i == 0) {
    // F[0] is always the initial states constraint
    return ts_.init();
  }

  Term res = solver_true_;
  for (size_t j = i; j < frames_.size(); ++j) {
    for (const auto & u : frames_[j]) {
      res = solver_->make_term(And, res, u.term);
    }
  }

  // the property is implicitly part of the frame
  res = solver_->make_term(And, res, smart_not(bad_));
  return res;
}

void IC3Base::assert_trans_label() const
{
  // shouldn't be a scenario where trans is asserted at base context
  // just because of how IC3 works
  assert(solver_context_ > 0);
  solver_->assert_formula(trans_label_);
}

bool IC3Base::check_intersects(const Term & A, const Term & B)
{
  // should only do this check starting from context 0
  // don't want polluting assumptions
  assert(solver_context_ == 0);
  push_solver_context();
  solver_->assert_formula(A);
  solver_->assert_formula(B);
  Result r = check_sat();
  pop_solver_context();
  return r.is_sat();
}

bool IC3Base::check_intersects_initial(const Term & t)
{
  return check_intersects(init_label_, t);
}

string IC3Base::format_llm_term_value(const Term & val) const
{
  if (!val || !val->is_value()) return "";
  Sort sort = val->get_sort();
  if (sort->get_sort_kind() == BOOL) {
    return val == solver_true_ ? "1" : "0";
  }
  return val->to_string();
}

bool IC3Base::try_extract_witness_from_refs(
    const vector<IC3FrameDisjunct> & refs,
    bool use_next_state,
    string & ref_out,
    string & val_out) const
{
  assert(solver_context_ > 0);
  for (const auto & d : refs) {
    if (d.ref.empty()) continue;
    try {
      Term sym = ts_.lookup(d.ref);
      Term query = use_next_state ? ts_.next(sym) : sym;
      Term model_val = solver_->get_value(query);
      string formatted = format_llm_term_value(model_val);
      if (formatted.empty()) continue;
      ref_out = d.ref;
      val_out = formatted;
      return true;
    } catch (...) {
      continue;
    }
  }
  return false;
}

bool IC3Base::check_intersects_initial_with_witness(
    const Term & t,
    const vector<IC3FrameDisjunct> & refs,
    string & ref_out,
    string & val_out)
{
  assert(solver_context_ == 0);
  push_solver_context();
  solver_->assert_formula(init_label_);
  solver_->assert_formula(t);
  Result r = check_sat();
  const bool intersects = r.is_sat();
  if (intersects) {
    try_extract_witness_from_refs(refs, false, ref_out, val_out);
  }
  pop_solver_context();
  return intersects;
}

void IC3Base::fix_if_intersects_initial(TermVec & to_keep, const TermVec & rem)
{
  // TODO: there's a tricky issue here. The reducer doesn't have the label
  // assumptions so we can't use init_label_ here. need to come up with a
  // better interface. Should we add label assumptions to reducer?
  if (rem.size() != 0) {
    Term formula = solver_->make_term(And, ts_.init(), make_and(to_keep));

    bool success = reducer_.reduce_assump_unsatcore(formula,
                                                    rem,
                                                    to_keep,
                                                    NULL,
                                                    options_.ic3_gen_max_iter_,
                                                    options_.random_seed_);
    assert(success);
  }
}

size_t IC3Base::find_highest_frame(size_t i, IC3Formula & u)
{
  assert(!solver_context_);
  assert(u.disjunction);
  assert(u.term);
  assert(u.children.size());

  IC3Formula conj = ic3formula_negate(u);
  IC3Formula gen;
  size_t j = i;
  for (; j < frontier_idx(); ++j) {
    assert(!conj.disjunction);
    if (rel_ind_check(j + 1, conj, gen, false)) {
      std::swap(conj, gen);
    } else {
      break;
    }
  }
  assert(!conj.disjunction);
  assert(conj.term);
  assert(conj.children.size());

  u = ic3formula_negate(conj);
  assert(u.disjunction);
  assert(u.term);
  assert(u.children.size());
  return j;
}

TermVec IC3Base::get_input_values() const
{
  TermVec out_inputs;
  out_inputs.reserve(ts_.inputvars().size());
  for (const auto & iv : ts_.inputvars()) {
    out_inputs.push_back(solver_->make_term(Equal, iv, solver_->get_value(iv)));
  }
  return out_inputs;
}

TermVec IC3Base::get_next_state_values() const
{
  TermVec out_nexts;
  out_nexts.reserve(ts_.statevars().size());
  Term nv;
  for (const auto & sv : ts_.statevars()) {
    nv = ts_.next(sv);
    out_nexts.push_back(solver_->make_term(Equal, nv, solver_->get_value(nv)));
  }
  return out_nexts;
}

void IC3Base::reconstruct_trace(const ProofGoal * pg, TermVec & out)
{
  assert(!solver_context_);
  assert(pg);
  assert(pg->target.term);
  assert(check_intersects_initial(pg->target.term));

  out.clear();
  while (pg) {
    out.push_back(pg->target.term);
    assert(ts_.only_curr(out.back()));
    pg = pg->next;
  }

  // always add bad as last state so it's a full trace
  // NOTE this is because the reaches_bad implementation
  out.push_back(bad_);
}

Term IC3Base::make_and(TermVec vec, SmtSolver slv) const
{
  if (!slv) {
    slv = solver_;
  }

  if (vec.size() == 0) {
    return slv->make_term(true);
  }

  // sort the conjuncts
  std::sort(vec.begin(), vec.end(), term_hash_lt);
  Term res = vec[0];
  for (size_t i = 1; i < vec.size(); ++i) {
    res = slv->make_term(And, res, vec[i]);
  }
  return res;
}

void IC3Base::reset_solver()
{
  assert(solver_context_ == 0);

  if (failed_to_reset_solver_) {
    // don't even bother trying
    // this solver doesn't support reset_assertions
    return;
  }

  try {
    solver_->reset_assertions();

    // Now need to add back in constraints at context level 0
    logger.log(2, "IC3Base: Reset solver and now re-adding constraints.");

    // define init, trans, and bad labels
    assert(init_label_ == frame_labels_.at(0));
    solver_->assert_formula(
        solver_->make_term(Implies, init_label_, ts_.init()));

    solver_->assert_formula(
        solver_->make_term(Implies, trans_label_, ts_.trans()));

    solver_->assert_formula(solver_->make_term(Implies, bad_label_, bad_));

    Term prop = smart_not(bad_);
    for (size_t i = 0; i < frames_.size(); ++i) {
      assert(i < frame_labels_.size());
      // all frames except for F[0] include the property
      // but it's not stored in frames_ because it's not guaranteed to
      // be a valid IC3Formula
      if (i) {
        solver_->assert_formula(
            solver_->make_term(Implies, frame_labels_.at(i), prop));
      }

      // add all other constraints from the frame
      for (const auto & constraint : frames_.at(i)) {
        constrain_frame_label(i, constraint);
      }
    }
  }
  catch (SmtException & e) {
    logger.log(1,
               "Failed to reset solver (underlying solver must not support "
               "it). Disabling solver resets for rest of run.");
    failed_to_reset_solver_ = true;
  }

  num_check_sat_since_reset_ = 0;
}

Term IC3Base::label(const Term & t)
{
  auto it = labels_.find(t);
  if (it != labels_.end()) {
    return labels_.at(t);
  }

  Term l;
  if (is_lit(t, boolsort_)) {
    // this can be the label itself
    l = t;
  } else {
    unsigned i = 0;
    while (true) {
      try {
        l = solver_->make_symbol(
            "assump_" + std::to_string(t->hash()) + "_" + std::to_string(i),
            solver_->make_sort(BOOL));
        break;
      }
      catch (IncorrectUsageException & e) {
        ++i;
      }
      catch (SmtException & e) {
        throw e;
      }
    }
  }
  assert(l);

  labels_[t] = l;
  return l;
}

bool IC3Base::is_global_label(const Term & l) const
{
  return (l == trans_label_ || l == bad_label_
          || std::count(frame_labels_.begin(), frame_labels_.end(), l));
}

smt::Term IC3Base::smart_not(const Term & t) const
{
  const Op & op = t->get_op();
  if (op == Not) {
    TermVec children(t->begin(), t->end());
    assert(children.size() == 1);
    return children[0];
  } else {
    return solver_->make_term(Not, t);
  }
}

// LLM-guided generalization methods

static std::string simplify_cti_literal(const smt::Term & term)
{
  smt::Op op = term->get_op();
  smt::PrimOp po = op.prim_op;

  // Leaf: symbol/variable/constant
  if (term->is_symbol() || term->is_symbolic_const()) {
    return term->to_string();
  }

  // Constants (bitvector values like #b0000, #b1)
  if (po == smt::PrimOp::NUM_OPS_AND_NULL && term->is_value()) {
    return term->to_string();
  }

  // Recurse children
  std::vector<std::string> args;
  for (auto it = term->begin(); it != term->end(); ++it) {
    args.push_back(simplify_cti_literal(*it));
  }

  auto unary = [&](const std::string & sym) {
    return sym + (args.size() > 0 ? args[0] : "?");
  };
  auto binary = [&](const std::string & sym) {
    return "(" + (args.size() > 0 ? args[0] : "?") + " " + sym + " "
           + (args.size() > 1 ? args[1] : "?") + ")";
  };

  switch (po) {
    case smt::Not:        return "~" + (args.size() > 0 ? args[0] : "?");
    case smt::And:        return binary("∧");
    case smt::Or:         return binary("∨");
    case smt::Xor:        return binary("⊕");
    case smt::Implies:    return binary("→");
    case smt::Equal:      return binary("=");
    case smt::Distinct:   return binary("≠");
    case smt::Ite:
      return "ite(" + (args.size() > 0 ? args[0] : "?") + ", "
             + (args.size() > 1 ? args[1] : "?") + ", "
             + (args.size() > 2 ? args[2] : "?") + ")";
    case smt::BVNot:      return "~" + (args.size() > 0 ? args[0] : "?");
    case smt::BVNeg:      return "-" + (args.size() > 0 ? args[0] : "?");
    case smt::BVAnd:      return binary("&");
    case smt::BVOr:       return binary("|");
    case smt::BVXor:      return binary("^");
    case smt::BVAdd:      return binary("+");
    case smt::BVSub:      return binary("-");
    case smt::BVMul:      return binary("*");
    case smt::BVUgt:      return binary(">");
    case smt::BVUge:      return binary("≥");
    case smt::BVUlt:      return binary("<");
    case smt::BVUle:      return binary("≤");
    case smt::BVSgt:      return binary(">ₛ");
    case smt::BVSge:      return binary("≥ₛ");
    case smt::BVSlt:      return binary("<ₛ");
    case smt::BVSle:      return binary("≤ₛ");
    case smt::BVSdiv:     return binary("/ₛ");
    case smt::BVUdiv:     return binary("/");
    case smt::BVShl:      return binary("<<");
    case smt::BVAshr:     return binary(">>ₐ");
    case smt::BVLshr:     return binary(">>");
    case smt::BVComp:     return binary("==ₓ");
    case smt::Concat:     return binary("++");
    case smt::Extract: {
      std::string inner = args.size() > 0 ? args[0] : "?";
      return inner + "[" + std::to_string(op.idx0) + ":"
             + std::to_string(op.idx1) + "]";
    }
    case smt::Zero_Extend:
      return "zero_ext(" + (args.size() > 0 ? args[0] : "?") + ")";
    case smt::Sign_Extend:
      return "sign_ext(" + (args.size() > 0 ? args[0] : "?") + ")";
    case smt::Select:
      return (args.size() > 0 ? args[0] : "?") + "["
             + (args.size() > 1 ? args[1] : "?") + "]";
    case smt::BVUrem:
      return binary("%");
    default:
      return term->to_string();
  }
}

void IC3Base::set_llm_generalizer(std::shared_ptr<LLMGeneralizer> gen)
{
  llm_gen_ = gen;
}

static string extract_state_ref_name(const string & name)
{
  size_t pos = name.find("state");
  if (pos == string::npos) return name;
  size_t end = pos + 5;
  while (end < name.size() && isdigit(static_cast<unsigned char>(name[end]))) {
    ++end;
  }
  if (end > pos + 5) return name.substr(pos, end - pos);
  return name;
}

static void fill_cti_literal_from_term(const smt::Term & child, CTILiteral & lit)
{
  smt::Term inner = child;
  bool polarity = true;
  if (child->get_op() == smt::Not) {
    inner = *(child->begin());
    polarity = false;
  }

  smt::Op op = inner->get_op();
  if (op.prim_op == smt::Equal) {
    auto it = inner->begin();
    if (it != inner->end()) {
      smt::Term lhs = *it;
      smt::Term rhs = *std::next(it);
      lit.varname = extract_state_ref_name(lhs->to_string());
      lit.value = rhs->to_string();
      if (lit.value == "true") lit.value = "1";
      if (lit.value == "false") lit.value = "0";
      lit.expr = lit.varname + " = " + lit.value;
      if (!polarity) lit.expr = "not (" + lit.expr + ")";
      return;
    }
  }
  if (inner->is_symbol() || inner->is_symbolic_const()) {
    lit.varname = extract_state_ref_name(inner->to_string());
    if (inner->get_sort()->get_sort_kind() == smt::BOOL) {
      lit.value = polarity ? "true" : "false";
    } else {
      lit.value = polarity ? "1" : "0";
    }
    lit.expr = lit.varname + " = " + lit.value;
    return;
  }

  lit.varname = simplify_cti_literal(child);
  lit.expr = lit.varname;
  lit.value = polarity ? "true" : "false";
}

std::vector<CTILiteral> IC3Base::collect_cti_literals(
    const IC3Formula & cube) const
{
  std::vector<CTILiteral> lits;
  assert(!cube.disjunction);
  for (const auto & child : cube.children) {
    CTILiteral lit;
    lit.id = lits.size();
    lit.term = child;
    fill_cti_literal_from_term(child, lit);
    // Truncate very long simplified strings
    if (lit.varname.size() > 200) {
      lit.varname = lit.varname.substr(0, 197) + "...";
    }
    if (lit.expr.size() > 260) {
      lit.expr = lit.expr.substr(0, 257) + "...";
    }
    lit.kind = "unknown";
    lit.signals.push_back(lit.varname);
    lits.push_back(lit);
  }
  return lits;
}

void IC3Base::init_llm_symbol_registry(
    const unordered_map<string, string> & verilog_map)
{
  if (!llm_gen_) return;
  unordered_map<string, SymbolRegistryEntry> registry;
  for (const auto & sv : ts_.statevars()) {
    string name = simplify_cti_literal(sv);
    SymbolRegistryEntry e;
    e.kind = "state";
    e.width = sv->get_sort()->get_width();
    size_t pos = name.find("state");
    if (pos != string::npos) {
      try {
        e.btor2_line = stoul(name.substr(pos + 5));
      } catch (...) {
        e.btor2_line = 0;
      }
    }
    auto it = verilog_map.find(name);
    if (it != verilog_map.end()) e.verilog = it->second;
    registry[name] = e;
  }
  for (const auto & iv : ts_.inputvars()) {
    string name = simplify_cti_literal(iv);
    SymbolRegistryEntry e;
    e.kind = "input";
    e.width = iv->get_sort()->get_width();
    auto it = verilog_map.find(name);
    if (it != verilog_map.end()) e.verilog = it->second;
    registry[name] = e;
  }
  llm_gen_->set_symbol_registry(registry);
  string bad_expr = simplify_cti_literal(bad_);
  llm_gen_->write_benchmark_context(options_.filename_, bad_expr);
}

IC3Formula IC3Base::build_block_clause_from_disjuncts(
    const vector<IC3FrameDisjunct> & disjuncts) const
{
  TermVec children;
  for (const auto & d : disjuncts) {
    try {
      Term sym = ts_.lookup(d.ref);
      Sort sort = sym->get_sort();
      Term val;
      if (sort->get_sort_kind() == BOOL) {
        if (d.rhs == "true" || d.rhs == "1") val = solver_->make_term(true);
        else if (d.rhs == "false" || d.rhs == "0")
          val = solver_->make_term(false);
        else throw runtime_error("invalid bool rhs");
      } else {
        string s = d.rhs;
        if (s.rfind("#b", 0) == 0) {
          val = solver_->make_term(s.substr(2), sort);
        } else {
          val = solver_->make_term(stoul(s), sort);
        }
      }
      Term lit;
      if (d.op == "eq" || d.op.empty()) {
        lit = solver_->make_term(Equal, sym, val);
      } else if (d.op == "ne") {
        lit = solver_->make_term(Distinct, sym, val);
      } else {
        throw runtime_error("unsupported op");
      }
      if (!d.polarity) lit = solver_->make_term(Not, lit);
      children.push_back(lit);
    } catch (const exception & e) {
      logger.log(1, "IC3Frame block build failed: {}", e.what());
      return IC3Formula();
    }
  }
  if (children.empty()) return IC3Formula();
  Term t = children.size() == 1 ? children[0] : solver_->make_term(Or, children);
  return IC3Formula(t, children, true);
}

bool IC3Base::validate_frame_response_vocab(
    const IC3FrameResponse & resp) const
{
  for (const auto & d : resp.block_disjuncts) {
    try {
      ts_.lookup(d.ref);
    } catch (...) {
      return false;
    }
  }
  if (resp.has_refine_predicate) {
    vector<string> pred_refs;
    collect_predicate_refs(resp.refine_predicate, pred_refs);
    for (const auto & ref : pred_refs) {
      try {
        ts_.lookup(ref);
      } catch (...) {
        return false;
      }
    }
  }
  for (const auto & sym : resp.symbols_used) {
    try {
      ts_.lookup(sym);
    } catch (...) {
      return false;
    }
  }
  return true;
}

bool IC3Base::try_apply_llm_refine_predicate(const Term & pred)
{
  (void)pred;
  return false;
}

static std::string cti_json_escape(const std::string & s)
{
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      default: out += c;
    }
  }
  return out;
}

namespace {

void dump_ic3ia_cti(const CTIContext & ctx, const smt::TermVec & children) {
  const char * env = std::getenv("PONO_LLM_DUMP_IC3IA");
  if (!env || std::string(env) == "0" || std::string(env) == "") return;

  std::string dir = std::getenv("PONO_LLM_DUMP_DIR")
                        ? std::getenv("PONO_LLM_DUMP_DIR")
                        : "logs/pono_frame_dump";

  static int cti_counter = 0;
  static std::ofstream cti_file;
  static bool cti_opened = false;
  if (!cti_opened) {
    std::string path = dir + "/qspiflash_p040_ctis.jsonl";
    cti_file.open(path, std::ios::out | std::ios::app);
    cti_opened = true;
  }
  if (!cti_file.is_open()) return;

  cti_file << "{";
  cti_file << "\"type\":\"cti\",";
  cti_file << "\"benchmark\":\"qspiflash_divfive-p040\",";
  cti_file << "\"cti_id\":\"cti_" << cti_counter << "\",";
  cti_file << "\"frame\":" << ctx.frame_idx << ",";

  cti_file << "\"cube\":[";
  for (size_t i = 0; i < ctx.literals.size(); ++i) {
    if (i > 0) cti_file << ",";
    cti_file << "{";
    cti_file << "\"varname\":\"" << cti_json_escape(ctx.literals[i].varname) << "\",";
    cti_file << "\"expr\":\"" << cti_json_escape(ctx.literals[i].expr) << "\",";
    cti_file << "\"value\":\"" << cti_json_escape(ctx.literals[i].value) << "\",";
    cti_file << "\"kind\":\"" << cti_json_escape(ctx.literals[i].kind) << "\"";
    cti_file << "}";
  }
  cti_file << "],";

  cti_file << "\"raw_smt\":\"" << cti_json_escape(ctx.literals.empty() ? "" : ctx.literals[0].expr) << "\"";
  cti_file << "}\n";
  cti_file.flush();

  cti_counter++;
}

void dump_ic3ia_frame_clause(const IC3Base * engine,
                             size_t frame_idx,
                             const IC3Formula & clause,
                             const smt::TermVec & literals) {
  const char * env = std::getenv("PONO_LLM_DUMP_IC3IA");
  if (!env || std::string(env) == "0" || std::string(env) == "") return;

  std::string dir = std::getenv("PONO_LLM_DUMP_DIR")
                        ? std::getenv("PONO_LLM_DUMP_DIR")
                        : "logs/pono_frame_dump";

  static int clause_counter = 0;
  static std::ofstream clause_file;
  static bool clause_opened = false;
  if (!clause_opened) {
    std::string path = dir + "/qspiflash_p040_frames.jsonl";
    clause_file.open(path, std::ios::out | std::ios::app);
    clause_opened = true;
  }
  if (!clause_file.is_open()) return;

  clause_file << "{";
  clause_file << "\"type\":\"clause\",";
  clause_file << "\"benchmark\":\"qspiflash_divfive-p040\",";
  clause_file << "\"frame\":" << frame_idx << ",";
  clause_file << "\"clause_id\":\"F" << frame_idx << "_C" << clause_counter << "\",";
  clause_file << "\"literal_count\":" << literals.size() << ",";
  clause_file << "\"is_disjunction\":" << (clause.disjunction ? "true" : "false") << ",";

  clause_file << "\"literals\":[";
  for (size_t i = 0; i < literals.size(); ++i) {
    if (i > 0) clause_file << ",";
    std::string raw = literals[i]->to_string();

    // Try to resolve via virtual method (IC3IA overrides with lbl2pred_)
    std::string resolved_raw_expr;
    bool resolved_is_negated = false;
    bool resolved_ok = engine->resolve_frame_literal_for_dump(
        literals[i], resolved_raw_expr, resolved_is_negated);

    // Extract variable names from the raw SMT string
    // Frame literals look like: (= stateNN #bV) or (not (= stateNN #bV))
    std::string var_expr = resolved_ok ? resolved_raw_expr : raw;
    std::string vars_json = "[";
    std::string vals_json = "{";
    bool first_v = true;
    size_t pos = 0;
    while (pos < var_expr.size()) {
      size_t st_pos = var_expr.find("state", pos);
      if (st_pos == std::string::npos) break;
      size_t ns = st_pos + 5;
      while (ns < var_expr.size() && std::isdigit(var_expr[ns])) ns++;
      if (ns == st_pos + 5) { pos = ns; continue; }
      std::string st_var = var_expr.substr(st_pos, ns - st_pos);
      if (!first_v) { vars_json += ","; vals_json += ","; }
      vars_json += "\"" + st_var + "\"";
      // Try to get the value
      std::string val = "?";
      size_t bv = var_expr.find("#b", ns);
      if (bv != std::string::npos) {
        size_t vs = bv + 2;
        size_t ve = vs;
        while (ve < var_expr.size() && (std::isdigit(var_expr[ve]) || var_expr[ve] == 'x' || (var_expr[ve] >= 'a' && var_expr[ve] <= 'f'))) ve++;
        if (ve > vs) val = var_expr.substr(vs, ve - vs);
      }
      vals_json += "\"" + st_var + "\":\"" + val + "\"";
      first_v = false;
      pos = ns + 1;
    }
    vars_json += "]";
    vals_json += "}";

    clause_file << "{";
    clause_file << "\"raw\":\"" << cti_json_escape(raw) << "\",";
    clause_file << "\"resolved\":" << (resolved_ok ? "true" : "false") << ",";
    clause_file << "\"polarity\":" << (resolved_is_negated ? "false" : "true") << ",";
    clause_file << "\"raw_expr\":\"" << cti_json_escape(resolved_ok ? resolved_raw_expr : raw) << "\",";
    clause_file << "\"variables\":" << vars_json << ",";
    clause_file << "\"state_values\":" << vals_json;
    clause_file << "}";
  }
  clause_file << "],";

  clause_file << "\"raw_smt\":\"" << cti_json_escape(clause.term->to_string()) << "\"";
  clause_file << "}\n";
  clause_file.flush();

  clause_counter++;
}

}  // namespace

void IC3Base::capture_cti_context(size_t frame_idx, const IC3Formula & cube)
{
  // Build CTI context (always, for dump support even without LLM)
  CTIContext ctx;
  ctx.frame_idx = frame_idx;
  std::string raw_prop = simplify_cti_literal(bad_);
  ctx.property_name = raw_prop.size() > 200 ? raw_prop.substr(0, 197) + "..."
                                            : raw_prop;
  ctx.literals = collect_cti_literals(cube);
  if (llm_gen_) {
    ctx.cti_id = llm_gen_->make_cti_id(frame_idx, ctx.literals);
  }

  // Dump CTI for impact analysis (independent of LLM)
  dump_ic3ia_cti(ctx, cube.children);

  if (!llm_gen_) return;
  if (!llm_gen_->is_async_cti()) return;
  llm_gen_->buffer_cti_context(frame_idx, ctx, cube.children);
}

static bool term_to_disjunct_json(const smt::Term & term,
                                  const smt::Term & inner,
                                  bool polarity,
                                  ostringstream & out)
{
  smt::Op op = inner->get_op();
  if (op.prim_op == smt::Equal) {
    auto it = inner->begin();
    if (it != inner->end()) {
      smt::Term lhs = *it;
      smt::Term rhs = *std::next(it);
    string ref = extract_state_ref_name(lhs->to_string());
    string rhs_s = rhs->to_string();
    if (rhs_s == "true") rhs_s = "1";
    if (rhs_s == "false") rhs_s = "0";
    out << "{\"atom\":{";
    out << "\"ref\":\"" << cti_json_escape(ref) << "\",";
    out << "\"rhs\":\"" << cti_json_escape(rhs_s) << "\"},";
    out << "\"polarity\":" << (polarity ? "true" : "false") << "}";
    return true;
    }
  }
  if (inner->is_symbol() || inner->is_symbolic_const()) {
    string ref = extract_state_ref_name(inner->to_string());
    string rhs_s = polarity ? "1" : "0";
    out << "{\"atom\":{";
    out << "\"ref\":\"" << cti_json_escape(ref) << "\",";
    out << "\"rhs\":\"" << rhs_s << "\"},";
    out << "\"polarity\":" << (polarity ? "true" : "false") << "}";
    return true;
  }
  (void)term;
  return false;
}

std::string IC3Base::serialize_frame_snapshot_json(size_t frame_idx) const
{
  ostringstream out;
  out << "{\"frame_idx\":" << frame_idx << ",\"clauses\":[";
  if (frame_idx < frames_.size()) {
    bool first_clause = true;
    for (const auto & clause : frames_.at(frame_idx)) {
      if (!first_clause) out << ",";
      first_clause = false;
      out << "{\"disjuncts\":[";
      bool first_disj = true;
      for (const auto & child : clause.children) {
        if (!first_disj) out << ",";
        first_disj = false;
        smt::Term inner = child;
        bool polarity = true;
        if (child->get_op() == smt::Not) {
          inner = *(child->begin());
          polarity = false;
        }
        ostringstream disj;
        if (!term_to_disjunct_json(child, inner, polarity, disj)) {
          out << "{\"atom\":{\"ref\":\"\",\"rhs\":\"\"},";
          out << "\"polarity\":true,\"expr\":\""
              << cti_json_escape(simplify_cti_literal(child)) << "\"}";
        } else {
          out << disj.str();
        }
      }
      out << "]}";
    }
  }
  out << "]}";
  return out.str();
}

void IC3Base::process_llm_candidates()
{
  if (!llm_gen_ || !llm_gen_->enabled()) return;

  auto responses = llm_gen_->poll_responses();
  if (responses.empty()) return;

  std::unordered_map<std::string, std::vector<IC3FrameResponse>> grouped;
  for (auto & resp : responses) {
    grouped[resp.source_cti_id].push_back(resp);
  }

  for (auto & entry : grouped) {
    const std::string & cti_id = entry.first;
    if (llm_gen_->is_cti_accepted(cti_id)) continue;

    if (llm_gen_->stats_.accepted_budget >= options_.llm_accepted_budget_) {
      llm_gen_->stats_.num_budget_skip++;
      continue;
    }

    size_t frame_idx = 0;
    smt::TermVec cube;
    if (cti_id.rfind("batch_", 0) == 0) {
      if (!llm_gen_->lookup_batch_meta(cti_id, frame_idx)) {
        llm_gen_->stats_.num_lookup_miss++;
        continue;
      }
    } else if (!llm_gen_->lookup_cti_meta(cti_id, frame_idx, cube)) {
      llm_gen_->stats_.num_lookup_miss++;
      continue;
    }

    const size_t current_attempt = llm_gen_->feedback_attempt(cti_id);
    bool accepted = false;
    for (auto & resp : entry.second) {
      if (llm_gen_->is_cti_accepted(cti_id)) break;

      const size_t resp_attempt =
          resp.attempt ? resp.attempt : current_attempt;
      if (resp_attempt != current_attempt) {
        llm_gen_->stats_.num_attempt_mismatch++;
        continue;
      }

      if (!validate_frame_response_vocab(resp)) {
        llm_gen_->stats_.num_vocab_fail++;
        llm_gen_->add_feedback(cti_id, resp, "vocab_fail");
        llm_gen_->note_response_processed(cti_id, resp_attempt);
        continue;
      }

      if (resp.has_refine_predicate) {
        Term pred = build_predicate_term(solver_, ts_, resp.refine_predicate);
        if (!pred) {
          llm_gen_->stats_.num_parse_fail++;
          llm_gen_->add_feedback(cti_id, resp, "predicate_parse_fail");
        } else if (try_apply_llm_refine_predicate(pred)) {
          llm_gen_->stats_.num_predicates_added++;
          logger.log(1, "IC3Frame refine_predicate added: {}", pred);
        } else {
          llm_gen_->add_feedback(cti_id, resp, "predicate_rejected");
        }
      }

      if (!resp.has_block) {
        llm_gen_->stats_.num_missing_block++;
        llm_gen_->add_feedback(cti_id, resp, "missing_block");
        llm_gen_->note_response_processed(cti_id, resp_attempt);
        continue;
      }

      IC3Formula blocking = build_block_clause_from_disjuncts(resp.block_disjuncts);
      if (blocking.children.empty()) {
        llm_gen_->stats_.num_parse_fail++;
        llm_gen_->add_feedback(cti_id, resp, "empty_block_clause");
        llm_gen_->note_response_processed(cti_id, resp_attempt);
        continue;
      }

      IC3Formula check_cube = ic3formula_negate(blocking);
      std::string wit_ref;
      std::string wit_val;
      if (check_intersects_initial_with_witness(
              check_cube.term, resp.block_disjuncts, wit_ref, wit_val)) {
        llm_gen_->stats_.num_rejected_initial++;
        llm_gen_->add_feedback(
            cti_id, resp, "rejected_initial", wit_ref, wit_val);
        llm_gen_->note_response_processed(cti_id, resp_attempt);
        continue;
      }

      IC3Formula out;
      wit_ref.clear();
      wit_val.clear();
      if (!rel_ind_check(frame_idx,
                         check_cube,
                         out,
                         false,
                         &resp.block_disjuncts,
                         &wit_ref,
                         &wit_val)) {
        llm_gen_->stats_.num_induction_fail++;
        llm_gen_->add_feedback(
            cti_id, resp, "induction_failed", wit_ref, wit_val);
        llm_gen_->note_response_processed(cti_id, resp_attempt);
        continue;
      }

      constrain_frame(frame_idx, blocking, true);
      llm_gen_->stats_.num_accepted++;
      llm_gen_->stats_.accepted_budget++;
      llm_gen_->mark_accepted(cti_id);
      llm_gen_->note_response_processed(cti_id, resp_attempt);
      accepted = true;
      logger.log(1,
                 "IC3Frame response ACCEPTED at frame {} (disjuncts={})",
                 frame_idx,
                 blocking.children.size());
      logger.log(1, "  Rationale: {}", resp.rationale);
      break;
    }

    if (!accepted && !llm_gen_->is_cti_accepted(cti_id)
        && llm_gen_->all_parallel_samples_received(cti_id, current_attempt)) {
      llm_gen_->finish_attempt(cti_id, frame_idx);
    }
  }

  std::vector<std::string> retries;
  llm_gen_->take_retry_queue(retries);
  for (const std::string & retry_cti_id : retries) {
    if (llm_gen_->is_cti_accepted(retry_cti_id)) continue;
    size_t retry_frame = 0;
    smt::TermVec retry_cube;
    if (retry_cti_id.rfind("batch_", 0) == 0) {
      if (!llm_gen_->lookup_batch_meta(retry_cti_id, retry_frame)) {
        llm_gen_->stats_.num_lookup_miss++;
        continue;
      }
    } else if (!llm_gen_->lookup_cti_meta(retry_cti_id, retry_frame, retry_cube)) {
      llm_gen_->stats_.num_lookup_miss++;
      continue;
    }
    std::string snapshot = serialize_frame_snapshot_json(retry_frame);
    llm_gen_->write_retry_request(retry_cti_id, snapshot);
  }
}

}  // namespace pono
