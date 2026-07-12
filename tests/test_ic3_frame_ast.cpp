#include "core/fts.h"
#include "engines/ic3_frame_ast.h"
#include "gtest/gtest.h"
#include "smt/available_solvers.h"

using namespace pono;
using namespace smt;
using namespace std;

namespace pono_tests {

static string sample_response_line(size_t sample_id, size_t attempt = 1)
{
  return R"({"type":"ic3_frame_response","source_cti_id":"batch_f2_a1","sample_id":)"
         + to_string(sample_id)
         + R"(,"attempt":)" + to_string(attempt)
         + R"(,"block_disjuncts":[{"ref":"state1","op":"eq","rhs":"0","polarity":false}],"rationale":"ok"})";
}

TEST(IC3FrameAstTest, NumericSampleId)
{
  auto res = parse_ic3_frame_response_line(sample_response_line(2));
  ASSERT_TRUE(res.valid) << res.error_msg;
  EXPECT_EQ(res.sample_id, 2u);
  EXPECT_EQ(res.source_cti_id, "batch_f2_a1");
}

TEST(IC3FrameAstTest, NumericAttempt)
{
  auto res = parse_ic3_frame_response_line(sample_response_line(1, 2));
  ASSERT_TRUE(res.valid) << res.error_msg;
  EXPECT_EQ(res.attempt, 2u);
}

TEST(IC3FrameAstTest, DistinctSamples)
{
  unordered_set<size_t> seen;
  for (size_t sid : {0, 1, 2}) {
    auto res = parse_ic3_frame_response_line(sample_response_line(sid));
    ASSERT_TRUE(res.valid) << res.error_msg;
    seen.insert(res.sample_id);
  }
  EXPECT_EQ(seen.size(), 3u);
}

TEST(IC3FrameAstTest, InvalidType)
{
  string line =
      R"({"type":"other","source_cti_id":"x","sample_id":0,"block_disjuncts":[{"ref":"state1","op":"eq","rhs":"0","polarity":false}]})";
  auto res = parse_ic3_frame_response_line(line);
  EXPECT_FALSE(res.valid);
}

TEST(IC3FrameAstTest, SampleIdNotStringField)
{
  // Regression: parse_string_field would read "attempt" after numeric sample_id.
  string line =
      R"({"type":"ic3_frame_response","source_cti_id":"batch_f1_a1","sample_id":3,"attempt":1,"block_disjuncts":[{"ref":"state5","op":"eq","rhs":"1","polarity":false}],"rationale":"x"})";
  auto res = parse_ic3_frame_response_line(line);
  ASSERT_TRUE(res.valid) << res.error_msg;
  EXPECT_EQ(res.sample_id, 3u);
  EXPECT_EQ(res.attempt, 1u);
}

TEST(IC3FrameAstTest, BlockClausesMulti)
{
  string line =
      R"({"type":"ic3_frame_response","source_cti_id":"batch_f2_a1","sample_id":0,"block_clauses":[[{"ref":"state5","op":"eq","rhs":"0","polarity":true}],[{"ref":"state93","op":"eq","rhs":"1","polarity":false}]],"rationale":"alt"})";
  auto res = parse_ic3_frame_response_line(line);
  ASSERT_TRUE(res.valid) << res.error_msg;
  ASSERT_EQ(res.block_clauses.size(), 2u);
  EXPECT_EQ(res.block_clauses[0].size(), 1u);
  EXPECT_EQ(res.block_clauses[1][0].ref, "state93");
  EXPECT_EQ(res.block_disjuncts.size(), 1u);
  EXPECT_EQ(res.block_disjuncts[0].ref, "state5");
}

TEST(IC3FrameAstTest, LegacyBlockDisjunctsMapsToClauses)
{
  string line =
      R"({"type":"ic3_frame_response","source_cti_id":"batch_f1_a1","sample_id":0,"block_disjuncts":[{"ref":"state1","op":"eq","rhs":"0","polarity":false}],"rationale":"legacy"})";
  auto res = parse_ic3_frame_response_line(line);
  ASSERT_TRUE(res.valid) << res.error_msg;
  ASSERT_EQ(res.block_clauses.size(), 1u);
  EXPECT_EQ(res.block_clauses[0][0].ref, "state1");
}

TEST(IC3FrameAstTest, PredicateAstKeyOrderIsIrrelevant)
{
  string line =
      R"({"predicate_ast":{"args":[{"form":"ref","ref":"state1"},{"args":[{"const":"0","form":"const","width":8},{"form":"ref","ref":"state2"}],"form":"add"}],"form":"ule"}})";
  IC3FramePredicateNode node;
  ASSERT_TRUE(extract_predicate_ast_field(line, node));
  ASSERT_TRUE(node.valid);
  EXPECT_EQ(node.form, "ule");
  ASSERT_EQ(node.args.size(), 2u);
  EXPECT_EQ(node.args[0].form, "ref");
  EXPECT_EQ(node.args[1].form, "add");
}

TEST(IC3FrameAstTest, BuildsNaryArithmetic)
{
  SmtSolver solver = create_solver(BZLA);
  FunctionalTransitionSystem fts(solver);
  Sort bv8 = solver->make_sort(BV, 8);
  Term state = fts.make_statevar("state1", bv8);
  IC3FramePredicateNode node = parse_predicate_ast_from_json(
      R"({"args":[{"args":[{"form":"ref","ref":"state1"},{"form":"const","const":"1","width":8},{"form":"const","const":"2","width":8}],"form":"add"},{"form":"const","const":"3","width":8}],"form":"eq"})");
  ASSERT_TRUE(node.valid);
  Term predicate = build_predicate_term(solver, fts, node);
  ASSERT_TRUE(predicate);
  solver->assert_formula(
      solver->make_term(Equal, state, solver->make_term(0, bv8)));
  solver->assert_formula(solver->make_term(Not, predicate));
  EXPECT_TRUE(solver->check_sat().is_unsat());
}

TEST(IC3FrameAstTest, BuildsUnarySubAsNegation)
{
  SmtSolver solver = create_solver(BZLA);
  FunctionalTransitionSystem fts(solver);
  Sort bv8 = solver->make_sort(BV, 8);
  Term state = fts.make_statevar("state1", bv8);
  IC3FramePredicateNode node = parse_predicate_ast_from_json(
      R"({"form":"eq","args":[{"form":"sub","args":[{"form":"ref","ref":"state1"}]},{"form":"const","const":"255","width":8}]})");
  ASSERT_TRUE(node.valid);
  Term predicate = build_predicate_term(solver, fts, node);
  ASSERT_TRUE(predicate);
  solver->assert_formula(
      solver->make_term(Equal, state, solver->make_term(1, bv8)));
  solver->assert_formula(solver->make_term(Not, predicate));
  EXPECT_TRUE(solver->check_sat().is_unsat());
}

}  // namespace pono_tests
