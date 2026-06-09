#include <memory>
#include <tuple>

#include "core/fts.h"
#include "engines/ic3.h"
#include "engines/llm_generalizer.h"
#include "gtest/gtest.h"
#include "options/options.h"
#include "smt-switch/smt.h"
#include "smt/available_solvers.h"

using namespace pono;
using namespace smt;
using namespace std;

namespace pono_tests {

class IC3UnderTest : public IC3
{
 public:
  IC3UnderTest(const SafetyProperty & p,
               const TransitionSystem & ts,
               const SmtSolver & s,
               PonoOptions & opt)
      : IC3(p, ts, s, opt)
  {
  }

  using IC3Base::build_block_clause_from_disjuncts;
  using IC3Base::try_accept_first_block_clause;
  using IC3Base::validate_block_clause_vocab;
};

class LLMBlockAcceptTest : public ::testing::Test,
                           public ::testing::WithParamInterface<SolverEnum>
{
 protected:
  void SetUp() override
  {
    opts.smt_solver_ = GetParam();
    opts.llm_gen_mode_ = LLM_GEN_ASYNC_CTI;
    s = create_solver_for(opts.smt_solver_, IC3_BOOL, false);
    boolsort = s->make_sort(BOOL);

    fts = std::make_unique<FunctionalTransitionSystem>(s);
    s1 = fts->make_statevar("s1", boolsort);
    s2 = fts->make_statevar("s2", boolsort);
    fts->constrain_init(s->make_term(Not, s1));
    fts->constrain_init(s->make_term(Not, s2));
    fts->assign_next(s1, s->make_term(Or, s1, s2));
    fts->assign_next(s2, s2);

    SafetyProperty p(s, s->make_term(Not, s1));
    ic3 = std::make_unique<IC3UnderTest>(p, *fts, s, opts);

    auto gen = std::make_shared<LLMGeneralizer>(opts, s);
    ic3->set_llm_generalizer(gen);
  }

  PonoOptions opts;
  SmtSolver s;
  Sort boolsort;
  Term s1, s2;
  std::unique_ptr<FunctionalTransitionSystem> fts;
  std::unique_ptr<IC3UnderTest> ic3;
};

TEST_P(LLMBlockAcceptTest, BuildBlockClauseOr)
{
  vector<IC3FrameDisjunct> disjuncts;
  IC3FrameDisjunct d1;
  d1.ref = "s1";
  d1.rhs = "0";
  d1.op = "eq";
  d1.polarity = true;
  disjuncts.push_back(d1);
  IC3FrameDisjunct d2;
  d2.ref = "s2";
  d2.rhs = "1";
  d2.op = "eq";
  d2.polarity = true;
  disjuncts.push_back(d2);

  IC3Formula f = ic3->build_block_clause_from_disjuncts(disjuncts);
  ASSERT_EQ(f.children.size(), 2u);
}

TEST_P(LLMBlockAcceptTest, ValidateVocabRejectsUnknownRef)
{
  vector<IC3FrameDisjunct> disjuncts;
  IC3FrameDisjunct d;
  d.ref = "no_such_state";
  d.rhs = "0";
  d.op = "eq";
  d.polarity = true;
  disjuncts.push_back(d);
  EXPECT_FALSE(ic3->validate_block_clause_vocab(disjuncts));
}

TEST_P(LLMBlockAcceptTest, ValidateVocabAcceptsKnownRefs)
{
  vector<IC3FrameDisjunct> disjuncts;
  for (const char * ref : {"s1", "s2"}) {
    IC3FrameDisjunct d;
    d.ref = ref;
    d.rhs = "0";
    d.op = "eq";
    d.polarity = true;
    disjuncts.push_back(d);
  }
  EXPECT_TRUE(ic3->validate_block_clause_vocab(disjuncts));
}

TEST_P(LLMBlockAcceptTest, ParsedMultiClauseResponsePreservesOrder)
{
  string line =
      R"({"type":"ic3_frame_response","source_cti_id":"batch_f2_a1","sample_id":0,"attempt":1,)"
      R"("block_clauses":[)"
      R"([{"ref":"s1","op":"eq","rhs":"0","polarity":true}],)"
      R"([{"ref":"s2","op":"eq","rhs":"1","polarity":true}])"
      R"(],"rationale":"two clauses"})";
  auto resp = parse_ic3_frame_response_line(line);
  ASSERT_TRUE(resp.valid) << resp.error_msg;
  ASSERT_EQ(resp.block_clauses.size(), 2u);
  EXPECT_EQ(resp.block_clauses[0][0].ref, "s1");
  EXPECT_EQ(resp.block_clauses[1][0].ref, "s2");
  EXPECT_TRUE(ic3->validate_block_clause_vocab(resp.block_clauses[0]));
  EXPECT_TRUE(ic3->validate_block_clause_vocab(resp.block_clauses[1]));
}

INSTANTIATE_TEST_SUITE_P(
    ParametrizedLLMBlockAcceptTests,
    LLMBlockAcceptTest,
    testing::ValuesIn(available_solver_enums()));

}  // namespace pono_tests
