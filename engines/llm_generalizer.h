/*********************                                                  */
/*! \file llm_generalizer.h
** \verbatim
** \brief LLM-guided lemma generalization for IC3/IC3-IA
**
** Provides JSONL-based communication with a Python sidecar that calls
** an LLM (e.g. DeepSeek V4 Pro) to propose generalized lemmas from CTI
** contexts. All candidate lemmas must pass SMT-based validation before
** being inserted into frames.
** \endverbatim
**/
#pragma once

#include <cstddef>
#include <fstream>
#include <string>
#include <vector>

#include "options/options.h"
#include "smt-switch/smt.h"

namespace pono {

struct CTILiteral
{
  std::string varname;
  std::string value;
  smt::Term term;
};

struct CTIContext
{
  size_t frame_idx;
  std::vector<CTILiteral> literals;
  std::string property_name;
  std::vector<CTILiteral> frame_lemmas;  // optional: nearby frame lemmas
};

struct LLMCandidate
{
  enum Type
  {
    CUBE_SUBSET = 0,
    QF_SMT,
    PREDICATE_RELATION
  };

  Type type;
  size_t frame_hint;
  std::vector<std::string> keep_literals;
  std::vector<std::string> drop_literals;
  std::string formula;
  std::vector<std::string> used_symbols;
  std::string rationale;

  // parsed SMT term (if applicable)
  smt::Term parsed_term;
};

struct LLMValidationResult
{
  bool schema_ok;
  bool parse_ok;
  bool vocab_ok;
  bool init_ok;
  bool induction_ok;
  bool subsumption_ok;
  bool budget_ok;
  size_t legal_frame;
  std::string error_msg;
};

struct GeneralizationStats
{
  size_t num_requests;
  size_t num_candidates;
  size_t num_accepted;
  size_t num_schema_fail;
  size_t num_parse_fail;
  size_t num_vocab_fail;
  size_t num_induction_fail;
  size_t num_subsumption_fail;
  size_t num_budget_skip;
  size_t total_tokens;
  size_t accepted_budget;
  double total_llm_time_ms;

  void reset()
  {
    num_requests = 0;
    num_candidates = 0;
    num_accepted = 0;
    num_schema_fail = 0;
    num_parse_fail = 0;
    num_vocab_fail = 0;
    num_induction_fail = 0;
    num_subsumption_fail = 0;
    num_budget_skip = 0;
    total_tokens = 0;
    accepted_budget = 0;
    total_llm_time_ms = 0.0;
  }
};

class LLMGeneralizer
{
 public:
  LLMGeneralizer(PonoOptions opts, const smt::SmtSolver & solver);

  void write_cti_context(const CTIContext & ctx);

  std::vector<LLMCandidate> poll_candidates();

  bool enabled() const;
  bool is_async_cti() const;
  bool is_seed_only() const;

  const GeneralizationStats & stats() const { return stats_; }
  void log_stats() const;

  // Store the last CTI cube for candidate pairing (cube-subset mode)
  void store_last_cti_cube(const smt::TermVec & cube_children);
  const smt::TermVec & last_cti_cube() const { return last_cti_cube_; }

  GeneralizationStats stats_;

 private:
  void write_json(const CTIContext & ctx);
  std::string escape_json(const std::string & s) const;

  PonoOptions opts_;
  smt::SmtSolver solver_;

  std::string request_path_;
  std::string response_path_;
  std::string log_path_;
  std::streampos last_response_pos_;

  // Stored CTI cube children for candidate pairing
  smt::TermVec last_cti_cube_;
};

}  // namespace pono
