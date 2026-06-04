/*********************                                                  */
/*! \file llm_generalizer.cpp
** \brief IC3 Frame v1 online LLM JSONL protocol
**/

#include "engines/llm_generalizer.h"

#include <cassert>
#include <chrono>
#include <fstream>
#include <functional>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <thread>
#include <unordered_set>

#include "utils/logger.h"

using namespace smt;
using namespace std;

namespace pono {

namespace {

static void ensure_dir_for_file(const string & path)
{
  size_t pos = path.find_last_of('/');
  if (pos == string::npos) return;
  string dir = path.substr(0, pos);
  string cur;
  for (char c : dir) {
    cur.push_back(c);
    if (c == '/') mkdir(cur.c_str(), 0775);
  }
}

/** Stable feedback key for batch IDs (batch_f2_a1 -> batch_f2). */
static string batch_feedback_key(const string & batch_id)
{
  if (batch_id.rfind("batch_", 0) != 0) return batch_id;
  size_t pos = batch_id.rfind("_a");
  if (pos != string::npos && pos > 6) return batch_id.substr(0, pos);
  return batch_id;
}

static string extract_state_ref(const string & name)
{
  size_t pos = name.find("state");
  if (pos == string::npos) return name;
  size_t end = pos + 5;
  while (end < name.size() && isdigit(static_cast<unsigned char>(name[end]))) {
    ++end;
  }
  if (end > pos + 5) return name.substr(pos, end - pos);
  return name;
}

}  // namespace

LLMGeneralizer::LLMGeneralizer(PonoOptions opts, const SmtSolver & solver)
    : opts_(opts), solver_(solver)
{
  request_path_ = opts_.llm_request_path_.empty()
                      ? "/tmp/pono_llm_requests.jsonl"
                      : opts_.llm_request_path_;
  response_path_ = opts_.llm_response_path_.empty()
                       ? "/tmp/pono_llm_responses.jsonl"
                       : opts_.llm_response_path_;
  log_path_ = opts_.llm_log_path_.empty() ? "/tmp/pono_llm_log.jsonl"
                                          : opts_.llm_log_path_;
  size_t slash = request_path_.find_last_of('/');
  benchmark_context_path_ =
      (slash == string::npos ? "/tmp" : request_path_.substr(0, slash))
      + "/pono_benchmark_context.json";
  stats_.reset();
}

bool LLMGeneralizer::enabled() const
{
  return opts_.llm_gen_mode_ != LLM_GEN_NONE;
}

bool LLMGeneralizer::is_async_cti() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_ASYNC_CTI;
}

string LLMGeneralizer::make_cti_id(size_t frame_idx,
                                   const vector<CTILiteral> & literals) const
{
  ostringstream oss;
  oss << "cti_f" << frame_idx << "_";
  for (size_t i = 0; i < literals.size() && i < 8; ++i) {
    oss << literal_ref(literals[i]) << "=" << literals[i].value << ";";
  }
  return oss.str();
}

void LLMGeneralizer::set_symbol_registry(
    const unordered_map<string, SymbolRegistryEntry> & registry)
{
  symbol_registry_ = registry;
}

void LLMGeneralizer::write_benchmark_context(const string & benchmark_name,
                                            const string & bad_expr)
{
  if (benchmark_context_written_) return;
  benchmark_name_ = benchmark_name;
  bad_expr_ = bad_expr;
  ensure_dir_for_file(benchmark_context_path_);
  ofstream fout(benchmark_context_path_);
  if (!fout.is_open()) return;
  fout << "{";
  fout << "\"schema_version\":1,";
  fout << "\"type\":\"benchmark_context\",";
  fout << "\"benchmark\":\"" << escape_json(benchmark_name) << "\",";
  fout << "\"bad_property\":\"" << escape_json(bad_expr) << "\",";
  fout << "\"symbol_registry\":{";
  bool first = true;
  for (const auto & kv : symbol_registry_) {
    if (!first) fout << ",";
    first = false;
    fout << "\"" << escape_json(kv.first) << "\":{";
    fout << "\"kind\":\"" << escape_json(kv.second.kind) << "\",";
    fout << "\"width\":" << kv.second.width << ",";
    fout << "\"btor2_line\":" << kv.second.btor2_line << ",";
    if (kv.second.verilog.empty()) {
      fout << "\"verilog\":null";
    } else {
      fout << "\"verilog\":\"" << escape_json(kv.second.verilog) << "\"";
    }
    fout << "}";
  }
  fout << "}}";
  fout.close();
  benchmark_context_written_ = true;
}

string LLMGeneralizer::literal_ref(const CTILiteral & lit) const
{
  return extract_state_ref(lit.varname);
}

string LLMGeneralizer::escape_json(const string & s) const
{
  ostringstream oss;
  for (char c : s) {
    switch (c) {
      case '"': oss << "\\\""; break;
      case '\\': oss << "\\\\"; break;
      case '\n': oss << "\\n"; break;
      case '\r': oss << "\\r"; break;
      case '\t': oss << "\\t"; break;
      default: oss << c;
    }
  }
  return oss.str();
}

void LLMGeneralizer::buffer_cti_context(size_t frame_idx,
                                        const CTIContext & ctx,
                                        const TermVec & cube_children)
{
  BufferedCTI b;
  b.ctx = ctx;
  b.cube_children = cube_children;
  frame_cti_buffer_[frame_idx].push_back(b);

  StoredCTI stored;
  stored.ctx = ctx;
  stored.cube = cube_children;
  cti_store_[ctx.cti_id] = stored;
}

bool LLMGeneralizer::has_buffered_cti(size_t frame_idx) const
{
  auto it = frame_cti_buffer_.find(frame_idx);
  return it != frame_cti_buffer_.end() && !it->second.empty();
}

size_t LLMGeneralizer::feedback_attempt(const string & cti_id) const
{
  auto it = attempt_by_cti_.find(cti_id);
  if (it == attempt_by_cti_.end()) return 1;
  return it->second;
}

namespace {

static string sample_group_key(const string & cti_id, size_t attempt)
{
  return cti_id + "#" + std::to_string(attempt);
}

static string serialize_response_for_feedback(
    const IC3FrameResponse & rejected,
    const function<string(const string &)> & escape)
{
  ostringstream out;
  out << "{";
  out << "\"source_cti_id\":\"" << escape(rejected.source_cti_id) << "\",";
  out << "\"sample_id\":" << rejected.sample_id << ",";
  out << "\"attempt\":" << rejected.attempt << ",";
  out << "\"has_block\":" << (rejected.has_block ? "true" : "false") << ",";
  out << "\"has_refine_predicate\":"
      << (rejected.has_refine_predicate ? "true" : "false") << ",";
  out << "\"rationale\":\"" << escape(rejected.rationale) << "\"";
  out << "}";
  return out.str();
}

}  // namespace

void LLMGeneralizer::register_outstanding_samples(const string & cti_id,
                                                  size_t attempt)
{
  outstanding_samples_[sample_group_key(cti_id, attempt)] =
      opts_.llm_parallel_samples_;
}

void LLMGeneralizer::note_response_processed(const string & cti_id,
                                             size_t attempt)
{
  auto it = outstanding_samples_.find(sample_group_key(cti_id, attempt));
  if (it != outstanding_samples_.end() && it->second > 0) {
    it->second--;
  }
}

bool LLMGeneralizer::all_parallel_samples_received(const string & cti_id,
                                                   size_t attempt) const
{
  auto it = outstanding_samples_.find(sample_group_key(cti_id, attempt));
  if (it == outstanding_samples_.end()) return true;
  return it->second == 0;
}

void LLMGeneralizer::add_feedback(const string & cti_id,
                                  const IC3FrameResponse & rejected,
                                  const string & reason,
                                  const string & witness_ref,
                                  const string & witness_next)
{
  LLMFeedbackEntry fb;
  fb.reason = reason;
  fb.rejected_json =
      serialize_response_for_feedback(rejected,
                                      [this](const string & s) {
                                        return escape_json(s);
                                      });
  fb.witness_ref = witness_ref;
  fb.witness_next_value = witness_next;
  feedback_by_cti_[batch_feedback_key(cti_id)].push_back(fb);
}

void LLMGeneralizer::finish_attempt(const string & cti_id, size_t frame_idx)
{
  if (is_cti_accepted(cti_id)) return;
  size_t attempt = feedback_attempt(cti_id);
  if (attempt >= opts_.llm_max_attempts_) return;
  attempt_by_cti_[cti_id] = attempt + 1;
  retry_queue_.push_back(cti_id);
  (void)frame_idx;
}

void LLMGeneralizer::mark_accepted(const string & cti_id)
{
  accepted_cti_ids_.insert(cti_id);
  outstanding_samples_[sample_group_key(cti_id, feedback_attempt(cti_id))] = 0;
  if (cti_id.rfind("batch_", 0) == 0) {
    batch_store_.erase(cti_id);
  }
}

bool LLMGeneralizer::is_cti_accepted(const string & cti_id) const
{
  return accepted_cti_ids_.count(cti_id) > 0;
}

void LLMGeneralizer::append_cti_cube_json(ostream & out, const CTIContext & ctx) const
{
  out << "\"cti\":{\"cube\":{\"literals\":[";
  for (size_t i = 0; i < ctx.literals.size(); ++i) {
    if (i > 0) out << ",";
    const auto & lit = ctx.literals[i];
    string ref = literal_ref(lit);
    string rhs = lit.value;
    if (rhs == "true") rhs = "1";
    if (rhs == "false") rhs = "0";
    bool pol = (lit.value == "true" || lit.value == "1");
    out << "{\"atom\":{";
    out << "\"ref\":\"" << escape_json(ref) << "\",";
    out << "\"rhs\":\"" << escape_json(rhs) << "\"},";
    out << "\"polarity\":" << (pol ? "true" : "false") << "}";
  }
  out << "]}}";
}

void LLMGeneralizer::serialize_frame_request(
    ostream & out,
    const CTIContext & ctx,
    size_t attempt,
    const vector<LLMFeedbackEntry> & feedback,
    const string & frame_snapshot_json)
{
  out << "{";
  out << "\"schema_version\":1,";
  out << "\"type\":\"ic3_frame_request\",";
  out << "\"frame_idx\":" << ctx.frame_idx << ",";
  out << "\"cti_id\":\"" << escape_json(ctx.cti_id) << "\",";
  out << "\"attempt\":" << attempt << ",";
  out << "\"max_attempts\":" << opts_.llm_max_attempts_ << ",";
  out << "\"parallel_group\":\"" << escape_json(ctx.cti_id + "_a" + std::to_string(attempt))
      << "\",";
  out << "\"parallel_samples\":" << opts_.llm_parallel_samples_ << ",";
  out << "\"reasoning_effort\":\"" << escape_json(opts_.llm_reasoning_effort_) << "\",";
  out << "\"model\":\""
      << escape_json(opts_.llm_model_.empty() ? "deepseek-v4-pro" : opts_.llm_model_)
      << "\",";
  out << "\"benchmark_context_path\":\"" << escape_json(benchmark_context_path_)
      << "\",";

  append_cti_cube_json(out, ctx);
  out << ",";

  if (!frame_snapshot_json.empty()) {
    out << "\"frame_snapshot\":" << frame_snapshot_json << ",";
  } else {
    out << "\"frame_snapshot\":{\"frame_idx\":" << ctx.frame_idx
        << ",\"clauses\":[]},";
  }

  out << "\"feedback\":[";
  for (size_t i = 0; i < feedback.size(); ++i) {
    if (i > 0) out << ",";
    out << "{\"reason\":\"" << escape_json(feedback[i].reason) << "\",";
    out << "\"rejected_json\":\"" << escape_json(feedback[i].rejected_json)
        << "\",";
    out << "\"witness\":{";
    out << "\"ref\":\"" << escape_json(feedback[i].witness_ref) << "\",";
    out << "\"next_value\":\"" << escape_json(feedback[i].witness_next_value)
        << "\"}}";
  }
  out << "]}";
}

void LLMGeneralizer::write_request_for_cti(const CTIContext & ctx,
                                           const string & frame_snapshot_json)
{
  size_t attempt = feedback_attempt(ctx.cti_id);
  if (attempt > opts_.llm_max_attempts_) return;

  string req_id = ctx.cti_id + "#" + std::to_string(attempt);
  if (sent_request_ids_.count(req_id)) return;
  sent_request_ids_.insert(req_id);

  if (!attempt_by_cti_.count(ctx.cti_id)) {
    attempt_by_cti_[ctx.cti_id] = 1;
  }

  ensure_dir_for_file(request_path_);
  ofstream fout(request_path_, ios::app);
  if (!fout.is_open()) {
    logger.log(0, "LLMGeneralizer: cannot open request file {}", request_path_);
    return;
  }

  vector<LLMFeedbackEntry> fb;
  auto fb_it = feedback_by_cti_.find(ctx.cti_id);
  if (fb_it != feedback_by_cti_.end()) fb = fb_it->second;

  serialize_frame_request(fout, ctx, attempt, fb, frame_snapshot_json);
  fout << "\n";
  register_outstanding_samples(ctx.cti_id, attempt);
  stats_.num_requests++;
}

void LLMGeneralizer::serialize_batch_request(
    ostream & out,
    const string & batch_id,
    size_t frame_idx,
    size_t attempt,
    const vector<BufferedCTI> & buffered,
    const vector<LLMFeedbackEntry> & feedback,
    const string & frame_snapshot_json)
{
  out << "{";
  out << "\"schema_version\":1,";
  out << "\"type\":\"ic3_frame_batch_request\",";
  out << "\"batch_id\":\"" << escape_json(batch_id) << "\",";
  out << "\"frame_idx\":" << frame_idx << ",";
  out << "\"attempt\":" << attempt << ",";
  out << "\"max_attempts\":" << opts_.llm_max_attempts_ << ",";
  out << "\"parallel_group\":\"" << escape_json(batch_id) << "\",";
  out << "\"parallel_samples\":" << opts_.llm_parallel_samples_ << ",";
  out << "\"temperature\":0.5,";
  out << "\"reasoning_effort\":\"" << escape_json(opts_.llm_reasoning_effort_) << "\",";
  out << "\"model\":\""
      << escape_json(opts_.llm_model_.empty() ? "deepseek-v4-pro" : opts_.llm_model_)
      << "\",";
  out << "\"benchmark_context_path\":\"" << escape_json(benchmark_context_path_)
      << "\",";

  out << "\"cti_entries\":[";
  for (size_t i = 0; i < buffered.size(); ++i) {
    if (i > 0) out << ",";
    out << "{\"cti_id\":\"" << escape_json(buffered[i].ctx.cti_id) << "\",";
    append_cti_cube_json(out, buffered[i].ctx);
    out << "}";
  }
  out << "],";

  if (!frame_snapshot_json.empty()) {
    out << "\"frame_snapshot\":" << frame_snapshot_json << ",";
  } else {
    out << "\"frame_snapshot\":{\"frame_idx\":" << frame_idx
        << ",\"clauses\":[]},";
  }

  out << "\"feedback\":[";
  for (size_t i = 0; i < feedback.size(); ++i) {
    if (i > 0) out << ",";
    out << "{\"reason\":\"" << escape_json(feedback[i].reason) << "\",";
    out << "\"rejected_json\":\"" << escape_json(feedback[i].rejected_json)
        << "\",";
    out << "\"witness\":{";
    out << "\"ref\":\"" << escape_json(feedback[i].witness_ref) << "\",";
    out << "\"next_value\":\"" << escape_json(feedback[i].witness_next_value)
        << "\"}}";
  }
  out << "]}";
}

void LLMGeneralizer::write_batch_request(size_t frame_idx,
                                        const string & frame_snapshot_json,
                                        const vector<BufferedCTI> & buffered,
                                        size_t attempt_arg)
{
  if (buffered.empty()) return;

  size_t attempt = attempt_arg > 0 ? attempt_arg : 1;
  string batch_id = "batch_f" + std::to_string(frame_idx) + "_a"
                    + std::to_string(attempt);

  if (!attempt_by_cti_.count(batch_id)) {
    attempt_by_cti_[batch_id] = attempt;
  }

  if (attempt > opts_.llm_max_attempts_) return;

  string req_id = batch_id + "#" + std::to_string(attempt);
  if (sent_request_ids_.count(req_id)) return;
  sent_request_ids_.insert(req_id);

  BatchMeta meta;
  meta.frame_idx = frame_idx;
  for (const auto & b : buffered) {
    StoredCTI stored;
    stored.ctx = b.ctx;
    stored.cube = b.cube_children;
    meta.ctis.push_back(stored);
  }
  batch_store_[batch_id] = meta;

  ensure_dir_for_file(request_path_);
  ofstream fout(request_path_, ios::app);
  if (!fout.is_open()) {
    logger.log(0, "LLMGeneralizer: cannot open request file {}", request_path_);
    return;
  }

  vector<LLMFeedbackEntry> fb;
  auto fb_it = feedback_by_cti_.find(batch_feedback_key(batch_id));
  if (fb_it != feedback_by_cti_.end()) fb = fb_it->second;

  serialize_batch_request(fout, batch_id, frame_idx, attempt, buffered, fb,
                          frame_snapshot_json);
  fout << "\n";
  register_outstanding_samples(batch_id, attempt);
  stats_.num_requests++;
  last_flushed_batch_id_ = batch_id;
  logger.log(1,
             "LLMGeneralizer: batch request {} ({} CTIs, frame {})",
             batch_id,
             buffered.size(),
             frame_idx);
}

void LLMGeneralizer::flush_frame_batch(size_t frame_idx,
                                       const string & frame_snapshot_json)
{
  auto it = frame_cti_buffer_.find(frame_idx);
  if (it == frame_cti_buffer_.end() || it->second.empty()) {
    last_flushed_batch_id_.clear();
    return;
  }

  if (opts_.llm_batch_cti_) {
    write_batch_request(frame_idx, frame_snapshot_json, it->second);
  } else {
    for (const auto & buffered : it->second) {
      write_request_for_cti(buffered.ctx, frame_snapshot_json);
    }
    logger.log(1, "LLMGeneralizer: flushed frame {} CTI requests", frame_idx);
  }

  frame_cti_buffer_.erase(it);
}

bool LLMGeneralizer::wait_for_batch_responses(const string & batch_id,
                                              size_t expected_samples,
                                              unsigned timeout_sec)
{
  using clock = chrono::steady_clock;
  auto deadline = clock::now() + chrono::seconds(timeout_sec);
  const streampos wait_pos = last_response_pos_;

  while (clock::now() < deadline) {
    unordered_set<size_t> samples;
    ifstream fin(response_path_);
    if (fin) {
      fin.seekg(wait_pos);
      string line;
      while (getline(fin, line)) {
        if (line.empty() || line[0] != '{') continue;
        IC3FrameResponse resp = parse_ic3_frame_response_line(line);
        if (!resp.valid) continue;
        if (resp.source_cti_id == batch_id) {
          samples.insert(resp.sample_id);
        }
      }
    }
    if (samples.size() >= expected_samples) {
      logger.log(1,
                 "LLMGeneralizer: batch {} received {}/{} samples",
                 batch_id,
                 samples.size(),
                 expected_samples);
      return true;
    }
    this_thread::sleep_for(chrono::milliseconds(200));
  }

  stats_.num_batch_timeout++;
  logger.log(0,
               "LLMGeneralizer: batch {} wait timeout ({}s)",
               batch_id,
               timeout_sec);
  return false;
}

bool LLMGeneralizer::lookup_batch_meta(const string & batch_id,
                                       size_t & out_frame_idx) const
{
  auto it = batch_store_.find(batch_id);
  if (it == batch_store_.end()) return false;
  out_frame_idx = it->second.frame_idx;
  return true;
}

void LLMGeneralizer::take_retry_queue(vector<string> & out)
{
  out.clear();
  out.swap(retry_queue_);
}

void LLMGeneralizer::write_retry_request(const string & cti_id,
                                         const string & frame_snapshot_json)
{
  if (is_cti_accepted(cti_id)) return;

  if (cti_id.rfind("batch_", 0) == 0) {
    auto it = batch_store_.find(cti_id);
    if (it == batch_store_.end()) return;
    vector<BufferedCTI> buffered;
    for (const auto & stored : it->second.ctis) {
      BufferedCTI b;
      b.ctx = stored.ctx;
      b.cube_children = stored.cube;
      buffered.push_back(b);
    }
    size_t attempt = feedback_attempt(cti_id);
    write_batch_request(
        it->second.frame_idx, frame_snapshot_json, buffered, attempt);
    return;
  }

  auto store_it = cti_store_.find(cti_id);
  if (store_it == cti_store_.end()) return;
  write_request_for_cti(store_it->second.ctx, frame_snapshot_json);
}

void LLMGeneralizer::flush_retries(const string & frame_snapshot_json)
{
  if (retry_queue_.empty()) return;

  vector<string> pending;
  pending.swap(retry_queue_);

  for (const string & cti_id : pending) {
    if (is_cti_accepted(cti_id)) continue;
    auto store_it = cti_store_.find(cti_id);
    if (store_it == cti_store_.end()) continue;
    write_request_for_cti(store_it->second.ctx, frame_snapshot_json);
  }
}

vector<IC3FrameResponse> LLMGeneralizer::poll_responses()
{
  vector<IC3FrameResponse> responses;
  ifstream fin(response_path_);
  if (!fin.is_open()) return responses;

  fin.seekg(last_response_pos_);
  string line;
  while (getline(fin, line)) {
    if (line.empty() || line[0] != '{') continue;
    IC3FrameResponse resp = parse_ic3_frame_response_line(line);
    if (!resp.valid) {
      stats_.num_schema_fail++;
      logger.log(1, "LLM response schema fail: {}", resp.error_msg);
      continue;
    }
    stats_.num_candidates++;
    responses.push_back(resp);
  }
  last_response_pos_ = fin.tellg();
  return responses;
}

bool LLMGeneralizer::lookup_cti_meta(const string & cti_id,
                                     size_t & out_frame_idx,
                                     TermVec & out_cube) const
{
  auto it = cti_store_.find(cti_id);
  if (it == cti_store_.end()) return false;
  out_frame_idx = it->second.ctx.frame_idx;
  out_cube = it->second.cube;
  return true;
}

void LLMGeneralizer::log_stats() const
{
  logger.log(0, "LLM Generalization Statistics:");
  logger.log(0, "  Requests sent:       {}", stats_.num_requests);
  logger.log(0, "  Candidates received: {}", stats_.num_candidates);
  logger.log(0, "  Accepted:            {}", stats_.num_accepted);
  logger.log(0, "  Schema failures:     {}", stats_.num_schema_fail);
  logger.log(0, "  Parse failures:      {}", stats_.num_parse_fail);
  logger.log(0, "  Vocab failures:      {}", stats_.num_vocab_fail);
  logger.log(0, "  Induction failures:  {}", stats_.num_induction_fail);
  logger.log(0, "  Rejected initial:    {}", stats_.num_rejected_initial);
  logger.log(0, "  Missing block:       {}", stats_.num_missing_block);
  logger.log(0, "  Lookup miss:         {}", stats_.num_lookup_miss);
  logger.log(0, "  Attempt mismatch:    {}", stats_.num_attempt_mismatch);
  logger.log(0, "  Budget skips:        {}", stats_.num_budget_skip);
  logger.log(0, "  Predicates added:    {}", stats_.num_predicates_added);
  const size_t rejected_total =
      stats_.num_schema_fail + stats_.num_parse_fail + stats_.num_vocab_fail
      + stats_.num_induction_fail + stats_.num_rejected_initial
      + stats_.num_missing_block + stats_.num_lookup_miss
      + stats_.num_attempt_mismatch;
  cerr << "LLM_STATS accepted=" << stats_.num_accepted << " rejected="
       << rejected_total
       << " errors=0 requests=" << stats_.num_requests
       << " candidates=" << stats_.num_candidates << " schema_fail="
       << stats_.num_schema_fail << " parse_fail=" << stats_.num_parse_fail
       << " vocab_fail=" << stats_.num_vocab_fail << " induction_fail="
       << stats_.num_induction_fail << " rejected_initial="
       << stats_.num_rejected_initial << " missing_block="
       << stats_.num_missing_block << " lookup_miss=" << stats_.num_lookup_miss
       << " attempt_mismatch=" << stats_.num_attempt_mismatch
       << " budget_skip=" << stats_.num_budget_skip
       << " predicates_added=" << stats_.num_predicates_added
       << " batch_timeouts=" << stats_.num_batch_timeout << endl;
}

}  // namespace pono
