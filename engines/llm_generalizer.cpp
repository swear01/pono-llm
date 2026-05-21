/*********************                                                  */
/*! \file llm_generalizer.cpp
** \brief LLM-guided lemma generalization for IC3/IC3-IA
**/

#include "engines/llm_generalizer.h"

#include <cassert>
#include <fstream>
#include <sstream>
#include <stdexcept>

#include "utils/logger.h"

using namespace smt;
using namespace std;

namespace pono {

LLMGeneralizer::LLMGeneralizer(PonoOptions opts, const SmtSolver & solver)
    : opts_(opts),
      solver_(solver),
      last_response_pos_(0)
{
  request_path_ = opts_.llm_request_path_.empty()
                      ? "/tmp/pono_llm_requests.jsonl"
                      : opts_.llm_request_path_;
  response_path_ = opts_.llm_response_path_.empty()
                       ? "/tmp/pono_llm_responses.jsonl"
                       : opts_.llm_response_path_;
  log_path_ = opts_.llm_log_path_.empty() ? "/tmp/pono_llm_log.jsonl"
                                          : opts_.llm_log_path_;
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
}

}  // namespace pono
