/*********************                                                  */
/*! \file llm_generalizer.cpp
** \brief IC3 Frame v1 online LLM JSONL protocol
**/

#include "engines/llm_generalizer.h"

#include <algorithm>
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

static bool append_jsonl_line(const string & path, const string & json_body)
{
  ensure_dir_for_file(path);
  ofstream fout(path, ios::app);
  if (!fout.is_open()) return false;
  fout << json_body << "\n";
  fout.flush();
  return true;
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

static string escape_json_string(const string & s)
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

/** tellg() returns -1 at EOF; seekg(-1) fails and breaks append-only polling. */
static bool response_offset_valid(streampos pos)
{
  return static_cast<long long>(pos) >= 0;
}

static streampos safe_response_offset(streampos pos)
{
  return response_offset_valid(pos) ? pos : streampos(0);
}

/** Find the matching closing character for open_ch at open_pos, respecting nesting
 *  and JSON string literals. Returns string::npos if not found. */
static size_t find_json_matching_close(const string & s, size_t open_pos,
                                       char open_ch, char close_ch)
{
  int depth = 0;
  bool in_str = false;
  bool escape = false;
  for (size_t i = open_pos; i < s.size(); ++i) {
    char c = s[i];
    if (escape) { escape = false; continue; }
    if (c == '\\' && in_str) { escape = true; continue; }
    if (c == '"') { in_str = !in_str; continue; }
    if (in_str) continue;
    if (c == open_ch) { ++depth; }
    else if (c == close_ch) { if (--depth == 0) return i; }
  }
  return string::npos;
}

/** Parse the value of a JSON string field from a JSON object/line. */
static string parse_json_string_field(const string & s, const string & key)
{
  string needle = "\"" + key + "\"";
  size_t pos = s.find(needle);
  if (pos == string::npos) return {};
  pos = s.find('"', pos + needle.size());
  if (pos == string::npos) return {};
  // Skip optional ':' and whitespace
  size_t val_start = s.find('"', pos + 1);
  // Handle ": " case — find the actual value quote after the key's closing quote
  // pos is the closing quote of the key; next non-space char should be ':'
  size_t colon = s.find(':', pos);
  if (colon == string::npos) return {};
  val_start = s.find('"', colon + 1);
  if (val_start == string::npos) return {};
  size_t val_end = val_start + 1;
  bool esc = false;
  while (val_end < s.size()) {
    char c = s[val_end];
    if (esc) { esc = false; ++val_end; continue; }
    if (c == '\\') { esc = true; ++val_end; continue; }
    if (c == '"') break;
    ++val_end;
  }
  return s.substr(val_start + 1, val_end - val_start - 1);
}

}  // namespace

std::string format_cti_literal_line(const CTILiteral & lit)
{
  string ref = extract_state_ref(lit.varname);
  string rhs = lit.value;
  if (rhs == "true") rhs = "1";
  if (rhs == "false") rhs = "0";
  return (lit.polarity ? "" : "!") + ref + "=" + rhs;
}

std::string ref_from_digest_lit_line(const string & lit)
{
  string text = lit;
  while (!text.empty() && (text.front() == ' ' || text.front() == '\t')) {
    text.erase(text.begin());
  }
  if (text.empty() || text.find('(') != string::npos
      || text.find("bvor") != string::npos
      || text.find("bvcomp") != string::npos) {
    return "";
  }
  bool neg = !text.empty() && text[0] == '!';
  size_t start = neg ? 1 : 0;
  size_t eq = text.find('=', start);
  if (eq == string::npos || eq <= start) return "";
  string ref = text.substr(start, eq - start);
  if (ref.empty()) return "";
  return ref;
}

bool negate_digest_lit_to_disjunct(const string & lit, IC3FrameDisjunct & out)
{
  string text = lit;
  while (!text.empty() && (text.front() == ' ' || text.front() == '\t')) {
    text.erase(text.begin());
  }
  if (text.empty() || text.find('(') != string::npos
      || text.find("bvor") != string::npos
      || text.find("bvcomp") != string::npos) {
    return false;
  }
  bool neg_prefix = !text.empty() && text[0] == '!';
  size_t start = neg_prefix ? 1 : 0;
  size_t eq = text.find('=', start);
  if (eq == string::npos || eq <= start) return false;
  string ref = text.substr(start, eq - start);
  string rhs = text.substr(eq + 1);
  if (ref.empty() || rhs.empty()) return false;
  bool positive_pol = !neg_prefix;
  out.ref = ref;
  out.op = "eq";
  out.rhs = rhs;
  out.polarity = !positive_pol;
  return true;
}

std::string serialize_init_raw_json(
    const vector<string> & refs,
    const unordered_map<string, string> & values)
{
  ostringstream out;
  out << "{\"refs\":[";
  for (size_t i = 0; i < refs.size(); ++i) {
    if (i > 0) out << ",";
    out << "\"" << escape_json_string(refs[i]) << "\"";
  }
  out << "],\"values\":{";
  bool first_val = true;
  for (const string & ref : refs) {
    auto it = values.find(ref);
    if (it == values.end() || it->second.empty()) continue;
    if (!first_val) out << ",";
    first_val = false;
    out << "\"" << escape_json_string(ref) << "\":\""
        << escape_json_string(it->second) << "\"";
  }
  out << "}}";
  return out.str();
}

std::string serialize_candidate_hints_json(const vector<LLMCandidateHint> & hints)
{
  ostringstream out;
  out << "[";
  for (size_t i = 0; i < hints.size(); ++i) {
    if (i > 0) out << ",";
    const auto & h = hints[i];
    out << "{\"lit\":\"" << escape_json_string(h.lit) << "\",";
    out << "\"count\":" << h.count << ",";
    out << "\"block_disjunct\":{";
    out << "\"ref\":\"" << escape_json_string(h.block_disjunct.ref) << "\",";
    out << "\"op\":\"" << escape_json_string(h.block_disjunct.op) << "\",";
    out << "\"rhs\":\"" << escape_json_string(h.block_disjunct.rhs) << "\",";
    out << "\"polarity\":" << (h.block_disjunct.polarity ? "true" : "false");
    out << "},";
    out << "\"init_safe\":" << (h.init_safe ? "true" : "false");
    if (!h.reason.empty()) {
      out << ",\"reason\":\"" << escape_json_string(h.reason) << "\"";
    }
    out << "}";
  }
  out << "]";
  return out.str();
}

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

bool LLMGeneralizer::is_semantic_guidance() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_SEMANTIC;
}

// ---------------------------------------------------------------------------
// Semantic guidance — Stage 0 / Stage 2
// ---------------------------------------------------------------------------

string LLMGeneralizer::build_stage0_request_json() const
{
  auto ts = chrono::duration_cast<chrono::milliseconds>(
                chrono::steady_clock::now().time_since_epoch())
                .count();
  ostringstream req_id_oss;
  req_id_oss << "inv_s0_" << ts;
  string req_id = req_id_oss.str();

  ostringstream oss;
  oss << "{\"type\":\"ic3_stage0_request\",\"schema_version\":1";
  oss << ",\"request_id\":\"" << req_id << "\"";
  oss << ",\"benchmark\":\"" << escape_json(benchmark_name_) << "\"";
  oss << ",\"property_desc\":\"" << escape_json(bad_expr_) << "\"";
  oss << ",\"btor2_path\":\"" << escape_json(opts_.filename_) << "\"";
  oss << ",\"symbol_registry\":{";
  bool first = true;
  for (const auto & kv : symbol_registry_) {
    if (!first) oss << ",";
    first = false;
    oss << "\"" << escape_json(kv.first) << "\":{";
    oss << "\"kind\":\"" << escape_json(kv.second.kind) << "\"";
    oss << ",\"width\":" << kv.second.width;
    oss << ",\"btor2_line\":" << kv.second.btor2_line;
    if (!kv.second.verilog.empty()) {
      oss << ",\"verilog\":\"" << escape_json(kv.second.verilog) << "\"";
    }
    oss << "}";
  }
  oss << "}}";
  return oss.str();
}

string LLMGeneralizer::build_stage2_request_json(
    size_t frame_idx,
    const string & trigger,
    size_t total_cti_count,
    size_t frame_clause_count,
    const vector<unordered_map<string, string>> & cti_cluster) const
{
  auto ts = chrono::duration_cast<chrono::milliseconds>(
                chrono::steady_clock::now().time_since_epoch())
                .count();
  ostringstream req_id_oss;
  req_id_oss << "inv_s2_f" << frame_idx << "_" << ts;
  string req_id = req_id_oss.str();

  ostringstream oss;
  oss << "{\"type\":\"ic3_stage2_request\",\"schema_version\":1";
  oss << ",\"request_id\":\"" << req_id << "\"";
  oss << ",\"benchmark\":\"" << escape_json(benchmark_name_) << "\"";
  oss << ",\"property_desc\":\"" << escape_json(bad_expr_) << "\"";
  oss << ",\"btor2_path\":\"" << escape_json(opts_.filename_) << "\"";
  oss << ",\"trigger\":\"" << escape_json(trigger) << "\"";
  oss << ",\"proof_state\":{";
  oss << "\"frame_idx\":" << frame_idx;
  oss << ",\"total_cti_count\":" << total_cti_count;
  oss << ",\"frame_clause_count\":" << frame_clause_count;
  oss << "}";
  oss << ",\"cti_cluster\":[";
  bool first_cti = true;
  for (const auto & cti : cti_cluster) {
    if (!first_cti) oss << ",";
    first_cti = false;
    oss << "{";
    bool first_kv = true;
    for (const auto & kv : cti) {
      if (!first_kv) oss << ",";
      first_kv = false;
      oss << "\"" << escape_json(kv.first) << "\":\"" << escape_json(kv.second) << "\"";
    }
    oss << "}";
  }
  oss << "]}";
  return oss.str();
}

void LLMGeneralizer::write_invariant_request(const string & req_json)
{
  last_invariant_request_id_ = parse_json_string_field(req_json, "request_id");
  if (!append_jsonl_line(request_path_, req_json)) {
    logger.log(1, "LLM: failed to write invariant request to {}", request_path_);
  }
}

bool LLMGeneralizer::poll_invariant_response(
    const string & request_id,
    unsigned timeout_ms,
    vector<IC3FramePredicateNode> & candidates_out)
{
  using clock = chrono::steady_clock;
  candidates_out.clear();
  const auto deadline = clock::now() + chrono::milliseconds(timeout_ms);

  while (true) {
    ifstream fin(response_path_);
    if (fin.is_open()) {
      // Full-file scan to avoid stale streampos issues on appended files.
      fin.seekg(0);
      string line;
      while (getline(fin, line)) {
        if (line.empty() || line[0] != '{') continue;
        if (line.find(request_id) == string::npos) continue;
        if (line.find("\"ic3_invariant_response\"") == string::npos) continue;
        // Confirm request_id matches (guard against substring false positives).
        string found_id = parse_json_string_field(line, "request_id");
        if (found_id != request_id) continue;

        // Extract the candidates array.
        size_t arr_pos = line.find("\"candidates\"");
        if (arr_pos != string::npos) {
          size_t bracket_pos = line.find('[', arr_pos);
          if (bracket_pos != string::npos) {
            size_t bracket_end =
                find_json_matching_close(line, bracket_pos, '[', ']');
            if (bracket_end != string::npos) {
              string arr = line.substr(bracket_pos + 1,
                                       bracket_end - bracket_pos - 1);
              size_t cur = 0;
              while (cur < arr.size()) {
                size_t obj_start = arr.find('{', cur);
                if (obj_start == string::npos) break;
                size_t obj_end =
                    find_json_matching_close(arr, obj_start, '{', '}');
                if (obj_end == string::npos) break;
                string candidate =
                    arr.substr(obj_start, obj_end - obj_start + 1);
                IC3FramePredicateNode node;
                if (extract_predicate_ast_field(candidate, node)) {
                  candidates_out.push_back(node);
                }
                cur = obj_end + 1;
              }
            }
          }
        }
        return true;
      }
    }

    if (clock::now() >= deadline) return false;
    this_thread::sleep_for(chrono::milliseconds(100));
  }
}

void LLMGeneralizer::update_stuck_counter(bool made_progress)
{
  if (made_progress) {
    frames_stuck_rounds_ = 0;
  } else {
    ++frames_stuck_rounds_;
  }
}

void LLMGeneralizer::reset_stage2_cooldown(int cooldown_ctis)
{
  stage2_cooldown_remaining_ = cooldown_ctis;
}

bool LLMGeneralizer::stage2_cooldown_active() const
{
  return stage2_cooldown_remaining_ > 0;
}

void LLMGeneralizer::decrement_cooldown()
{
  if (stage2_cooldown_remaining_ > 0) --stage2_cooldown_remaining_;
}

int LLMGeneralizer::cti_cluster_density(size_t frame_idx) const
{
  auto it = frame_cti_buffer_.find(frame_idx);
  if (it == frame_cti_buffer_.end()) return 0;
  return static_cast<int>(it->second.size());
}

vector<unordered_map<string, string>> LLMGeneralizer::collect_frame_cti_cluster(
    size_t frame_idx, size_t max_ctis) const
{
  vector<unordered_map<string, string>> result;
  auto it = frame_cti_buffer_.find(frame_idx);
  if (it == frame_cti_buffer_.end()) return result;
  const auto & buffered = it->second;
  size_t n = min(buffered.size(), max_ctis);
  for (size_t i = 0; i < n; ++i) {
    unordered_map<string, string> cti_map;
    for (const auto & lit : buffered[i].ctx.literals) {
      string ref = extract_state_ref(lit.varname);
      if (!ref.empty() && ref.rfind("state", 0) == 0) {
        cti_map[ref] = lit.value;
      }
    }
    if (!cti_map.empty()) result.push_back(cti_map);
  }
  return result;
}

// ---------------------------------------------------------------------------

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

void LLMGeneralizer::collect_buffered_literal_keys(size_t frame_idx,
                                                   vector<string> & out) const
{
  out.clear();
  auto it = frame_cti_buffer_.find(frame_idx);
  if (it == frame_cti_buffer_.end()) return;
  unordered_set<string> seen;
  for (const auto & b : it->second) {
    for (const auto & lit : b.ctx.literals) {
      string key = format_literal_line(lit);
      if (seen.insert(key).second) out.push_back(key);
    }
  }
}

void LLMGeneralizer::collect_cti_literal_refs(
    const string & cti_id, unordered_set<string> & out) const
{
  out.clear();
  if (cti_id.rfind("batch_", 0) == 0) {
    auto it = batch_store_.find(cti_id);
    if (it == batch_store_.end()) return;
    for (const auto & stored : it->second.ctis) {
      for (const auto & lit : stored.ctx.literals) {
        string ref = extract_state_ref(lit.varname);
        if (!ref.empty()) out.insert(ref);
      }
    }
    return;
  }
  auto it = cti_store_.find(cti_id);
  if (it == cti_store_.end()) return;
  for (const auto & lit : it->second.ctx.literals) {
    string ref = extract_state_ref(lit.varname);
    if (!ref.empty()) out.insert(ref);
  }
}

void LLMGeneralizer::collect_digest_ranked_literals(
    size_t frame_idx,
    const string & batch_cti_id,
    vector<pair<string, size_t>> & out,
    size_t max_lits) const
{
  out.clear();
  vector<BufferedCTI> source;
  if (!batch_cti_id.empty()) {
    auto it = batch_store_.find(batch_cti_id);
    if (it != batch_store_.end()) {
      for (const auto & stored : it->second.ctis) {
        BufferedCTI b;
        b.ctx = stored.ctx;
        source.push_back(b);
      }
    }
  } else {
    auto it = frame_cti_buffer_.find(frame_idx);
    if (it != frame_cti_buffer_.end()) source = it->second;
  }

  unordered_map<string, size_t> lit_counts;
  for (const auto & b : source) {
    unordered_set<string> seen_lit;
    for (const auto & lit : b.ctx.literals) {
      string key = format_literal_line(lit);
      if (seen_lit.insert(key).second) lit_counts[key]++;
    }
  }
  vector<pair<string, size_t>> ranked(lit_counts.begin(), lit_counts.end());
  sort(ranked.begin(),
       ranked.end(),
       [](const pair<string, size_t> & a, const pair<string, size_t> & b) {
         return a.second > b.second;
       });
  const size_t cap = max_lits > 0 ? max_lits : opts_.llm_cti_digest_top_lits_;
  if (ranked.size() > cap) ranked.resize(cap);
  out.swap(ranked);
}

void LLMGeneralizer::collect_init_raw_refs(size_t frame_idx,
                                           const string & batch_cti_id,
                                           vector<string> & out) const
{
  out.clear();
  const size_t max_refs = opts_.llm_init_raw_max_refs_;
  if (max_refs == 0) return;

  vector<BufferedCTI> source;
  if (!batch_cti_id.empty()) {
    auto it = batch_store_.find(batch_cti_id);
    if (it != batch_store_.end()) {
      for (const auto & stored : it->second.ctis) {
        BufferedCTI b;
        b.ctx = stored.ctx;
        source.push_back(b);
      }
    }
  } else {
    auto it = frame_cti_buffer_.find(frame_idx);
    if (it != frame_cti_buffer_.end()) source = it->second;
  }

  unordered_set<string> seen;
  auto add_ref = [&](const string & ref) {
    if (ref.empty() || seen.count(ref)) return;
    seen.insert(ref);
    out.push_back(ref);
  };

  unordered_map<string, size_t> lit_counts;
  for (const auto & b : source) {
    unordered_set<string> seen_lit;
    for (const auto & lit : b.ctx.literals) {
      string key = format_literal_line(lit);
      if (seen_lit.insert(key).second) lit_counts[key]++;
    }
  }
  vector<pair<string, size_t>> ranked(lit_counts.begin(), lit_counts.end());
  sort(ranked.begin(),
       ranked.end(),
       [](const pair<string, size_t> & a, const pair<string, size_t> & b) {
         return a.second > b.second;
       });
  const size_t top_lits = opts_.llm_cti_digest_top_lits_;
  if (ranked.size() > top_lits) ranked.resize(top_lits);
  for (const auto & row : ranked) {
    add_ref(ref_from_digest_lit_line(row.first));
    if (out.size() >= max_refs) return;
  }

  auto ingest_feedback = [&](const string & key) {
    auto fb_it = feedback_by_cti_.find(key);
    if (fb_it == feedback_by_cti_.end()) return;
    for (const auto & fb : fb_it->second) {
      add_ref(fb.witness_ref);
      if (out.size() >= max_refs) return;
    }
  };

  if (!batch_cti_id.empty()) {
    ingest_feedback(batch_feedback_key(batch_cti_id));
    if (out.size() < max_refs) ingest_feedback(batch_cti_id);
  } else {
    ingest_feedback("batch_f" + std::to_string(frame_idx));
  }
}

void LLMGeneralizer::collect_cti_literal_keys(const string & cti_id,
                                              vector<string> & out) const
{
  out.clear();
  unordered_set<string> seen;
  if (cti_id.rfind("batch_", 0) == 0) {
    auto it = batch_store_.find(cti_id);
    if (it == batch_store_.end()) return;
    for (const auto & stored : it->second.ctis) {
      for (const auto & lit : stored.ctx.literals) {
        string key = format_literal_line(lit);
        if (seen.insert(key).second) out.push_back(key);
      }
    }
    return;
  }
  auto it = cti_store_.find(cti_id);
  if (it == cti_store_.end()) return;
  for (const auto & lit : it->second.ctx.literals) {
    string key = format_literal_line(lit);
    if (seen.insert(key).second) out.push_back(key);
  }
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

static void append_disjunct_json(ostream & out,
                                 const IC3FrameDisjunct & d,
                                 const function<string(const string &)> & escape)
{
  out << "{\"ref\":\"" << escape(d.ref) << "\",";
  out << "\"op\":\"" << escape(d.op) << "\",";
  out << "\"rhs\":\"" << escape(d.rhs) << "\",";
  out << "\"polarity\":" << (d.polarity ? "true" : "false") << "}";
}

static string serialize_response_for_feedback(
    const IC3FrameResponse & rejected,
    size_t clause_idx,
    const function<string(const string &)> & escape)
{
  vector<vector<IC3FrameDisjunct>> clauses = rejected.block_clauses;
  if (clauses.empty() && !rejected.block_disjuncts.empty()) {
    clauses.push_back(rejected.block_disjuncts);
  }

  ostringstream out;
  out << "{";
  out << "\"source_cti_id\":\"" << escape(rejected.source_cti_id) << "\",";
  out << "\"sample_id\":" << rejected.sample_id << ",";
  out << "\"attempt\":" << rejected.attempt << ",";
  out << "\"has_block\":" << (rejected.has_block ? "true" : "false") << ",";
  out << "\"has_refine_predicate\":"
      << (rejected.has_refine_predicate ? "true" : "false") << ",";
  out << "\"block_clauses\":[";
  for (size_t ci = 0; ci < clauses.size(); ++ci) {
    if (ci > 0) out << ",";
    out << "[";
    for (size_t di = 0; di < clauses[ci].size(); ++di) {
      if (di > 0) out << ",";
      append_disjunct_json(out, clauses[ci][di], escape);
    }
    out << "]";
  }
  out << "],";
  if (clause_idx != SIZE_MAX) {
    out << "\"clause_idx\":" << clause_idx << ",";
  }
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
                                  const string & witness_next,
                                  size_t clause_idx)
{
  LLMFeedbackEntry fb;
  fb.reason = reason;
  fb.rejected_json =
      serialize_response_for_feedback(rejected,
                                      clause_idx,
                                      [this](const string & s) {
                                        return escape_json(s);
                                      });
  fb.witness_ref = witness_ref;
  fb.witness_next_value = witness_next;
  fb.clause_idx = clause_idx;
  fb.sample_id = rejected.sample_id;
  vector<vector<IC3FrameDisjunct>> clauses = rejected.block_clauses;
  if (clauses.empty() && !rejected.block_disjuncts.empty()) {
    clauses.push_back(rejected.block_disjuncts);
  }
  if (clause_idx != SIZE_MAX && clause_idx < clauses.size()) {
    fb.failed_clause = clauses[clause_idx];
  } else if (!clauses.empty()) {
    fb.failed_clause = clauses.back();
  }
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

string LLMGeneralizer::format_literal_line(const CTILiteral & lit) const
{
  return format_cti_literal_line(lit);
}

void LLMGeneralizer::build_cti_digest(const vector<BufferedCTI> & buffered,
                                      vector<size_t> & out_indices,
                                      string & out_digest_json,
                                      size_t max_cubes_override) const
{
  const size_t n = buffered.size();
  const size_t max_cubes = max_cubes_override > 0
                               ? max_cubes_override
                               : opts_.llm_cti_digest_max_cubes_;
  const size_t top_lits = opts_.llm_cti_digest_top_lits_;

  unordered_map<string, size_t> lit_counts;
  for (const auto & b : buffered) {
    unordered_set<string> seen;
    for (const auto & lit : b.ctx.literals) {
      string key = format_literal_line(lit);
      if (seen.insert(key).second) lit_counts[key]++;
    }
  }

  vector<pair<string, size_t>> ranked(lit_counts.begin(), lit_counts.end());
  sort(ranked.begin(),
       ranked.end(),
       [](const pair<string, size_t> & a, const pair<string, size_t> & b) {
         return a.second > b.second;
       });
  if (ranked.size() > top_lits) ranked.resize(top_lits);

  out_indices.clear();
  if (n == 0) {
    out_digest_json = "{}";
    return;
  }
  if (n <= max_cubes) {
    for (size_t i = 0; i < n; ++i) out_indices.push_back(i);
  } else if (max_cubes <= 1) {
    out_indices.push_back(0);
  } else {
    for (size_t k = 0; k < max_cubes; ++k) {
      out_indices.push_back((k * (n - 1)) / (max_cubes - 1));
    }
  }

  ostringstream d;
  d << "{\"cti_total\":" << n << ",\"literal_stats\":[";
  for (size_t i = 0; i < ranked.size(); ++i) {
    if (i > 0) d << ",";
    d << "{\"lit\":\"" << escape_json(ranked[i].first) << "\",";
    d << "\"count\":" << ranked[i].second << "}";
  }
  d << "]}";
  out_digest_json = d.str();
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
    bool pol = lit.polarity;
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
  out << "\"max_block_clauses\":" << opts_.llm_max_block_clauses_ << ",";
  out << "\"parallel_group\":\"" << escape_json(ctx.cti_id + "_a" + std::to_string(attempt))
      << "\",";
  out << "\"parallel_samples\":" << opts_.llm_parallel_samples_ << ",";
  out << "\"reasoning_effort\":\"" << escape_json(opts_.llm_reasoning_effort_) << "\",";
  out << "\"model\":\""
      << escape_json(opts_.llm_model_.empty() ? "deepseek/deepseek-v4-flash"
                                               : opts_.llm_model_)
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

  vector<LLMFeedbackEntry> fb;
  auto fb_it = feedback_by_cti_.find(ctx.cti_id);
  if (fb_it != feedback_by_cti_.end()) fb = fb_it->second;

  ostringstream buf;
  serialize_frame_request(buf, ctx, attempt, fb, frame_snapshot_json);
  if (!append_jsonl_line(request_path_, buf.str())) {
    logger.log(0, "LLMGeneralizer: cannot open request file {}", request_path_);
    return;
  }
  register_outstanding_samples(ctx.cti_id, attempt);
  stats_.num_requests++;
}

void LLMGeneralizer::append_feedback_raw_json(
    ostream & out, const vector<LLMFeedbackEntry> & feedback) const
{
  out << "\"feedback_raw\":[";
  for (size_t i = 0; i < feedback.size(); ++i) {
    if (i > 0) out << ",";
    const auto & fb = feedback[i];
    out << "{\"reason\":\"" << escape_json(fb.reason) << "\",";
    out << "\"witness\":{";
    out << "\"ref\":\"" << escape_json(fb.witness_ref) << "\",";
    out << "\"next_value\":\"" << escape_json(fb.witness_next_value) << "\"},";
    out << "\"failed_clause\":[";
    for (size_t di = 0; di < fb.failed_clause.size(); ++di) {
      if (di > 0) out << ",";
      append_disjunct_json(out, fb.failed_clause[di], [this](const string & s) {
        return escape_json(s);
      });
    }
    out << "],";
    if (fb.clause_idx != SIZE_MAX) {
      out << "\"clause_idx\":" << fb.clause_idx << ",";
    }
    out << "\"sample_id\":" << fb.sample_id << "}";
  }
  out << "]";
}

void LLMGeneralizer::serialize_batch_request(
    ostream & out,
    const string & batch_id,
    size_t frame_idx,
    size_t attempt,
    const vector<BufferedCTI> & buffered,
    const vector<size_t> & export_indices,
    const string & digest_json,
    const vector<LLMFeedbackEntry> & feedback,
    const string & frame_snapshot_json,
    const string & init_raw_json,
    const string & candidate_hints_json)
{
  out << "{";
  out << "\"schema_version\":1,";
  out << "\"type\":\"ic3_frame_batch_request\",";
  out << "\"batch_id\":\"" << escape_json(batch_id) << "\",";
  out << "\"frame_idx\":" << frame_idx << ",";
  out << "\"attempt\":" << attempt << ",";
  out << "\"max_attempts\":" << opts_.llm_max_attempts_ << ",";
  out << "\"max_block_clauses\":" << opts_.llm_max_block_clauses_ << ",";
  out << "\"parallel_group\":\"" << escape_json(batch_id) << "\",";
  out << "\"parallel_samples\":" << opts_.llm_parallel_samples_ << ",";
  out << "\"temperature\":0.5,";
  out << "\"reasoning_effort\":\"" << escape_json(opts_.llm_reasoning_effort_) << "\",";
  out << "\"model\":\""
      << escape_json(opts_.llm_model_.empty() ? "deepseek/deepseek-v4-flash"
                                               : opts_.llm_model_)
      << "\",";
  out << "\"benchmark_context_path\":\"" << escape_json(benchmark_context_path_)
      << "\",";

  if (!digest_json.empty()) {
    out << "\"cti_digest\":" << digest_json << ",";
  }

  out << "\"cti_entries\":[";
  for (size_t i = 0; i < export_indices.size(); ++i) {
    if (i > 0) out << ",";
    const auto & b = buffered[export_indices[i]];
    out << "{\"cti_id\":\"" << escape_json(b.ctx.cti_id) << "\"";
    if (!digest_json.empty()) {
      out << ",\"literals\":[";
      unordered_set<string> seen;
      bool first_lit = true;
      for (const auto & lit : b.ctx.literals) {
        string key = format_literal_line(lit);
        if (!seen.insert(key).second) continue;
        if (!first_lit) out << ",";
        first_lit = false;
        out << "\"" << escape_json(key) << "\"";
      }
      out << "]";
    } else {
      out << ",";
      append_cti_cube_json(out, b.ctx);
    }
    out << "}";
  }
  out << "],";

  if (!frame_snapshot_json.empty()) {
    out << "\"frame_snapshot\":" << frame_snapshot_json << ",";
  } else {
    out << "\"frame_snapshot\":{\"frame_idx\":" << frame_idx
        << ",\"clauses\":[]},";
  }

  if (!init_raw_json.empty()) {
    out << "\"init_raw\":" << init_raw_json << ",";
  }

  if (!candidate_hints_json.empty()) {
    out << "\"candidate_hints\":" << candidate_hints_json << ",";
  }

  append_feedback_raw_json(out, feedback);
  out << ",";

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
                                        size_t attempt_arg,
                                        const string & init_raw_json,
                                        const string & candidate_hints_json)
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

  vector<LLMFeedbackEntry> fb;
  auto fb_it = feedback_by_cti_.find(batch_feedback_key(batch_id));
  if (fb_it != feedback_by_cti_.end()) fb = fb_it->second;

  vector<size_t> export_indices;
  for (size_t i = 0; i < buffered.size(); ++i) export_indices.push_back(i);
  string digest_json;

  auto serialize_line = [&](const vector<size_t> & indices,
                            const string & digest) -> string {
    ostringstream buf;
    serialize_batch_request(buf,
                            batch_id,
                            frame_idx,
                            attempt,
                            buffered,
                            indices,
                            digest,
                            fb,
                            frame_snapshot_json,
                            init_raw_json,
                            candidate_hints_json);
    return buf.str();
  };

  string line;
  if (opts_.llm_cti_digest_) {
    // Always attach cti_digest (Q3.2 needs stats on every attempt, including retries).
    size_t max_cubes = opts_.llm_cti_digest_max_cubes_;
    for (int shrink = 0; shrink < 5 && max_cubes > 0; ++shrink) {
      build_cti_digest(buffered, export_indices, digest_json, max_cubes);
      line = serialize_line(export_indices, digest_json);
      if (line.size() <= opts_.llm_batch_max_json_bytes_) break;
      if (max_cubes <= 1) break;
      max_cubes = std::max(max_cubes / 2, size_t(1));
    }
  } else {
    line = serialize_line(export_indices, digest_json);
  }

  if (!append_jsonl_line(request_path_, line)) {
    logger.log(0, "LLMGeneralizer: cannot open request file {}", request_path_);
    return;
  }
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
                                       const string & frame_snapshot_json,
                                       const string & init_raw_json,
                                       const string & candidate_hints_json)
{
  auto it = frame_cti_buffer_.find(frame_idx);
  if (it == frame_cti_buffer_.end() || it->second.empty()) {
    last_flushed_batch_id_.clear();
    return;
  }

  if (opts_.llm_batch_cti_) {
    write_batch_request(frame_idx,
                        frame_snapshot_json,
                        it->second,
                        0,
                        init_raw_json,
                        candidate_hints_json);
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
  const auto t0 = clock::now();
  const auto deadline = t0 + chrono::seconds(timeout_sec);
  size_t received_samples = 0;
  bool ok = false;

  while (clock::now() < deadline) {
    unordered_set<size_t> samples;
    ifstream fin(response_path_);
    if (fin) {
      // Full-file scan: batch_id filter is cheap; avoids stale streampos on append.
      fin.clear();
      fin.seekg(0);
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
    received_samples = samples.size();
    if (received_samples >= expected_samples) {
      ok = true;
      break;
    }
    this_thread::sleep_for(chrono::milliseconds(200));
  }

  const auto wait_ms = static_cast<uint64_t>(
      chrono::duration_cast<chrono::milliseconds>(clock::now() - t0).count());
  stats_.num_batch_waits++;
  stats_.total_batch_wait_ms += wait_ms;
  if (wait_ms > stats_.max_batch_wait_ms) {
    stats_.max_batch_wait_ms = wait_ms;
  }

  cerr << "LLM_BATCH_WAIT batch_id=" << batch_id << " wait_ms=" << wait_ms
       << " ok=" << (ok ? 1 : 0) << " samples=" << received_samples << "/"
       << expected_samples << endl;

  if (ok) {
    logger.log(1,
               "LLMGeneralizer: batch {} received {}/{} samples (wait_ms={})",
               batch_id,
               received_samples,
               expected_samples,
               wait_ms);
    return true;
  }

  stats_.num_batch_timeout++;
  logger.log(0,
               "LLMGeneralizer: batch {} wait timeout ({}s, wait_ms={})",
               batch_id,
               timeout_sec,
               wait_ms);
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
                                         const string & frame_snapshot_json,
                                         const string & init_raw_json,
                                         const string & candidate_hints_json)
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
    write_batch_request(it->second.frame_idx,
                        frame_snapshot_json,
                        buffered,
                        attempt,
                        init_raw_json,
                        candidate_hints_json);
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

  const streampos read_pos = safe_response_offset(last_response_pos_);
  fin.clear();
  fin.seekg(read_pos);
  string line;
  bool advanced = false;
  while (getline(fin, line)) {
    advanced = true;
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
  if (advanced) {
    fin.clear();
    fin.seekg(0, ios::end);
    const streampos end_pos = fin.tellg();
    if (response_offset_valid(end_pos)) {
      last_response_pos_ = end_pos;
    }
  }
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
  logger.log(0, "  Batch waits:         {}", stats_.num_batch_waits);
  logger.log(0, "  Batch wait total ms: {}", stats_.total_batch_wait_ms);
  logger.log(0, "  Batch wait max ms:   {}", stats_.max_batch_wait_ms);
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
       << " batch_timeouts=" << stats_.num_batch_timeout
       << " batch_waits=" << stats_.num_batch_waits
       << " batch_wait_ms_total=" << stats_.total_batch_wait_ms
       << " batch_wait_ms_max=" << stats_.max_batch_wait_ms << endl;
}

}  // namespace pono
