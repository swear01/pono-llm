/*********************                                                  */
/*! \file ic3_frame_ast.h
** \brief IC3 Frame v1 AST: structured literals → SMT terms / IC3Formula
**/
#pragma once

#include <cstddef>
#include <string>
#include <vector>

#include "core/ts.h"
#include "smt-switch/smt.h"

namespace pono {

struct IC3FrameDisjunct
{
  std::string ref;
  std::string op;
  std::string rhs;
  bool polarity = true;
};

struct IC3FramePredicateNode
{
  std::string form;
  std::string ref;
  std::string const_val;
  size_t width = 0;
  int extract_hi = -1;
  int extract_lo = -1;
  std::vector<IC3FramePredicateNode> args;
  bool valid = false;
};

struct IC3FrameResponse
{
  std::string source_cti_id;
  size_t sample_id = 0;
  size_t attempt = 0;
  bool has_block = false;
  std::vector<IC3FrameDisjunct> block_disjuncts;
  bool has_refine_predicate = false;
  IC3FramePredicateNode refine_predicate;
  std::vector<std::string> symbols_used;
  std::string rationale;
  bool valid = false;
  std::string error_msg;
};

IC3FrameResponse parse_ic3_frame_response_line(const std::string & line);

void collect_predicate_refs(const IC3FramePredicateNode & node,
                            std::vector<std::string> & refs);

smt::Term build_predicate_term(const smt::SmtSolver & solver,
                               const TransitionSystem & ts,
                               const IC3FramePredicateNode & node);

}  // namespace pono
