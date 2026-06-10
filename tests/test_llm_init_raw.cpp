#include <memory>
#include <unordered_map>

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

TEST(LLMInitRawHelpersTest, RefFromDigestLitLineParsesSimpleLits)
{
  EXPECT_EQ(ref_from_digest_lit_line("state34=#b1"), "state34");
  EXPECT_EQ(ref_from_digest_lit_line("!state512=1"), "state512");
  EXPECT_EQ(ref_from_digest_lit_line("state5=0"), "state5");
}

TEST(LLMInitRawHelpersTest, RefFromDigestLitLineSkipsComplexLits)
{
  EXPECT_EQ(ref_from_digest_lit_line("(bvor x y)=#b1"), "");
  EXPECT_EQ(ref_from_digest_lit_line("state34=bvor"), "");
  EXPECT_EQ(ref_from_digest_lit_line(""), "");
}

TEST(LLMInitRawHelpersTest, NegateDigestLitToDisjunct)
{
  IC3FrameDisjunct dj;
  ASSERT_TRUE(negate_digest_lit_to_disjunct("state34=#b1", dj));
  EXPECT_EQ(dj.ref, "state34");
  EXPECT_EQ(dj.rhs, "#b1");
  EXPECT_FALSE(dj.polarity);
  ASSERT_TRUE(negate_digest_lit_to_disjunct("!state5=#b0", dj));
  EXPECT_TRUE(dj.polarity);
}

TEST(LLMInitRawHelpersTest, SerializeInitRawJsonEscapesAndOrdersRefs)
{
  vector<string> refs = {"state34", "state512"};
  unordered_map<string, string> values = {
      {"state34", "#b0"},
      {"state512", "1"},
  };
  string json = serialize_init_raw_json(refs, values);
  EXPECT_NE(json.find("\"refs\":[\"state34\",\"state512\"]"), string::npos);
  EXPECT_NE(json.find("\"state34\":\"#b0\""), string::npos);
  EXPECT_NE(json.find("\"state512\":\"1\""), string::npos);
}

class LLMInitRawCollectTest : public ::testing::Test,
                              public ::testing::WithParamInterface<SolverEnum>
{
 protected:
  void SetUp() override
  {
    opts.smt_solver_ = GetParam();
    opts.llm_gen_mode_ = LLM_GEN_ASYNC_CTI;
    opts.llm_init_raw_max_refs_ = 15;
    s = create_solver_for(opts.smt_solver_, IC3_BOOL, false);
    gen = make_shared<LLMGeneralizer>(opts, s);
  }

  static CTILiteral make_lit(const string & ref, const string & rhs)
  {
    CTILiteral lit;
    lit.varname = ref;
    lit.value = rhs;
    lit.polarity = true;
    return lit;
  }

  PonoOptions opts;
  SmtSolver s;
  shared_ptr<LLMGeneralizer> gen;
};

TEST_P(LLMInitRawCollectTest, CollectInitRawRefsRanksDigestLiterals)
{
  CTIContext ctx1;
  ctx1.cti_id = "cti_a";
  ctx1.frame_idx = 3;
  ctx1.literals = {make_lit("state34", "1"), make_lit("state99", "1")};

  CTIContext ctx2;
  ctx2.cti_id = "cti_b";
  ctx2.frame_idx = 3;
  ctx2.literals = {make_lit("state34", "1"), make_lit("state512", "0")};

  TermVec empty;
  gen->buffer_cti_context(3, ctx1, empty);
  gen->buffer_cti_context(3, ctx2, empty);

  vector<string> refs;
  gen->collect_init_raw_refs(3, "", refs);
  ASSERT_GE(refs.size(), 2u);
  EXPECT_EQ(refs[0], "state34");
  EXPECT_NE(find(refs.begin(), refs.end(), "state512"), refs.end());
}

TEST_P(LLMInitRawCollectTest, CollectInitRawRefsIncludesWitnessFeedback)
{
  CTIContext ctx;
  ctx.cti_id = "cti_a";
  ctx.frame_idx = 2;
  ctx.literals = {make_lit("state34", "1")};
  TermVec empty;
  gen->buffer_cti_context(2, ctx, empty);

  IC3FrameResponse rejected;
  rejected.valid = true;
  gen->add_feedback("batch_f2_a1",
                    rejected,
                    "rejected_initial",
                    "state512",
                    "1");

  vector<string> refs;
  gen->collect_init_raw_refs(2, "", refs);
  EXPECT_NE(find(refs.begin(), refs.end(), "state512"), refs.end());
}

class IC3InitRawTest : public ::testing::Test,
                       public ::testing::WithParamInterface<SolverEnum>
{
 protected:
  void SetUp() override
  {
    opts.smt_solver_ = GetParam();
    opts.llm_gen_mode_ = LLM_GEN_ASYNC_CTI;
    s = create_solver_for(opts.smt_solver_, IC3_BOOL, false);
    boolsort = s->make_sort(BOOL);

    fts = make_unique<FunctionalTransitionSystem>(s);
    s1 = fts->make_statevar("s1", boolsort);
    s2 = fts->make_statevar("s2", boolsort);
    fts->constrain_init(s->make_term(Not, s1));
    fts->constrain_init(s->make_term(Not, s2));
    fts->assign_next(s1, s->make_term(Or, s1, s2));
    fts->assign_next(s2, s2);

    SafetyProperty p(s, s->make_term(Not, s1));
    ic3 = make_unique<IC3UnderTest>(p, *fts, s, opts);
    gen = make_shared<LLMGeneralizer>(opts, s);
    ic3->set_llm_generalizer(gen);
    ic3->initialize();
  }

  class IC3UnderTest : public IC3
  {
   public:
    IC3UnderTest(const SafetyProperty & p,
                 const TransitionSystem & ts,
                 const SmtSolver & solver,
                 PonoOptions & opt)
        : IC3(p, ts, solver, opt)
    {
    }

    using IC3Base::build_candidate_hints_json_for_llm;
    using IC3Base::build_init_raw_json_for_llm;
    using IC3Base::get_init_value_at_reset;
    using IC3Base::is_init_safe_block_disjuncts;
  };

  PonoOptions opts;
  SmtSolver s;
  Sort boolsort;
  Term s1, s2;
  unique_ptr<FunctionalTransitionSystem> fts;
  unique_ptr<IC3UnderTest> ic3;
  shared_ptr<LLMGeneralizer> gen;
};

TEST_P(IC3InitRawTest, GetInitValueAtResetReadsModel)
{
  EXPECT_EQ(ic3->get_init_value_at_reset("s1"), "0");
  EXPECT_EQ(ic3->get_init_value_at_reset("s2"), "0");
}

TEST_P(IC3InitRawTest, BuildInitRawJsonForLlmEmbedsValues)
{
  CTIContext ctx;
  ctx.cti_id = "cti_a";
  ctx.frame_idx = 1;
  CTILiteral lit;
  lit.varname = "s1";
  lit.value = "1";
  lit.polarity = true;
  ctx.literals = {lit};
  TermVec empty;
  gen->buffer_cti_context(1, ctx, empty);

  string json = ic3->build_init_raw_json_for_llm(1);
  EXPECT_NE(json.find("\"refs\""), string::npos);
  EXPECT_NE(json.find("\"s1\":\"0\""), string::npos);
}

TEST_P(IC3InitRawTest, CandidateHintsMarksInitSafeNegation)
{
  CTIContext ctx;
  ctx.cti_id = "cti_a";
  ctx.frame_idx = 1;
  CTILiteral lit;
  lit.varname = "s1";
  lit.value = "1";
  lit.polarity = true;
  ctx.literals = {lit};
  TermVec empty;
  gen->buffer_cti_context(1, ctx, empty);

  IC3FrameDisjunct safe;
  safe.ref = "s1";
  safe.op = "eq";
  safe.rhs = "1";
  safe.polarity = false;
  EXPECT_TRUE(ic3->is_init_safe_block_disjuncts({safe}));

  string hints = ic3->build_candidate_hints_json_for_llm(1);
  EXPECT_NE(hints.find("\"init_safe\":true"), string::npos);
  EXPECT_NE(hints.find("s1=1"), string::npos);
}

INSTANTIATE_TEST_SUITE_P(AvailableSolvers,
                         LLMInitRawCollectTest,
                         testing::ValuesIn(available_solver_enums()));

INSTANTIATE_TEST_SUITE_P(AvailableSolvers,
                         IC3InitRawTest,
                         testing::ValuesIn(available_solver_enums()));

}  // namespace pono_tests
