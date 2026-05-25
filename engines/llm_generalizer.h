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
#include <deque>
#include <fstream>
#include <map>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "options/options.h"
#include "smt-switch/smt.h"

namespace pono {

struct CTILiteral
{
  size_t id = 0;
  std::string varname;
  std::string expr;
  std::string value;
  std::string kind;
  std::vector<std::string> signals;
  smt::Term term;
};

struct CTIContext
{
  std::string cti_id;
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

struct LLMIdCandidate
{
  std::string cti_id;
  std::vector<size_t> keep_ids;
  std::vector<size_t> drop_ids;
  std::vector<size_t> add_back_ids;
  std::string mode;
  std::string confidence;
  std::string short_reason;
};

struct LLMWitnessDiff
{
  size_t literal_id;
  std::string cti_literal;
  std::string witness_value;
  std::string effect;
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
  bool is_offline_dump() const;
  bool is_offline_check() const;

  std::string replay_dir() const { return replay_dir_; }
  std::string make_cti_id(size_t frame_idx,
                          const std::vector<CTILiteral> & literals) const;

  void write_static_context(const std::string & benchmark_name,
                            const std::string & bad_expr,
                            const std::vector<CTILiteral> & states,
                            const std::vector<CTILiteral> & inputs,
                            const std::vector<std::string> & state_updates);
  void write_offline_cti_context(const CTIContext & ctx);

  void load_offline_records();
  bool get_proposal(const std::string & cti_id, LLMIdCandidate & out) const;
  bool get_repair(const std::string & cti_id, LLMIdCandidate & out) const;

  void write_replay_result(const std::string & cti_id,
                           const std::string & status,
                           size_t frame_idx,
                           size_t original_size,
                           size_t candidate_size,
                           const std::string & reason);
  void write_repair_request(const CTIContext & ctx,
                            const LLMIdCandidate & failed,
                            const std::vector<LLMWitnessDiff> & diffs);

  const GeneralizationStats & stats() const { return stats_; }
  void log_stats() const;

  // Store the last CTI cube for candidate pairing (cube-subset mode)
  void store_last_cti_cube(const smt::TermVec & cube_children);
  const smt::TermVec & last_cti_cube() const { return last_cti_cube_; }

  // Retrieve next matched CTI cube for candidate pairing (FIFO)
  smt::TermVec pop_next_cti_cube();

  // Multi-CTI batching: buffer CTIs per frame, flush as one LLM request
  void buffer_cti_context(size_t frame_idx, const CTIContext & ctx);
  void flush_frame_batch(size_t frame_idx);
  bool has_buffered_cti(size_t frame_idx) const;

  GeneralizationStats stats_;

 private:
  void write_json(const CTIContext & ctx);
  std::string escape_json(const std::string & s) const;

  PonoOptions opts_;
  smt::SmtSolver solver_;

  std::string request_path_;
  std::string response_path_;
  std::string log_path_;
  std::string replay_dir_;
  std::streampos last_response_pos_;
  bool offline_records_loaded_;

  // Stored CTI cube children for candidate pairing
  smt::TermVec last_cti_cube_;

  // Multi-CTI batching: buffer CTIs per frame before sending to LLM
  struct BufferedCTI {
    CTIContext ctx;
    smt::TermVec cube_children;
  };
  std::map<size_t, std::vector<BufferedCTI>> frame_cti_buffer_;

  // Recent CTI cubes for matching late-arriving LLM candidates
  std::deque<smt::TermVec> stored_cti_cubes_;
  static const size_t kMaxStoredCubes = 20;

  // Dedup set to avoid sending duplicate CTI contexts
  std::unordered_set<std::string> sent_ctx_hashes_;

  std::unordered_map<std::string, LLMIdCandidate> proposals_;
  std::unordered_map<std::string, LLMIdCandidate> repairs_;
};

}  // namespace pono
