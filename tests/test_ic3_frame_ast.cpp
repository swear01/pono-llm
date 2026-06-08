#include "engines/ic3_frame_ast.h"

#include "gtest/gtest.h"

using namespace pono;
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

}  // namespace pono_tests
