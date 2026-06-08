#include "engines/llm_generalizer.h"

#include "gtest/gtest.h"

using namespace pono;

namespace pono_tests {

TEST(LLMLiteralFormatTest, PolarityFalseWithRhsOne)
{
  CTILiteral lit;
  lit.varname = "state5";
  lit.value = "1";
  lit.polarity = false;
  EXPECT_EQ(format_cti_literal_line(lit), "!state5=1");
}

TEST(LLMLiteralFormatTest, PolarityTrueWithRhsOne)
{
  CTILiteral lit;
  lit.varname = "state5";
  lit.value = "1";
  lit.polarity = true;
  EXPECT_EQ(format_cti_literal_line(lit), "state5=1");
}

TEST(LLMLiteralFormatTest, NormalizesBoolRhs)
{
  CTILiteral lit;
  lit.varname = "state3";
  lit.value = "false";
  lit.polarity = true;
  EXPECT_EQ(format_cti_literal_line(lit), "state3=0");
}

}  // namespace pono_tests
