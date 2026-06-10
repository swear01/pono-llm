#include "engines/ic3base.h"

#include "gtest/gtest.h"

using namespace pono;

namespace pono_tests {

TEST(ProofGoalQueueTest, ClearDoesNotUseAfterFree)
{
  ProofGoalQueue q;
  IC3Formula f;
  f.term = nullptr;
  f.disjunction = true;
  q.new_proof_goal(f, 3, nullptr);
  q.new_proof_goal(f, 2, nullptr);
  q.new_proof_goal(f, 1, nullptr);
  ASSERT_FALSE(q.empty());
  q.clear();
  EXPECT_TRUE(q.empty());
  // Repeat clear on empty queue (destructor path).
  q.clear();
}

}  // namespace pono_tests
