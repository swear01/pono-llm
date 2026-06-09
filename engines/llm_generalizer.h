/*********************                                                  */
/*! \file llm_generalizer.h
** \brief IC3 Frame v1 online LLM integration (JSONL sidecar protocol)
**/
#pragma once

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <map>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "engines/ic3_frame_ast.h"
#include "options/options.h"
#include "smt-switch/smt.h"

namespace pono {

struct CTILiteral
{
  size_t id = 0;
  std::string varname;
  std::string expr;
  std::string value;
  bool polarity = true;
  std::string kind;
  std::vector<std::string> signals;
  smt::Term term;
};

/** Compact literal line for digest keys and JSONL (uses CTILiteral::polarity). */
std::string format_cti_literal_line(const CTILiteral & lit);

struct CTIContext
{
  std::string cti_id;
  size_t frame_idx;
  std::vector<CTILiteral> literals;
  std::string property_name;
};

struct SymbolRegistryEntry
{
  std::string kind;
  size_t width = 0;
  size_t btor2_line = 0;
  std::string verilog;
};

struct LLMFeedbackEntry
{
  std::string reason;
  std::string rejected_json;
  std::string witness_ref;
  std::string witness_next_value;
};

struct LLMValidationResult
{
  bool schema_ok = false;
  bool parse_ok = false;
  bool vocab_ok = false;
  bool init_ok = false;
  bool induction_ok = false;
  bool budget_ok = true;
  size_t legal_frame = 0;
  std::string error_msg;
};

struct GeneralizationStats
{
  size_t num_requests = 0;
  size_t num_candidates = 0;
  size_t num_accepted = 0;
  size_t num_schema_fail = 0;
  size_t num_parse_fail = 0;
  size_t num_vocab_fail = 0;
  size_t num_induction_fail = 0;
  size_t num_rejected_initial = 0;
  size_t num_missing_block = 0;
  size_t num_lookup_miss = 0;
  size_t num_attempt_mismatch = 0;
  size_t num_budget_skip = 0;
  size_t num_predicates_added = 0;
  size_t num_batch_timeout = 0;
  size_t num_batch_waits = 0;
  uint64_t total_batch_wait_ms = 0;
  uint64_t max_batch_wait_ms = 0;
  size_t total_tokens = 0;
  size_t accepted_budget = 0;
  double total_llm_time_ms = 0.0;

  void reset()
  {
    num_requests = 0;
    num_candidates = 0;
    num_accepted = 0;
    num_schema_fail = 0;
    num_parse_fail = 0;
    num_vocab_fail = 0;
    num_induction_fail = 0;
    num_rejected_initial = 0;
    num_missing_block = 0;
    num_lookup_miss = 0;
    num_attempt_mismatch = 0;
    num_budget_skip = 0;
    num_predicates_added = 0;
    num_batch_timeout = 0;
    num_batch_waits = 0;
    total_batch_wait_ms = 0;
    max_batch_wait_ms = 0;
    total_tokens = 0;
    accepted_budget = 0;
    total_llm_time_ms = 0.0;
  }
};

class LLMGeneralizer
{
 public:
  LLMGeneralizer(PonoOptions opts, const smt::SmtSolver & solver);

  bool enabled() const;
  bool is_async_cti() const;

  std::string make_cti_id(size_t frame_idx,
                          const std::vector<CTILiteral> & literals) const;

  void set_symbol_registry(
      const std::unordered_map<std::string, SymbolRegistryEntry> & registry);

  void write_benchmark_context(const std::string & benchmark_name,
                               const std::string & bad_expr);

  void buffer_cti_context(size_t frame_idx,
                          const CTIContext & ctx,
                          const smt::TermVec & cube_children);
  void flush_frame_batch(size_t frame_idx,
                         const std::string & frame_snapshot_json);
  void flush_retries(const std::string & frame_snapshot_json);
  void take_retry_queue(std::vector<std::string> & out);
  void write_retry_request(const std::string & cti_id,
                           const std::string & frame_snapshot_json);
  void register_outstanding_samples(const std::string & cti_id, size_t attempt);
  void note_response_processed(const std::string & cti_id, size_t attempt);
  bool all_parallel_samples_received(const std::string & cti_id,
                                     size_t attempt) const;
  bool has_buffered_cti(size_t frame_idx) const;

  void collect_buffered_literal_keys(size_t frame_idx,
                                     std::vector<std::string> & out) const;

  void collect_cti_literal_refs(const std::string & cti_id,
                                std::unordered_set<std::string> & out) const;

  void collect_cti_literal_keys(const std::string & cti_id,
                                std::vector<std::string> & out) const;

  std::string last_flushed_batch_id() const { return last_flushed_batch_id_; }

  bool wait_for_batch_responses(const std::string & batch_id,
                                size_t expected_samples,
                                unsigned timeout_sec);

  std::vector<IC3FrameResponse> poll_responses();

  bool lookup_batch_meta(const std::string & batch_id,
                         size_t & out_frame_idx) const;

  bool lookup_cti_meta(const std::string & cti_id,
                       size_t & out_frame_idx,
                       smt::TermVec & out_cube) const;

  void add_feedback(const std::string & cti_id,
                    const IC3FrameResponse & rejected,
                    const std::string & reason,
                    const std::string & witness_ref = "",
                    const std::string & witness_next = "",
                    size_t clause_idx = SIZE_MAX);

  void finish_attempt(const std::string & cti_id, size_t frame_idx);

  void mark_accepted(const std::string & cti_id);
  bool is_cti_accepted(const std::string & cti_id) const;

  size_t feedback_attempt(const std::string & cti_id) const;

  const GeneralizationStats & stats() const { return stats_; }
  void log_stats() const;

  GeneralizationStats stats_;

  struct BufferedCTI
  {
    CTIContext ctx;
    smt::TermVec cube_children;
  };

  struct StoredCTI
  {
    CTIContext ctx;
    smt::TermVec cube;
  };

  struct BatchMeta
  {
    size_t frame_idx = 0;
    std::vector<StoredCTI> ctis;
  };

 private:
  std::string escape_json(const std::string & s) const;
  std::string literal_ref(const CTILiteral & lit) const;
  void serialize_frame_request(std::ostream & out,
                               const CTIContext & ctx,
                               size_t attempt,
                               const std::vector<LLMFeedbackEntry> & feedback,
                               const std::string & frame_snapshot_json);

  void write_request_for_cti(const CTIContext & ctx,
                             const std::string & frame_snapshot_json);

  void append_cti_cube_json(std::ostream & out, const CTIContext & ctx) const;

  std::string format_literal_line(const CTILiteral & lit) const;
  void build_cti_digest(const std::vector<BufferedCTI> & buffered,
                        std::vector<size_t> & out_indices,
                        std::string & out_digest_json,
                        size_t max_cubes_override = 0) const;

  void serialize_batch_request(std::ostream & out,
                               const std::string & batch_id,
                               size_t frame_idx,
                               size_t attempt,
                               const std::vector<BufferedCTI> & buffered,
                               const std::vector<size_t> & export_indices,
                               const std::string & digest_json,
                               const std::vector<LLMFeedbackEntry> & feedback,
                               const std::string & frame_snapshot_json);

  void write_batch_request(size_t frame_idx,
                           const std::string & frame_snapshot_json,
                           const std::vector<BufferedCTI> & buffered,
                           size_t attempt = 0);

  PonoOptions opts_;
  smt::SmtSolver solver_;

  std::string request_path_;
  std::string response_path_;
  std::string log_path_;
  std::string benchmark_context_path_;
  std::streampos last_response_pos_ = 0;

  bool benchmark_context_written_ = false;
  std::string benchmark_name_;
  std::string bad_expr_;

  std::unordered_map<std::string, SymbolRegistryEntry> symbol_registry_;

  std::map<size_t, std::vector<BufferedCTI>> frame_cti_buffer_;
  std::unordered_map<std::string, StoredCTI> cti_store_;

  std::unordered_map<std::string, std::vector<LLMFeedbackEntry>> feedback_by_cti_;
  std::unordered_map<std::string, size_t> attempt_by_cti_;

  std::unordered_set<std::string> sent_request_ids_;
  std::unordered_set<std::string> accepted_cti_ids_;
  std::vector<std::string> retry_queue_;
  std::unordered_map<std::string, size_t> outstanding_samples_;

  std::unordered_map<std::string, BatchMeta> batch_store_;
  std::string last_flushed_batch_id_;
};

}  // namespace pono
