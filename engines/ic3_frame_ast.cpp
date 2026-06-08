/*********************                                                  */
/*! \file ic3_frame_ast.cpp
**/

#include "engines/ic3_frame_ast.h"

#include <cctype>
#include <stdexcept>

using namespace smt;
using namespace std;

namespace pono {

namespace {

static string parse_string_field(const string & line, const string & field)
{
  size_t pos = line.find("\"" + field + "\"");
  if (pos == string::npos) return "";
  pos = line.find(":", pos);
  if (pos == string::npos) return "";
  pos = line.find("\"", pos);
  if (pos == string::npos) return "";
  size_t end = line.find("\"", pos + 1);
  if (end == string::npos) return "";
  return line.substr(pos + 1, end - pos - 1);
}

static size_t find_matching_brace(const string & line, size_t open_pos)
{
  int depth = 0;
  bool in_string = false;
  for (size_t i = open_pos; i < line.size(); ++i) {
    if (line[i] == '"') {
      in_string = !in_string;
    } else if (!in_string) {
      if (line[i] == '{') depth++;
      else if (line[i] == '}') {
        depth--;
        if (depth == 0) return i;
      }
    }
  }
  return string::npos;
}

static size_t find_matching_bracket(const string & line, size_t open_pos)
{
  int depth = 0;
  bool in_string = false;
  for (size_t i = open_pos; i < line.size(); ++i) {
    if (line[i] == '"') {
      in_string = !in_string;
    } else if (!in_string) {
      if (line[i] == '[') depth++;
      else if (line[i] == ']') {
        depth--;
        if (depth == 0) return i;
      }
    }
  }
  return string::npos;
}

static bool parse_bool_field(const string & obj, const string & field, bool def)
{
  size_t pos = obj.find("\"" + field + "\"");
  if (pos == string::npos) return def;
  pos = obj.find(":", pos);
  if (pos == string::npos) return def;
  string tail = obj.substr(pos + 1);
  if (tail.find("true") != string::npos) return true;
  if (tail.find("false") != string::npos) return false;
  return def;
}

/** JSON number field (e.g. "sample_id": 1). Do not use parse_string_field. */
static size_t parse_uint_field(const string & line,
                               const string & field,
                               size_t def = 0)
{
  size_t pos = line.find("\"" + field + "\"");
  if (pos == string::npos) return def;
  pos = line.find(":", pos);
  if (pos == string::npos) return def;
  try {
    return stoul(line.substr(pos + 1));
  } catch (...) {
    return def;
  }
}

static size_t parse_size_field(const string & obj, const string & field, size_t def)
{
  size_t pos = obj.find("\"" + field + "\"");
  if (pos == string::npos) return def;
  pos = obj.find(":", pos);
  if (pos == string::npos) return def;
  try {
    return stoul(obj.substr(pos + 1));
  } catch (...) {
    return def;
  }
}

static vector<IC3FrameDisjunct> parse_disjunct_array(const string & arr_content)
{
  vector<IC3FrameDisjunct> out;
  size_t pos = 0;
  while (pos < arr_content.size()) {
    size_t obj_start = arr_content.find("{", pos);
    if (obj_start == string::npos) break;
    size_t obj_end = find_matching_brace(arr_content, obj_start);
    if (obj_end == string::npos) break;
    string obj = arr_content.substr(obj_start, obj_end - obj_start + 1);
    IC3FrameDisjunct d;
    d.ref = parse_string_field(obj, "ref");
    if (d.ref.empty()) {
      size_t atom_pos = obj.find("\"atom\"");
      if (atom_pos != string::npos) {
        d.ref = parse_string_field(obj.substr(atom_pos), "ref");
      }
    }
    d.op = parse_string_field(obj, "op");
    if (d.op.empty()) d.op = "eq";
    d.rhs = parse_string_field(obj, "rhs");
    d.polarity = parse_bool_field(obj, "polarity", true);
    if (!d.ref.empty() && !d.rhs.empty()) out.push_back(d);
    pos = obj_end + 1;
  }
  return out;
}

static IC3FramePredicateNode parse_predicate_node(const string & obj);

static vector<IC3FramePredicateNode> parse_predicate_args(const string & obj)
{
  vector<IC3FramePredicateNode> args;
  size_t pos = obj.find("\"args\"");
  if (pos == string::npos) return args;
  pos = obj.find("[", pos);
  if (pos == string::npos) return args;
  size_t end = find_matching_bracket(obj, pos);
  if (end == string::npos) return args;
  string arr = obj.substr(pos + 1, end - pos - 1);
  size_t cur = 0;
  while (cur < arr.size()) {
    size_t obj_start = arr.find("{", cur);
    if (obj_start == string::npos) break;
    size_t obj_end = find_matching_brace(arr, obj_start);
    if (obj_end == string::npos) break;
    IC3FramePredicateNode child =
        parse_predicate_node(arr.substr(obj_start, obj_end - obj_start + 1));
    if (child.valid) args.push_back(child);
    cur = obj_end + 1;
  }
  return args;
}

static IC3FramePredicateNode parse_predicate_node(const string & obj)
{
  IC3FramePredicateNode node;
  node.form = parse_string_field(obj, "form");
  if (node.form.empty()) {
    if (!obj.empty() && obj.find("\"ref\"") != string::npos) {
      node.form = "ref";
    } else if (!obj.empty() && obj.find("\"const\"") != string::npos) {
      node.form = "const";
    }
  }
  if (node.form.empty()) return node;

  node.ref = parse_string_field(obj, "ref");
  node.const_val = parse_string_field(obj, "const");
  node.width = parse_size_field(obj, "width", 0);
  node.extract_hi = static_cast<int>(parse_size_field(obj, "hi", 0));
  node.extract_lo = static_cast<int>(parse_size_field(obj, "lo", 0));
  node.args = parse_predicate_args(obj);
  node.valid = true;
  return node;
}

static bool parse_predicate_field(const string & line,
                                const string & field,
                                IC3FramePredicateNode & out)
{
  size_t pos = line.find("\"" + field + "\"");
  if (pos == string::npos) return false;
  pos = line.find("{", pos);
  if (pos == string::npos) return false;
  size_t end = find_matching_brace(line, pos);
  if (end == string::npos) return false;
  out = parse_predicate_node(line.substr(pos, end - pos + 1));
  return out.valid;
}

static bool parse_actions_predicate(const string & line, IC3FramePredicateNode & out)
{
  size_t pos = line.find("\"actions\"");
  if (pos == string::npos) return false;
  pos = line.find("[", pos);
  if (pos == string::npos) return false;
  size_t end = find_matching_bracket(line, pos);
  if (end == string::npos) return false;
  string actions = line.substr(pos + 1, end - pos - 1);
  size_t pred_pos = actions.find("\"kind\":\"refine_predicate\"");
  if (pred_pos == string::npos) {
    pred_pos = actions.find("\"kind\": \"refine_predicate\"");
  }
  if (pred_pos == string::npos) return false;
  size_t obj_start = actions.rfind("{", pred_pos);
  if (obj_start == string::npos) return false;
  size_t obj_end = find_matching_brace(actions, obj_start);
  if (obj_end == string::npos) return false;
  string action_obj = actions.substr(obj_start, obj_end - obj_start + 1);
  size_t ppos = action_obj.find("\"predicate\"");
  if (ppos == string::npos) return false;
  ppos = action_obj.find("{", ppos);
  if (ppos == string::npos) return false;
  size_t pend = find_matching_brace(action_obj, ppos);
  if (pend == string::npos) return false;
  out = parse_predicate_node(action_obj.substr(ppos, pend - ppos + 1));
  return out.valid;
}

static vector<IC3FrameDisjunct> parse_action_block_disjuncts(
    const string & action_obj)
{
  size_t disj_pos = action_obj.find("\"disjuncts\"");
  if (disj_pos == string::npos) {
    disj_pos = action_obj.find("\"clause\"");
    if (disj_pos != string::npos) {
      disj_pos = action_obj.find("\"disjuncts\"", disj_pos);
    }
  }
  if (disj_pos == string::npos) return {};
  disj_pos = action_obj.find("[", disj_pos);
  if (disj_pos == string::npos) return {};
  size_t disj_end = find_matching_bracket(action_obj, disj_pos);
  if (disj_end == string::npos) return {};
  return parse_disjunct_array(
      action_obj.substr(disj_pos + 1, disj_end - disj_pos - 1));
}

static vector<vector<IC3FrameDisjunct>> parse_all_actions_blocks(
    const string & line)
{
  vector<vector<IC3FrameDisjunct>> out;
  size_t pos = line.find("\"actions\"");
  if (pos == string::npos) return out;
  pos = line.find("[", pos);
  if (pos == string::npos) return out;
  size_t end = find_matching_bracket(line, pos);
  if (end == string::npos) return out;

  string actions = line.substr(pos + 1, end - pos - 1);
  size_t search = 0;
  while (search < actions.size()) {
    size_t block_pos = actions.find("\"kind\":\"block\"", search);
    if (block_pos == string::npos) {
      block_pos = actions.find("\"kind\": \"block\"", search);
    }
    if (block_pos == string::npos) break;

    size_t obj_start = actions.rfind("{", block_pos);
    if (obj_start == string::npos || obj_start < search) break;
    size_t obj_end = find_matching_brace(actions, obj_start);
    if (obj_end == string::npos) break;

    string action_obj = actions.substr(obj_start, obj_end - obj_start + 1);
    auto disjuncts = parse_action_block_disjuncts(action_obj);
    if (!disjuncts.empty()) out.push_back(disjuncts);
    search = obj_end + 1;
  }
  return out;
}

static vector<IC3FrameDisjunct> parse_actions_block(const string & line)
{
  auto all = parse_all_actions_blocks(line);
  if (all.empty()) return {};
  return all.front();
}

static vector<vector<IC3FrameDisjunct>> parse_block_clauses_field(
    const string & line)
{
  vector<vector<IC3FrameDisjunct>> out;
  size_t pos = line.find("\"block_clauses\"");
  if (pos == string::npos) return out;
  pos = line.find("[", pos);
  if (pos == string::npos) return out;
  size_t end = find_matching_bracket(line, pos);
  if (end == string::npos) return out;

  string outer = line.substr(pos + 1, end - pos - 1);
  size_t cur = 0;
  while (cur < outer.size()) {
    while (cur < outer.size() && (outer[cur] == ',' || isspace(outer[cur]))) {
      cur++;
    }
    if (cur >= outer.size()) break;

    if (outer[cur] == '[') {
      size_t inner_end = find_matching_bracket(outer, cur);
      if (inner_end == string::npos) break;
      auto disjuncts = parse_disjunct_array(outer.substr(cur + 1, inner_end - cur - 1));
      if (!disjuncts.empty()) out.push_back(disjuncts);
      cur = inner_end + 1;
      continue;
    }

    if (outer[cur] == '{') {
      size_t obj_end = find_matching_brace(outer, cur);
      if (obj_end == string::npos) break;
      auto disjuncts =
          parse_disjunct_array(outer.substr(cur, obj_end - cur + 1));
      if (!disjuncts.empty()) out.push_back(disjuncts);
      cur = obj_end + 1;
      continue;
    }

    break;
  }
  return out;
}

static Term build_node_term(const SmtSolver & solver,
                            const TransitionSystem & ts,
                            const IC3FramePredicateNode & node);

static Term build_compare(const SmtSolver & solver,
                          const TransitionSystem & ts,
                          PrimOp op,
                          const IC3FramePredicateNode & node)
{
  if (node.args.size() != 2) throw runtime_error("compare needs 2 args");
  Term lhs = build_node_term(solver, ts, node.args[0]);
  Term rhs = build_node_term(solver, ts, node.args[1]);
  return solver->make_term(op, lhs, rhs);
}

static Term parse_const_term(const SmtSolver & solver,
                             const IC3FramePredicateNode & node)
{
  if (node.width == 0) {
    if (node.const_val == "true" || node.const_val == "1") {
      return solver->make_term(true);
    }
    if (node.const_val == "false" || node.const_val == "0") {
      return solver->make_term(false);
    }
    throw runtime_error("invalid bool const");
  }
  Sort sort = solver->make_sort(BV, node.width);
  string s = node.const_val;
  if (s.rfind("#b", 0) == 0) {
    return solver->make_term(s.substr(2), sort);
  }
  if (s.rfind("#x", 0) == 0) {
    return solver->make_term(s.substr(2), sort, 16);
  }
  return solver->make_term(stoul(s, nullptr, 10), sort);
}

static Term build_node_term(const SmtSolver & solver,
                            const TransitionSystem & ts,
                            const IC3FramePredicateNode & node)
{
  if (!node.valid) throw runtime_error("invalid predicate node");

  if (node.form == "ref") {
    return ts.lookup(node.ref);
  }
  if (node.form == "const") {
    return parse_const_term(solver, node);
  }
  if (node.form == "eq") return build_compare(solver, ts, Equal, node);
  if (node.form == "ne") return build_compare(solver, ts, Distinct, node);
  if (node.form == "ult") return build_compare(solver, ts, BVUlt, node);
  if (node.form == "ule") return build_compare(solver, ts, BVUle, node);
  if (node.form == "ugt") return build_compare(solver, ts, BVUgt, node);
  if (node.form == "uge") return build_compare(solver, ts, BVUge, node);
  if (node.form == "slt") return build_compare(solver, ts, BVSlt, node);
  if (node.form == "sle") return build_compare(solver, ts, BVSle, node);
  if (node.form == "sgt") return build_compare(solver, ts, BVSgt, node);
  if (node.form == "sge") return build_compare(solver, ts, BVSge, node);

  if (node.form == "not") {
    if (node.args.size() != 1) throw runtime_error("not needs 1 arg");
    return solver->make_term(Not, build_node_term(solver, ts, node.args[0]));
  }
  if (node.form == "implies") {
    if (node.args.size() != 2) throw runtime_error("implies needs 2 args");
    Term ant = build_node_term(solver, ts, node.args[0]);
    Term cons = build_node_term(solver, ts, node.args[1]);
    return solver->make_term(Implies, ant, cons);
  }

  if (node.form == "and" || node.form == "or") {
    if (node.args.empty()) throw runtime_error("and/or needs args");
    TermVec children;
    for (const auto & arg : node.args) {
      children.push_back(build_node_term(solver, ts, arg));
    }
    PrimOp op = (node.form == "and") ? And : Or;
    return solver->make_term(op, children);
  }

  if (node.form == "bvand" || node.form == "bvor" || node.form == "bvxor") {
    if (node.args.size() != 2) throw runtime_error("bv op needs 2 args");
    PrimOp op = BVAnd;
    if (node.form == "bvor") op = BVOr;
    if (node.form == "bvxor") op = BVXor;
    Term lhs = build_node_term(solver, ts, node.args[0]);
    Term rhs = build_node_term(solver, ts, node.args[1]);
    return solver->make_term(op, lhs, rhs);
  }
  if (node.form == "bvnot") {
    if (node.args.size() != 1) throw runtime_error("bvnot needs 1 arg");
    return solver->make_term(BVNot, build_node_term(solver, ts, node.args[0]));
  }
  if (node.form == "concat") {
    if (node.args.size() < 2) throw runtime_error("concat needs 2+ args");
    TermVec children;
    for (const auto & arg : node.args) {
      children.push_back(build_node_term(solver, ts, arg));
    }
    return solver->make_term(Concat, children);
  }
  if (node.form == "extract") {
    if (node.args.size() != 1) throw runtime_error("extract needs 1 arg");
    Term arg = build_node_term(solver, ts, node.args[0]);
    return solver->make_term(Op(Extract, node.extract_hi, node.extract_lo), arg);
  }

  throw runtime_error("unsupported predicate form: " + node.form);
}

Term build_predicate_term_impl(const SmtSolver & solver,
                               const TransitionSystem & ts,
                               const IC3FramePredicateNode & node)
{
  if (!node.valid) return Term();
  try {
    return build_node_term(solver, ts, node);
  } catch (...) {
    return Term();
  }
}

}  // namespace

void collect_predicate_refs(const IC3FramePredicateNode & node,
                            vector<string> & refs)
{
  if (node.form == "ref" && !node.ref.empty()) {
    refs.push_back(node.ref);
  }
  for (const auto & arg : node.args) {
    collect_predicate_refs(arg, refs);
  }
}

Term build_predicate_term(const SmtSolver & solver,
                          const TransitionSystem & ts,
                          const IC3FramePredicateNode & node)
{
  return build_predicate_term_impl(solver, ts, node);
}

IC3FrameResponse parse_ic3_frame_response_line(const string & line)
{
  IC3FrameResponse res;
  if (line.empty() || line[0] != '{') {
    res.error_msg = "not a JSON object";
    return res;
  }

  string type = parse_string_field(line, "type");
  if (type != "ic3_frame_response") {
    res.error_msg = "type is not ic3_frame_response";
    return res;
  }

  res.source_cti_id = parse_string_field(line, "source_cti_id");
  res.sample_id = parse_uint_field(line, "sample_id", 0);

  res.rationale = parse_string_field(line, "rationale");

  res.attempt = parse_uint_field(line, "attempt", 0);

  res.block_clauses = parse_block_clauses_field(line);
  if (res.block_clauses.empty()) {
    res.block_clauses = parse_all_actions_blocks(line);
  }

  size_t pos = line.find("\"block_disjuncts\"");
  if (pos != string::npos) {
    pos = line.find("[", pos);
    if (pos != string::npos) {
      size_t end = find_matching_bracket(line, pos);
      if (end != string::npos) {
        string arr = line.substr(pos + 1, end - pos - 1);
        res.block_disjuncts = parse_disjunct_array(arr);
      }
    }
  }

  if (res.block_clauses.empty() && !res.block_disjuncts.empty()) {
    res.block_clauses.push_back(res.block_disjuncts);
  } else if (res.block_clauses.empty()) {
    res.block_disjuncts = parse_actions_block(line);
    if (!res.block_disjuncts.empty()) {
      res.block_clauses.push_back(res.block_disjuncts);
    }
  } else if (res.block_disjuncts.empty() && !res.block_clauses.empty()) {
    res.block_disjuncts = res.block_clauses.front();
  }
  res.has_block = !res.block_clauses.empty();

  if (parse_predicate_field(line, "refine_predicate", res.refine_predicate)) {
    res.has_refine_predicate = true;
  } else if (parse_actions_predicate(line, res.refine_predicate)) {
    res.has_refine_predicate = true;
  }

  pos = line.find("\"symbols_used\"");
  if (pos != string::npos) {
    pos = line.find("[", pos);
    if (pos != string::npos) {
      size_t end = find_matching_bracket(line, pos);
      if (end != string::npos) {
        string arr = line.substr(pos + 1, end - pos - 1);
        size_t start = 0;
        while (true) {
          start = arr.find("\"", start);
          if (start == string::npos) break;
          size_t e = arr.find("\"", start + 1);
          if (e == string::npos) break;
          res.symbols_used.push_back(arr.substr(start + 1, e - start - 1));
          start = e + 1;
        }
      }
    }
  }

  if (!res.has_block && !res.has_refine_predicate) {
    res.error_msg = "no block or refine_predicate action";
    return res;
  }
  if (res.source_cti_id.empty()) {
    res.error_msg = "missing source_cti_id";
    return res;
  }

  res.valid = true;
  return res;
}

}  // namespace pono
