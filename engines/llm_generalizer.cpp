/*********************                                                  */
/*! \file llm_generalizer.cpp
** \brief LLM-guided lemma generalization for IC3/IC3-IA
**/

#include "engines/llm_generalizer.h"

#include <cassert>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <sys/types.h>

#include "utils/logger.h"

using namespace smt;
using namespace std;

namespace pono {

static std::vector<size_t> parse_size_array_field(const std::string & line,
                                                  const std::string & field)
{
  std::vector<size_t> out;
  size_t pos = line.find("\"" + field + "\"");
  if (pos == std::string::npos) return out;
  pos = line.find("[", pos);
  if (pos == std::string::npos) return out;
  size_t end = line.find("]", pos);
  if (end == std::string::npos) return out;
  std::string arr = line.substr(pos + 1, end - pos - 1);
  std::stringstream ss(arr);
  std::string item;
  while (std::getline(ss, item, ',')) {
    size_t first = item.find_first_of("0123456789");
    if (first == std::string::npos) continue;
    size_t last = item.find_last_of("0123456789");
    out.push_back(
        static_cast<size_t>(std::stoul(item.substr(first, last - first + 1))));
  }
  return out;
}

static std::string parse_string_field(const std::string & line,
                                      const std::string & field)
{
  size_t pos = line.find("\"" + field + "\"");
  if (pos == std::string::npos) return "";
  pos = line.find(":", pos);
  if (pos == std::string::npos) return "";
  pos = line.find("\"", pos);
  if (pos == std::string::npos) return "";
  size_t end = line.find("\"", pos + 1);
  if (end == std::string::npos) return "";
  return line.substr(pos + 1, end - pos - 1);
}

static void ensure_dir_exists(const std::string & path)
{
  if (path.empty()) return;
  std::string cur;
  for (char c : path) {
    cur.push_back(c);
    if (c == '/') {
      if (cur.size() > 1) mkdir(cur.c_str(), 0775);
    }
  }
  mkdir(path.c_str(), 0775);
}

LLMGeneralizer::LLMGeneralizer(PonoOptions opts, const SmtSolver & solver)
      : opts_(opts),
      solver_(solver),
      last_response_pos_(0),
      offline_records_loaded_(false)
{
  request_path_ = opts_.llm_request_path_.empty()
                      ? "/tmp/pono_llm_requests.jsonl"
                      : opts_.llm_request_path_;
  response_path_ = opts_.llm_response_path_.empty()
                       ? "/tmp/pono_llm_responses.jsonl"
                       : opts_.llm_response_path_;
  log_path_ = opts_.llm_log_path_.empty() ? "/tmp/pono_llm_log.jsonl"
                                          : opts_.llm_log_path_;
  replay_dir_ = opts_.llm_replay_dir_.empty() ? "llm_replay/default"
                                              : opts_.llm_replay_dir_;
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

bool LLMGeneralizer::is_seed_only() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_SEED_ONLY;
}

bool LLMGeneralizer::is_offline_dump() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_OFFLINE_DUMP;
}

bool LLMGeneralizer::is_offline_check() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_OFFLINE_CHECK;
}

std::string LLMGeneralizer::make_cti_id(
    size_t frame_idx, const std::vector<CTILiteral> & literals) const
{
  std::string raw = "frame" + std::to_string(frame_idx) + ":";
  for (const auto & lit : literals) {
    raw += std::to_string(lit.id) + "=" + lit.varname + "=" + lit.value + ";";
  }

  uint64_t hash = 1469598103934665603ULL;  // FNV-1a
  for (unsigned char c : raw) {
    hash ^= static_cast<uint64_t>(c);
    hash *= 1099511628211ULL;
  }

  std::ostringstream out;
  out << "frame" << frame_idx << ":" << std::hex << hash;
  return out.str();
}

void LLMGeneralizer::load_offline_records()
{
  if (offline_records_loaded_) return;
  offline_records_loaded_ = true;

  auto load_file = [&](const std::string & path,
                       std::unordered_map<std::string, LLMIdCandidate> & dst) {
    std::ifstream fin(path);
    if (!fin.is_open()) return;
    std::string line;
    while (std::getline(fin, line)) {
      if (line.empty() || line[0] != '{') continue;
      LLMIdCandidate cand;
      cand.cti_id = parse_string_field(line, "cti_id");
      cand.mode = parse_string_field(line, "mode");
      cand.confidence = parse_string_field(line, "confidence");
      cand.short_reason = parse_string_field(line, "short_reason");
      cand.keep_ids = parse_size_array_field(line, "keep_ids");
      if (cand.keep_ids.empty()) {
        cand.keep_ids = parse_size_array_field(line, "base_keep_ids");
      }
      cand.drop_ids = parse_size_array_field(line, "drop_ids");
      cand.add_back_ids = parse_size_array_field(line, "add_back_ids");
      if (!cand.cti_id.empty()) dst[cand.cti_id] = cand;
    }
  };

  load_file(replay_dir_ + "/proposals.jsonl", proposals_);
  load_file(replay_dir_ + "/repairs.jsonl", repairs_);
}

bool LLMGeneralizer::get_proposal(const std::string & cti_id,
                                  LLMIdCandidate & out) const
{
  auto it = proposals_.find(cti_id);
  if (it == proposals_.end()) return false;
  out = it->second;
  return true;
}

bool LLMGeneralizer::get_repair(const std::string & cti_id,
                                LLMIdCandidate & out) const
{
  auto it = repairs_.find(cti_id);
  if (it == repairs_.end()) return false;
  out = it->second;
  return true;
}

void LLMGeneralizer::write_offline_cti_context(const CTIContext & ctx)
{
  ensure_dir_exists(replay_dir_);
  std::ofstream fout(replay_dir_ + "/cti_contexts.jsonl", std::ios::app);
  if (!fout.is_open()) {
    logger.log(
        0, "LLMGeneralizer: cannot write offline CTI contexts in {}", replay_dir_);
    return;
  }

  fout << "{\"schema_version\":1,";
  fout << "\"cti_id\":\"" << escape_json(ctx.cti_id) << "\",";
  fout << "\"frame\":" << ctx.frame_idx << ",";
  fout << "\"property\":\"" << escape_json(ctx.property_name) << "\",";
  fout << "\"literals\":[";
  for (size_t i = 0; i < ctx.literals.size(); ++i) {
    const auto & lit = ctx.literals[i];
    if (i) fout << ",";
    fout << "{\"id\":" << lit.id << ",";
    fout << "\"expr\":\"" << escape_json(lit.expr) << "\",";
    fout << "\"varname\":\"" << escape_json(lit.varname) << "\",";
    fout << "\"value\":\"" << escape_json(lit.value) << "\",";
    fout << "\"kind\":\"" << escape_json(lit.kind) << "\",";
    fout << "\"signals\":[";
    for (size_t j = 0; j < lit.signals.size(); ++j) {
      if (j) fout << ",";
      fout << "\"" << escape_json(lit.signals[j]) << "\"";
    }
    fout << "]}";
  }
  fout << "]}\n";
  stats_.num_requests++;
}

void LLMGeneralizer::write_static_context(
    const std::string & benchmark_name,
    const std::string & bad_expr,
    const std::vector<CTILiteral> & states,
    const std::vector<CTILiteral> & inputs,
    const std::vector<std::string> & state_updates)
{
  ensure_dir_exists(replay_dir_);
  std::ofstream fout(replay_dir_ + "/static_context.json");
  if (!fout.is_open()) {
    logger.log(
        0, "LLMGeneralizer: cannot write static context in {}", replay_dir_);
    return;
  }

  fout << "{\n";
  fout << "  \"schema_version\": 1,\n";
  fout << "  \"benchmark\": \"" << escape_json(benchmark_name) << "\",\n";
  fout << "  \"property\": {\"bad_expr\": \"" << escape_json(bad_expr)
       << "\"},\n";

  auto emit_lits = [&](const char * name,
                       const std::vector<CTILiteral> & vars) {
    fout << "  \"" << name << "\": [";
    for (size_t i = 0; i < vars.size(); ++i) {
      if (i) fout << ",";
      fout << "{\"name\":\"" << escape_json(vars[i].varname)
           << "\",\"width\":1}";
    }
    fout << "],\n";
  };

  emit_lits("states", states);
  emit_lits("inputs", inputs);
  fout << "  \"state_updates\": [";
  for (size_t i = 0; i < state_updates.size(); ++i) {
    if (i) fout << ",";
    fout << "\"" << escape_json(state_updates[i]) << "\"";
  }
  fout << "],\n";
  fout << "  \"notes\": [\"All LLM candidates are checked on the full "
          "transition system.\"]\n";
  fout << "}\n";
}

void LLMGeneralizer::write_replay_result(const std::string & cti_id,
                                         const std::string & status,
                                         size_t frame_idx,
                                         size_t original_size,
                                         size_t candidate_size,
                                         const std::string & reason)
{
  ensure_dir_exists(replay_dir_);
  const bool repair_status = status.find("repair_") == 0;
  const std::string out_path =
      replay_dir_
      + (repair_status ? "/repair_replay_results.jsonl"
                       : "/proposal_replay_results.jsonl");
  std::ofstream fout(out_path, std::ios::app);
  if (!fout.is_open()) return;

  fout << "{\"schema_version\":1,";
  fout << "\"cti_id\":\"" << escape_json(cti_id) << "\",";
  fout << "\"status\":\"" << escape_json(status) << "\",";
  fout << "\"frame\":" << frame_idx << ",";
  fout << "\"original_size\":" << original_size << ",";
  fout << "\"candidate_size\":" << candidate_size << ",";
  fout << "\"reason\":\"" << escape_json(reason) << "\"}\n";
}

void LLMGeneralizer::write_repair_request(
    const CTIContext & ctx,
    const LLMIdCandidate & failed,
    const std::vector<LLMWitnessDiff> & diffs)
{
  ensure_dir_exists(replay_dir_);
  std::ofstream fout(replay_dir_ + "/repair_requests.jsonl", std::ios::app);
  if (!fout.is_open()) return;

  fout << "{\"schema_version\":1,";
  fout << "\"cti_id\":\"" << escape_json(ctx.cti_id) << "\",";
  fout << "\"frame\":" << ctx.frame_idx << ",";
  fout << "\"failed_keep_ids\":[";
  for (size_t i = 0; i < failed.keep_ids.size(); ++i) {
    if (i) fout << ",";
    fout << failed.keep_ids[i];
  }
  fout << "],\"failed_drop_ids\":[";
  for (size_t i = 0; i < failed.drop_ids.size(); ++i) {
    if (i) fout << ",";
    fout << failed.drop_ids[i];
  }
  fout << "],\"sat_witness_diff\":[";
  for (size_t i = 0; i < diffs.size(); ++i) {
    if (i) fout << ",";
    fout << "{\"literal_id\":" << diffs[i].literal_id << ",";
    fout << "\"cti_literal\":\"" << escape_json(diffs[i].cti_literal)
         << "\",";
    fout << "\"witness_value\":\"" << escape_json(diffs[i].witness_value)
         << "\",";
    fout << "\"effect\":\"" << escape_json(diffs[i].effect) << "\"}";
  }
  fout << "]}\n";
}

string LLMGeneralizer::escape_json(const string & s) const
{
  ostringstream out;
  for (char c : s) {
    switch (c) {
      case '"': out << "\\\""; break;
      case '\\': out << "\\\\"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default: out << c;
    }
  }
  return out.str();
}

void LLMGeneralizer::write_cti_context(const CTIContext & ctx)
{
  // Cap: don't send more than 50 CTI contexts per benchmark
  if (stats_.num_requests >= 50) {
    return;
  }

  // Dedup: skip duplicate CTI contexts (same literals with same values)
  std::string ctx_hash;
  for (const auto & lit : ctx.literals) {
    ctx_hash += lit.varname + lit.value;
  }
  if (sent_ctx_hashes_.count(ctx_hash)) {
    return;
  }
  sent_ctx_hashes_.insert(ctx_hash);

  ofstream fout(request_path_, ios::app);
  if (!fout.is_open()) {
    logger.log(0, "LLMGeneralizer: cannot open request file {}", request_path_);
    return;
  }

  ostringstream json;
  json << "{";
  json << "\"frame_idx\":" << ctx.frame_idx << ",";
  json << "\"property\":\"" << escape_json(ctx.property_name) << "\",";
  json << "\"literals\":[";
  for (size_t i = 0; i < ctx.literals.size(); ++i) {
    if (i > 0) json << ",";
    json << "{\"varname\":\"" << escape_json(ctx.literals[i].varname) << "\",";
    json << "\"value\":\"" << escape_json(ctx.literals[i].value) << "\"}";
  }
  json << "],";
  json << "\"candidate_language\":\""
       << (opts_.llm_candidate_language_ == LLMCandidateLanguage::CUBE_SUBSET
               ? "cube-subset"
               : (opts_.llm_candidate_language_ == LLMCandidateLanguage::QF_SMT
                      ? "qf-smt"
                      : "predicate-relation"))
       << "\",";
  json << "\"model\":\""
       << escape_json(opts_.llm_model_.empty() ? "deepseek-v4-pro"
                                               : opts_.llm_model_)
       << "\"";
  json << "}";
  json << "\n";

  fout << json.str();
  fout.close();

  stats_.num_requests++;
  logger.log(1,
             "LLMGeneralizer: wrote CTI context for frame {} ({} literals)",
             ctx.frame_idx,
             ctx.literals.size());
}

vector<LLMCandidate> LLMGeneralizer::poll_candidates()
{
  vector<LLMCandidate> candidates;

  ifstream fin(response_path_);
  if (!fin.is_open()) {
    return candidates;
  }

  fin.seekg(last_response_pos_);

  string line;
  while (getline(fin, line)) {
    if (line.empty() || line[0] != '{') continue;

    try {
    LLMCandidate cand;
    cand.type = LLMCandidate::CUBE_SUBSET;
    cand.frame_hint = 0;

    // minimal JSON parsing for the expected schema
    size_t pos = 0;

    // parse type
    pos = line.find("\"type\"");
    if (pos != string::npos) {
      pos = line.find("\"", pos + 7);
      if (pos != string::npos) {
        size_t end = line.find("\"", pos + 1);
        string type_str = line.substr(pos + 1, end - pos - 1);
        if (type_str == "cube_subset" || type_str == "cube-subset") {
          cand.type = LLMCandidate::CUBE_SUBSET;
        } else if (type_str == "qf_smt_formula" || type_str == "qf-smt") {
          cand.type = LLMCandidate::QF_SMT;
        } else if (type_str == "predicate_relation"
                   || type_str == "predicate-relation") {
          cand.type = LLMCandidate::PREDICATE_RELATION;
        }
      }
    }

    // parse frame_hint
    pos = line.find("\"frame_hint\"");
    if (pos != string::npos) {
      pos = line.find(":", pos);
      if (pos != string::npos) {
        try {
          cand.frame_hint = stoul(line.substr(pos + 1));
        } catch (...) {
          cand.frame_hint = 0;
        }
      }
    }

    // parse keep_literals array
    pos = line.find("\"keep_literals\"");
    if (pos != string::npos) {
      pos = line.find("[", pos);
      if (pos != string::npos) {
        size_t end = line.find("]", pos);
        string arr = line.substr(pos + 1, end - pos - 1);
        size_t start = 0;
        while (true) {
          start = arr.find("\"", start);
          if (start == string::npos) break;
          size_t e = arr.find("\"", start + 1);
          if (e == string::npos) break;
          cand.keep_literals.push_back(arr.substr(start + 1, e - start - 1));
          start = e + 1;
        }
      }
    }

    // parse drop_literals array
    pos = line.find("\"drop_literals\"");
    if (pos != string::npos) {
      pos = line.find("[", pos);
      if (pos != string::npos) {
        size_t end = line.find("]", pos);
        string arr = line.substr(pos + 1, end - pos - 1);
        size_t start = 0;
        while (true) {
          start = arr.find("\"", start);
          if (start == string::npos) break;
          size_t e = arr.find("\"", start + 1);
          if (e == string::npos) break;
          cand.drop_literals.push_back(arr.substr(start + 1, e - start - 1));
          start = e + 1;
        }
      }
    }

    // parse formula (for qf-smt mode)
    pos = line.find("\"formula\"");
    if (pos != string::npos) {
      pos = line.find("\"", pos + 9);
      if (pos != string::npos) {
        size_t end = line.find("\"", pos + 1);
        cand.formula = line.substr(pos + 1, end - pos - 1);
      }
    }

    // parse used_symbols array
    pos = line.find("\"used_symbols\"");
    if (pos != string::npos) {
      pos = line.find("[", pos);
      if (pos != string::npos) {
        size_t end = line.find("]", pos);
        string arr = line.substr(pos + 1, end - pos - 1);
        size_t start = 0;
        while (true) {
          start = arr.find("\"", start);
          if (start == string::npos) break;
          size_t e = arr.find("\"", start + 1);
          if (e == string::npos) break;
          cand.used_symbols.push_back(arr.substr(start + 1, e - start - 1));
          start = e + 1;
        }
      }
    }

    // parse rationale
    pos = line.find("\"rationale\"");
    if (pos != string::npos) {
      pos = line.find("\"", pos + 11);
      if (pos != string::npos) {
        size_t end = line.find("\"", pos + 1);
        cand.rationale = line.substr(pos + 1, end - pos - 1);
      }
    }

    candidates.push_back(cand);
    } catch (const std::exception & e) {
      logger.log(1,
                 "LLMGeneralizer: error parsing candidate: {}",
                 e.what());
    } catch (...) {
      logger.log(1, "LLMGeneralizer: unknown error parsing candidate");
    }
  }

  last_response_pos_ = fin.tellg();
  fin.close();

  stats_.num_candidates += candidates.size();
  if (!candidates.empty()) {
    logger.log(1,
               "LLMGeneralizer: polled {} candidate(s)",
               candidates.size());
  }

  return candidates;
}

void LLMGeneralizer::log_stats() const
{
  logger.log(0, "=== LLM Generalization Statistics ===");
  logger.log(0, "  Requests sent:       {}", stats_.num_requests);
  logger.log(0, "  Candidates received: {}", stats_.num_candidates);
  logger.log(0, "  Accepted:            {}", stats_.num_accepted);
  logger.log(0, "  Schema failures:     {}", stats_.num_schema_fail);
  logger.log(0, "  Parse failures:      {}", stats_.num_parse_fail);
  logger.log(0, "  Vocabulary failures: {}", stats_.num_vocab_fail);
  logger.log(0, "  Induction failures:  {}", stats_.num_induction_fail);
  logger.log(0, "  Subsumption failures:{}", stats_.num_subsumption_fail);
  logger.log(0, "  Budget skips:        {}", stats_.num_budget_skip);
  logger.log(0, "  Total tokens:        {}", stats_.total_tokens);
  logger.log(0, "  Accepted budget:     {}", stats_.accepted_budget);
  logger.log(0,
             "LLM_STATS accepted={} rejected={} errors={} "
             "requests={} candidates={} "
             "schema_fail={} parse_fail={} vocab_fail={} "
             "induction_fail={} subsumption_fail={} budget_skip={}",
             stats_.num_accepted,
             stats_.num_schema_fail + stats_.num_parse_fail
                 + stats_.num_vocab_fail + stats_.num_induction_fail
                 + stats_.num_subsumption_fail + stats_.num_budget_skip,
             stats_.num_schema_fail + stats_.num_parse_fail
                 + stats_.num_vocab_fail,
             stats_.num_requests,
             stats_.num_candidates,
             stats_.num_schema_fail,
             stats_.num_parse_fail,
             stats_.num_vocab_fail,
             stats_.num_induction_fail,
             stats_.num_subsumption_fail,
             stats_.num_budget_skip);
}

void LLMGeneralizer::store_last_cti_cube(const TermVec & cube_children)
{
  last_cti_cube_ = cube_children;
  stored_cti_cubes_.push_back(cube_children);
  if (stored_cti_cubes_.size() > kMaxStoredCubes) {
    stored_cti_cubes_.pop_front();
  }
}

TermVec LLMGeneralizer::pop_next_cti_cube()
{
  if (!stored_cti_cubes_.empty()) {
    TermVec cube = stored_cti_cubes_.front();
    stored_cti_cubes_.pop_front();
    return cube;
  }
  return last_cti_cube_;
}

}  // namespace pono
