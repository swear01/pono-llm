> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime path. See [`ic3_frame_v1_integration.md`](../ic3_frame_v1_integration.md).

# Offline LLM Repair Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline replay experiment path where LLM-generated IC3/PDR cube proposals and LLM witness repairs are checked by Pono's real `rel_ind_check()` and can produce accepted lemmas.

**Architecture:** Add two offline LLM modes to Pono: `offline-dump` emits static benchmark facts plus ID-based CTI contexts, and `offline-check` replays LLM proposal/repair JSONL records against live PDR frames. A Python driver creates `proposals.jsonl`, `repairs.jsonl`, and `summary.json` from the replay directory.

**Tech Stack:** C++17 / Pono IC3Base / smt-switch / Python 3 / JSONL / DeepSeek OpenAI-compatible client

---

## File Structure

- Modify `options/options.h`: add `offline-dump`, `offline-check`, and `--llm-replay-dir` option storage.
- Modify `options/options.cpp`: parse the new modes and CLI option.
- Modify `engines/llm_generalizer.h`: extend CTI literal/context structures and add offline replay data types and methods.
- Modify `engines/llm_generalizer.cpp`: write static context, write ID-based CTI contexts, load proposals/repairs, write replay results and repair requests.
- Modify `engines/ic3base.h`: declare offline candidate checking helpers.
- Modify `engines/ic3base.cpp`: call offline dump/check hooks at CTI capture time and implement solver-backed candidate checking with witness diff extraction.
- Create `llm_worker/offline_repair_driver.py`: generate LLM proposals, generate LLM repairs, summarize results.
- Create `llm_worker/prompts/offline_proposal.txt`: JSON-only proposal prompt template.
- Create `llm_worker/prompts/offline_repair.txt`: JSON-only repair prompt template.
- Create `tests/test_offline_repair_driver.py`: Python unit tests for parsing, validation, and summary.
- Modify `docs/ARCHITECTURE.md`: document the offline replay workflow.

---

### Task 1: Add offline replay CLI modes and replay directory option

**Files:**
- Modify: `options/options.h`
- Modify: `options/options.cpp`

- [ ] **Step 1: Extend the LLM mode enum**

Edit `options/options.h` near the existing `enum LLMGenMode` and replace it with:

```cpp
// LLM generation mode option
enum LLMGenMode
{
  LLM_GEN_NONE = 0,
  LLM_GEN_SEED_ONLY,
  LLM_GEN_ASYNC_CTI,
  LLM_GEN_OFFLINE_DUMP,
  LLM_GEN_OFFLINE_CHECK
};
```

- [ ] **Step 2: Add string mappings**

Edit `options/options.h` in `str2llmgenmode` and use:

```cpp
const std::unordered_map<std::string, LLMGenMode> str2llmgenmode({
    { "none", LLM_GEN_NONE },
    { "seed-only", LLM_GEN_SEED_ONLY },
    { "async-cti", LLM_GEN_ASYNC_CTI },
    { "offline-dump", LLM_GEN_OFFLINE_DUMP },
    { "offline-check", LLM_GEN_OFFLINE_CHECK },
});
```

- [ ] **Step 3: Add replay directory storage**

Edit `options/options.h` near existing LLM option fields:

```cpp
  std::string llm_request_path_;   // JSONL request output path
  std::string llm_response_path_;  // JSONL response poll path
  std::string llm_replay_dir_;     // directory for offline replay artifacts
```

Edit the default option block:

```cpp
  inline static const std::string default_llm_response_path_;
  inline static const std::string default_llm_replay_dir_;
```

- [ ] **Step 4: Add option enum value**

Edit `options/options.cpp` near the option enum values:

```cpp
  LLM_LOG_PATH,
  LLM_REQUEST_PATH,
  LLM_RESPONSE_PATH,
  LLM_REPLAY_DIR,
};
```

- [ ] **Step 5: Add CLI help entry**

Edit `options/options.cpp` after the `LLM_RESPONSE_PATH` help entry and keep the sentinel last:

```cpp
  { LLM_REPLAY_DIR,
    0,
    "",
    "llm-replay-dir",
    Arg::NonEmpty,
    "  --llm-replay-dir \tDirectory for offline LLM replay artifacts" },
  { 0, 0, 0, 0, 0, 0 }
```

Also update the `--llm-gen-mode` help string to include the new modes:

```cpp
"  --llm-gen-mode \tLLM generalization mode: none (default), seed-only, "
"async-cti, offline-dump, offline-check"
```

- [ ] **Step 6: Parse the replay directory option**

Edit the main option switch in `options/options.cpp` after `LLM_RESPONSE_PATH`:

```cpp
        case LLM_RESPONSE_PATH: llm_response_path_ = opt.arg; break;
        case LLM_REPLAY_DIR: llm_replay_dir_ = opt.arg; break;
```

- [ ] **Step 7: Build and smoke-test CLI parsing**

Run:

```bash
make -j$(nproc) -C build
build/pono --help | grep -E "llm-gen-mode|llm-replay-dir"
```

Expected:

```text
--llm-gen-mode
--llm-replay-dir
```

- [ ] **Step 8: Commit**

```bash
git add options/options.h options/options.cpp
git commit -m "Add offline LLM replay CLI options"
```

---

### Task 2: Extend LLMGeneralizer data model for ID-based offline replay

**Files:**
- Modify: `engines/llm_generalizer.h`
- Modify: `engines/llm_generalizer.cpp`

- [ ] **Step 1: Extend CTI structs**

Edit `engines/llm_generalizer.h` and update `CTILiteral`:

```cpp
struct CTILiteral
{
  size_t id;
  std::string varname;
  std::string expr;
  std::string value;
  std::string kind;
  std::vector<std::string> signals;
  smt::Term term;
};
```

Update `CTIContext`:

```cpp
struct CTIContext
{
  std::string cti_id;
  size_t frame_idx;
  std::vector<CTILiteral> literals;
  std::string property_name;
  std::vector<CTILiteral> frame_lemmas;
};
```

- [ ] **Step 2: Add offline record structs**

Add these structs after `LLMCandidate`:

```cpp
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
```

- [ ] **Step 3: Add offline method declarations**

Add to `class LLMGeneralizer` public methods:

```cpp
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
```

Add private fields:

```cpp
  std::string replay_dir_;
  bool offline_records_loaded_;
  std::unordered_map<std::string, LLMIdCandidate> proposals_;
  std::unordered_map<std::string, LLMIdCandidate> repairs_;
```

Add `#include <unordered_map>` to the header if it is not already present.

- [ ] **Step 4: Initialize replay fields**

Edit `LLMGeneralizer::LLMGeneralizer` in `engines/llm_generalizer.cpp`:

```cpp
  replay_dir_ = opts_.llm_replay_dir_.empty() ? "llm_replay/default"
                                              : opts_.llm_replay_dir_;
  offline_records_loaded_ = false;
```

- [ ] **Step 5: Add mode helpers**

Add to `engines/llm_generalizer.cpp` after existing mode helpers:

```cpp
bool LLMGeneralizer::is_offline_dump() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_OFFLINE_DUMP;
}

bool LLMGeneralizer::is_offline_check() const
{
  return opts_.llm_gen_mode_ == LLM_GEN_OFFLINE_CHECK;
}
```

- [ ] **Step 6: Add JSON array parser for numeric IDs**

Add a private file-local helper near the top of `engines/llm_generalizer.cpp`:

```cpp
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
    out.push_back(static_cast<size_t>(std::stoul(item.substr(first, last - first + 1))));
  }
  return out;
}
```

- [ ] **Step 7: Add JSON string parser helper**

Add near the numeric parser:

```cpp
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
```

- [ ] **Step 8: Implement stable CTI IDs**

Add:

```cpp
std::string LLMGeneralizer::make_cti_id(
    size_t frame_idx, const std::vector<CTILiteral> & literals) const
{
  std::string raw = "frame" + std::to_string(frame_idx) + ":";
  for (const auto & lit : literals) {
    raw += std::to_string(lit.id) + "=" + lit.varname + "=" + lit.value + ";";
  }
  std::hash<std::string> hasher;
  std::ostringstream out;
  out << "frame" << frame_idx << ":" << std::hex << hasher(raw);
  return out.str();
}
```

- [ ] **Step 9: Implement offline record loading**

Add:

```cpp
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
      cand.drop_ids = parse_size_array_field(line, "drop_ids");
      cand.add_back_ids = parse_size_array_field(line, "add_back_ids");
      if (!cand.cti_id.empty()) dst[cand.cti_id] = cand;
    }
  };

  load_file(replay_dir_ + "/proposals.jsonl", proposals_);
  load_file(replay_dir_ + "/repairs.jsonl", repairs_);
}
```

- [ ] **Step 10: Implement proposal/repair lookup**

Add:

```cpp
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
```

- [ ] **Step 11: Build**

```bash
make -j$(nproc) -C build
```

Expected final lines include:

```text
Built target pono-bin
```

- [ ] **Step 12: Commit**

```bash
git add engines/llm_generalizer.h engines/llm_generalizer.cpp
git commit -m "Add offline LLM replay data model"
```

---

### Task 3: Emit static benchmark context and ID-based CTI contexts

**Files:**
- Modify: `engines/llm_generalizer.cpp`
- Modify: `engines/ic3base.cpp`
- Modify: `engines/ic3base.h`

- [ ] **Step 1: Add directory creation helper**

Add to `engines/llm_generalizer.cpp` includes:

```cpp
#include <sys/stat.h>
#include <sys/types.h>
```

Add helper:

```cpp
static void ensure_dir_exists(const std::string & path)
{
  if (path.empty()) return;
  mkdir(path.c_str(), 0775);
}
```

- [ ] **Step 2: Implement `write_offline_cti_context`**

Add to `engines/llm_generalizer.cpp`:

```cpp
void LLMGeneralizer::write_offline_cti_context(const CTIContext & ctx)
{
  ensure_dir_exists(replay_dir_);
  std::ofstream fout(replay_dir_ + "/cti_contexts.jsonl", std::ios::app);
  if (!fout.is_open()) {
    logger.log(0, "LLMGeneralizer: cannot write offline CTI contexts in {}", replay_dir_);
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
```

- [ ] **Step 3: Implement static context writer**

Add to `engines/llm_generalizer.cpp`:

```cpp
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
    logger.log(0, "LLMGeneralizer: cannot write static context in {}", replay_dir_);
    return;
  }

  fout << "{\n";
  fout << "  \"schema_version\": 1,\n";
  fout << "  \"benchmark\": \"" << escape_json(benchmark_name) << "\",\n";
  fout << "  \"property\": {\"bad_expr\": \"" << escape_json(bad_expr) << "\"},\n";

  auto emit_lits = [&](const char * name, const std::vector<CTILiteral> & vars) {
    fout << "  \"" << name << "\": [";
    for (size_t i = 0; i < vars.size(); ++i) {
      if (i) fout << ",";
      fout << "{\"name\":\"" << escape_json(vars[i].varname) << "\",\"width\":1}";
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
  fout << "  \"notes\": [\"All LLM candidates are checked on the full transition system.\"]\n";
  fout << "}\n";
}
```

- [ ] **Step 4: Assign IDs and kinds in `collect_cti_literals`**

Edit `IC3Base::collect_cti_literals` in `engines/ic3base.cpp` so each literal gets an ID and expression:

```cpp
  for (const auto & child : cube.children) {
    CTILiteral lit;
    lit.id = lits.size();
    lit.term = child;
    if (child->get_op() == smt::Not) {
      smt::Term inner = *(child->begin());
      lit.varname = simplify_cti_literal(inner);
      lit.expr = lit.varname + " = false";
      lit.value = "false";
    } else {
      lit.varname = simplify_cti_literal(child);
      lit.expr = lit.varname + " = true";
      lit.value = "true";
    }
    if (lit.varname.size() > 200) {
      lit.varname = lit.varname.substr(0, 197) + "...";
    }
    lit.kind = "unknown";
    lit.signals.push_back(lit.varname);
    lits.push_back(lit);
  }
```

- [ ] **Step 5: Add static context export helper declaration**

Add to `engines/ic3base.h` private helper section:

```cpp
  void write_llm_static_context_once();
  bool llm_static_context_written_ = false;
```

- [ ] **Step 6: Implement static context export helper**

Add to `engines/ic3base.cpp` before `capture_cti_context`:

```cpp
void IC3Base::write_llm_static_context_once()
{
  if (!llm_gen_ || llm_static_context_written_) return;
  if (!llm_gen_->is_offline_dump() && !llm_gen_->is_offline_check()) return;

  std::vector<CTILiteral> states;
  std::vector<CTILiteral> inputs;
  for (const auto & sv : ts_.statevars()) {
    CTILiteral lit;
    lit.id = states.size();
    lit.varname = simplify_cti_literal(sv);
    lit.expr = lit.varname;
    lit.value = "";
    lit.kind = "state";
    lit.signals.push_back(lit.varname);
    lit.term = sv;
    states.push_back(lit);
  }
  for (const auto & iv : ts_.inputvars()) {
    CTILiteral lit;
    lit.id = inputs.size();
    lit.varname = simplify_cti_literal(iv);
    lit.expr = lit.varname;
    lit.value = "";
    lit.kind = "input";
    lit.signals.push_back(lit.varname);
    lit.term = iv;
    inputs.push_back(lit);
  }

  std::vector<std::string> updates;
  for (const auto & kv : ts_.state_updates()) {
    updates.push_back(simplify_cti_literal(kv.first) + "' = " + simplify_cti_literal(kv.second));
    if (updates.size() >= 200) break;
  }

  std::string bad_expr = simplify_cti_literal(bad_);
  llm_gen_->write_static_context("pono-benchmark", bad_expr, states, inputs, updates);
  llm_static_context_written_ = true;
}
```

- [ ] **Step 7: Route CTI capture through offline modes**

Edit `IC3Base::capture_cti_context`:

```cpp
void IC3Base::capture_cti_context(size_t frame_idx, const IC3Formula & cube)
{
  if (!llm_gen_) return;
  if (!llm_gen_->is_async_cti()
      && !llm_gen_->is_offline_dump()
      && !llm_gen_->is_offline_check()) {
    return;
  }

  write_llm_static_context_once();

  CTIContext ctx;
  ctx.frame_idx = frame_idx;
  std::string raw_prop = simplify_cti_literal(bad_);
  ctx.property_name = raw_prop.size() > 200 ? raw_prop.substr(0, 197) + "..." : raw_prop;
  ctx.literals = collect_cti_literals(cube);
  ctx.cti_id = llm_gen_->make_cti_id(frame_idx, ctx.literals);

  llm_gen_->store_last_cti_cube(cube.children);

  if (llm_gen_->is_async_cti()) {
    llm_gen_->write_cti_context(ctx);
  } else if (llm_gen_->is_offline_dump()) {
    llm_gen_->write_offline_cti_context(ctx);
  } else if (llm_gen_->is_offline_check()) {
    llm_gen_->write_offline_cti_context(ctx);
    process_offline_llm_for_cti(ctx, cube);
  }
}
```

- [ ] **Step 8: Add temporary offline hook stub**

Add declaration in `engines/ic3base.h`:

```cpp
  void process_offline_llm_for_cti(const CTIContext & ctx,
                                   const IC3Formula & cube);
```

Add no-op implementation in `engines/ic3base.cpp`:

```cpp
void IC3Base::process_offline_llm_for_cti(const CTIContext & ctx,
                                          const IC3Formula & cube)
{
  (void)ctx;
  (void)cube;
}
```

- [ ] **Step 9: Build and smoke-test offline dump**

Run:

```bash
rm -rf /tmp/pono_replay_smoke
build/pono -e ic3ia --llm-gen-mode offline-dump --llm-replay-dir /tmp/pono_replay_smoke samples/counter.btor2 || true
find /tmp/pono_replay_smoke -maxdepth 1 -type f -print | sort
```

Expected if the sample reaches a CTI:

```text
/tmp/pono_replay_smoke/cti_contexts.jsonl
/tmp/pono_replay_smoke/static_context.json
```

If `samples/counter.btor2` is solved before a CTI is captured, repeat the command with the current HWMCC benchmark used in previous experiments.

- [ ] **Step 10: Commit**

```bash
git add engines/llm_generalizer.cpp engines/llm_generalizer.h engines/ic3base.cpp engines/ic3base.h
git commit -m "Dump offline LLM replay contexts"
```

---

### Task 4: Implement proposal replay checking and SAT witness diff extraction

**Files:**
- Modify: `engines/ic3base.h`
- Modify: `engines/ic3base.cpp`
- Modify: `engines/llm_generalizer.cpp`

- [ ] **Step 1: Add helper declarations**

Add to `engines/ic3base.h`:

```cpp
  IC3Formula cube_from_keep_ids(const IC3Formula & cube,
                                const std::vector<size_t> & keep_ids) const;
  IC3Formula blocking_from_keep_ids(const IC3Formula & cube,
                                    const std::vector<size_t> & keep_ids) const;
  bool check_llm_candidate_with_witness(
      size_t frame_idx,
      const IC3Formula & candidate_cube,
      const CTIContext & ctx,
      const std::vector<size_t> & dropped_ids,
      std::vector<LLMWitnessDiff> & witness_diffs);
```

- [ ] **Step 2: Implement ID conversion helpers**

Add to `engines/ic3base.cpp`:

```cpp
IC3Formula IC3Base::cube_from_keep_ids(const IC3Formula & cube,
                                       const std::vector<size_t> & keep_ids) const
{
  std::set<size_t> keep(keep_ids.begin(), keep_ids.end());
  TermVec children;
  for (size_t i = 0; i < cube.children.size(); ++i) {
    if (keep.count(i)) children.push_back(cube.children[i]);
  }
  return ic3formula_conjunction(children);
}

IC3Formula IC3Base::blocking_from_keep_ids(const IC3Formula & cube,
                                           const std::vector<size_t> & keep_ids) const
{
  std::set<size_t> keep(keep_ids.begin(), keep_ids.end());
  TermVec children;
  for (size_t i = 0; i < cube.children.size(); ++i) {
    if (keep.count(i)) children.push_back(smart_not(cube.children[i]));
  }
  return ic3formula_disjunction(children);
}
```

- [ ] **Step 3: Implement solver-backed candidate check with witness diff**

Add to `engines/ic3base.cpp`:

```cpp
bool IC3Base::check_llm_candidate_with_witness(
    size_t frame_idx,
    const IC3Formula & candidate_cube,
    const CTIContext & ctx,
    const std::vector<size_t> & dropped_ids,
    std::vector<LLMWitnessDiff> & witness_diffs)
{
  witness_diffs.clear();
  assert(frame_idx > 0);
  assert(frame_idx < frames_.size());
  assert(!candidate_cube.disjunction);
  assert(!solver_context_);

  push_solver_context();
  assert_frame_labels(frame_idx - 1);
  solver_->assert_formula(solver_->make_term(Not, candidate_cube.term));
  assert_trans_label();

  assumps_.clear();
  for (const auto & cc : candidate_cube.children) {
    Term ccnext = ts_.next(cc);
    Term lbl = label(ccnext);
    if (lbl != ccnext && !is_global_label(lbl)) {
      solver_->assert_formula(solver_->make_term(Implies, lbl, ccnext));
    }
    assumps_.push_back(lbl);
  }

  Result r = check_sat_assuming(assumps_);
  if (r.is_sat()) {
    for (size_t id : dropped_ids) {
      if (id >= ctx.literals.size()) continue;
      Term lit_next = ts_.next(ctx.literals[id].term);
      Term val = solver_->get_value(lit_next);
      std::string val_s = simplify_cti_literal(val);
      if (val_s == "false" || val_s == "#b0") {
        LLMWitnessDiff diff;
        diff.literal_id = id;
        diff.cti_literal = ctx.literals[id].expr;
        diff.witness_value = simplify_cti_literal(lit_next) + " = " + val_s;
        diff.effect = "Adding this literal back excludes the SAT witness.";
        witness_diffs.push_back(diff);
      }
    }
  }

  pop_solver_context();
  assert(!solver_context_);
  assert(!r.is_unknown());
  return r.is_unsat();
}
```

- [ ] **Step 4: Implement replay result writer**

Add to `engines/llm_generalizer.cpp`:

```cpp
void LLMGeneralizer::write_replay_result(const std::string & cti_id,
                                         const std::string & status,
                                         size_t frame_idx,
                                         size_t original_size,
                                         size_t candidate_size,
                                         const std::string & reason)
{
  ensure_dir_exists(replay_dir_);
  std::ofstream fout(replay_dir_ + "/proposal_replay_results.jsonl", std::ios::app);
  if (!fout.is_open()) return;
  fout << "{\"schema_version\":1,";
  fout << "\"cti_id\":\"" << escape_json(cti_id) << "\",";
  fout << "\"status\":\"" << escape_json(status) << "\",";
  fout << "\"frame\":" << frame_idx << ",";
  fout << "\"original_size\":" << original_size << ",";
  fout << "\"candidate_size\":" << candidate_size << ",";
  fout << "\"reason\":\"" << escape_json(reason) << "\"}\n";
}
```

- [ ] **Step 5: Implement repair request writer**

Add to `engines/llm_generalizer.cpp`:

```cpp
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
    fout << "\"cti_literal\":\"" << escape_json(diffs[i].cti_literal) << "\",";
    fout << "\"witness_value\":\"" << escape_json(diffs[i].witness_value) << "\",";
    fout << "\"effect\":\"" << escape_json(diffs[i].effect) << "\"}";
  }
  fout << "]}\n";
}
```

- [ ] **Step 6: Implement offline proposal processing hook**

Replace the no-op `process_offline_llm_for_cti` in `engines/ic3base.cpp`:

```cpp
void IC3Base::process_offline_llm_for_cti(const CTIContext & ctx,
                                          const IC3Formula & cube)
{
  if (!llm_gen_ || !llm_gen_->is_offline_check()) return;
  llm_gen_->load_offline_records();

  LLMIdCandidate proposal;
  if (!llm_gen_->get_proposal(ctx.cti_id, proposal)) return;
  if (proposal.keep_ids.empty()) {
    llm_gen_->write_replay_result(ctx.cti_id, "rejected_schema", ctx.frame_idx,
                                  cube.children.size(), 0, "empty keep_ids");
    return;
  }

  IC3Formula candidate_cube = cube_from_keep_ids(cube, proposal.keep_ids);
  IC3Formula blocking = blocking_from_keep_ids(cube, proposal.keep_ids);
  if (candidate_cube.children.empty() || blocking.children.empty()) {
    llm_gen_->write_replay_result(ctx.cti_id, "rejected_schema", ctx.frame_idx,
                                  cube.children.size(), 0, "empty candidate cube");
    return;
  }

  std::vector<LLMWitnessDiff> diffs;
  bool ok = check_llm_candidate_with_witness(
      ctx.frame_idx, candidate_cube, ctx, proposal.drop_ids, diffs);
  if (ok) {
    constrain_frame(ctx.frame_idx, blocking, true);
    llm_gen_->stats_.num_accepted++;
    llm_gen_->write_replay_result(ctx.cti_id, "accepted_initial", ctx.frame_idx,
                                  cube.children.size(), candidate_cube.children.size(),
                                  proposal.short_reason);
    return;
  }

  llm_gen_->stats_.num_induction_fail++;
  llm_gen_->write_replay_result(ctx.cti_id, "sat_failed_initial", ctx.frame_idx,
                                cube.children.size(), candidate_cube.children.size(),
                                "proposal included a reachable one-step successor");
  if (!diffs.empty()) {
    llm_gen_->write_repair_request(ctx, proposal, diffs);
  }
}
```

- [ ] **Step 7: Build**

```bash
make -j$(nproc) -C build
```

Expected final lines include:

```text
Built target pono-bin
```

- [ ] **Step 8: Commit**

```bash
git add engines/ic3base.cpp engines/ic3base.h engines/llm_generalizer.cpp engines/llm_generalizer.h
git commit -m "Replay offline LLM proposals with witness diffs"
```

---

### Task 5: Add Python offline proposal/repair driver

**Files:**
- Create: `llm_worker/offline_repair_driver.py`
- Create: `llm_worker/prompts/offline_proposal.txt`
- Create: `llm_worker/prompts/offline_repair.txt`

- [ ] **Step 1: Add proposal prompt template**

Create `llm_worker/prompts/offline_proposal.txt`:

```text
You are assisting an IC3/PDR model checker.

The static circuit context below is benchmark-level heuristic context. The solver will check every proposal on the full transition system.

STATIC_CONTEXT_JSON:
{static_context}

CURRENT_CTI_JSON:
{cti_context}

Task: propose a generalized blocking cube by choosing CTI literal IDs to keep. The candidate cube g is accepted only if the solver proves F[k-1] AND T AND g' is UNSAT. You are not proving it; you are only proposing.

Guidelines:
- Keep state/control predicates near the bad property when they look semantically important.
- Drop primary input literals early unless they gate next-state updates of kept states.
- Drop low-level bit encoding details when a higher-level predicate remains.
- Use literal IDs only.
- Return JSON only.

Schema:
{"schema_version":1,"cti_id":"...","mode":"proposal","keep_ids":[0],"drop_ids":[1],"confidence":"low|medium|high","short_reason":"brief"}
```

- [ ] **Step 2: Add repair prompt template**

Create `llm_worker/prompts/offline_repair.txt`:

```text
You are repairing a failed IC3/PDR generalized cube proposal.

The previous candidate was SAT, meaning it included a legal one-step successor from F[k-1]. The SAT witness diff lists dropped CTI literals that are false in the witness; adding one or more back would exclude that witness.

STATIC_CONTEXT_JSON:
{static_context}

CURRENT_CTI_JSON:
{cti_context}

REPAIR_REQUEST_JSON:
{repair_request}

Task: choose a small set of add_back_ids from sat_witness_diff. Prefer literals that explain the transition reason, not arbitrary datapath detail. Return JSON only.

Schema:
{"schema_version":1,"cti_id":"...","mode":"repair","base_keep_ids":[0],"add_back_ids":[1],"confidence":"low|medium|high","short_reason":"brief"}
```

- [ ] **Step 3: Create driver skeleton**

Create `llm_worker/offline_repair_driver.py`:

```python
#!/usr/bin/env python3
"""Offline LLM proposal/repair driver for Pono replay experiments."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from deepseek_client import DeepSeekClient


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_template(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response does not contain a JSON object")
    return json.loads(text[start:end + 1])
```

- [ ] **Step 4: Add ID validation helpers**

Append:

```python
def literal_ids(cti: Dict[str, Any]) -> set[int]:
    return {int(lit["id"]) for lit in cti.get("literals", [])}


def normalize_proposal(row: Dict[str, Any], cti: Dict[str, Any]) -> Dict[str, Any]:
    valid = literal_ids(cti)
    keep = [int(x) for x in row.get("keep_ids", []) if int(x) in valid]
    drop = [int(x) for x in row.get("drop_ids", []) if int(x) in valid and int(x) not in keep]
    if not drop:
        drop = sorted(valid - set(keep))
    return {
        "schema_version": 1,
        "cti_id": cti["cti_id"],
        "mode": "proposal",
        "keep_ids": keep,
        "drop_ids": drop,
        "confidence": str(row.get("confidence", "low")),
        "short_reason": str(row.get("short_reason", ""))[:500],
    }


def normalize_repair(row: Dict[str, Any], req: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {int(d["literal_id"]) for d in req.get("sat_witness_diff", [])}
    add_back = [int(x) for x in row.get("add_back_ids", []) if int(x) in allowed]
    return {
        "schema_version": 1,
        "cti_id": req["cti_id"],
        "mode": "repair",
        "base_keep_ids": [int(x) for x in req.get("failed_keep_ids", [])],
        "add_back_ids": add_back,
        "confidence": str(row.get("confidence", "low")),
        "short_reason": str(row.get("short_reason", ""))[:500],
    }
```

- [ ] **Step 5: Add propose command**

Append:

```python
def cmd_propose(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    static_context = read_json(replay_dir / "static_context.json")
    ctis = read_jsonl(replay_dir / "cti_contexts.jsonl")[: args.max_ctis]
    existing = {r.get("cti_id") for r in read_jsonl(replay_dir / "proposals.jsonl")}
    template = load_template("offline_proposal.txt")
    client = DeepSeekClient(model_name=args.model or None)

    for cti in ctis:
        if cti.get("cti_id") in existing:
            continue
        prompt = template.format(
            static_context=json.dumps(static_context, ensure_ascii=False, sort_keys=True),
            cti_context=json.dumps(cti, ensure_ascii=False, sort_keys=True),
        )
        text, tokens, latency = client.call(prompt, model_name=args.model or None)
        try:
            raw = extract_json_object(text)
            row = normalize_proposal(raw, cti)
        except Exception as exc:
            row = {
                "schema_version": 1,
                "cti_id": cti["cti_id"],
                "mode": "proposal",
                "keep_ids": [],
                "drop_ids": [],
                "confidence": "low",
                "short_reason": f"invalid_json: {exc}",
            }
        row["token_count"] = tokens
        row["latency_ms"] = latency
        append_jsonl(replay_dir / "proposals.jsonl", row)
    return 0
```

- [ ] **Step 6: Add repair command**

Append:

```python
def cmd_repair(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    static_context = read_json(replay_dir / "static_context.json")
    cti_by_id = {r["cti_id"]: r for r in read_jsonl(replay_dir / "cti_contexts.jsonl")}
    requests = read_jsonl(replay_dir / "repair_requests.jsonl")[: args.max_ctis]
    existing = {r.get("cti_id") for r in read_jsonl(replay_dir / "repairs.jsonl")}
    template = load_template("offline_repair.txt")
    client = DeepSeekClient(model_name=args.model or None)

    for req in requests:
        cti_id = req.get("cti_id")
        if cti_id in existing or cti_id not in cti_by_id:
            continue
        prompt = template.format(
            static_context=json.dumps(static_context, ensure_ascii=False, sort_keys=True),
            cti_context=json.dumps(cti_by_id[cti_id], ensure_ascii=False, sort_keys=True),
            repair_request=json.dumps(req, ensure_ascii=False, sort_keys=True),
        )
        text, tokens, latency = client.call(prompt, model_name=args.model or None)
        try:
            raw = extract_json_object(text)
            row = normalize_repair(raw, req)
        except Exception as exc:
            row = {
                "schema_version": 1,
                "cti_id": cti_id,
                "mode": "repair",
                "base_keep_ids": [int(x) for x in req.get("failed_keep_ids", [])],
                "add_back_ids": [],
                "confidence": "low",
                "short_reason": f"invalid_json: {exc}",
            }
        row["token_count"] = tokens
        row["latency_ms"] = latency
        append_jsonl(replay_dir / "repairs.jsonl", row)
    return 0
```

- [ ] **Step 7: Add summarize command**

Append:

```python
def count_status(rows: Iterable[Dict[str, Any]], status: str) -> int:
    return sum(1 for r in rows if r.get("status") == status)


def cmd_summarize(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    ctis = read_jsonl(replay_dir / "cti_contexts.jsonl")
    proposals = read_jsonl(replay_dir / "proposals.jsonl")
    repairs = read_jsonl(replay_dir / "repairs.jsonl")
    proposal_results = read_jsonl(replay_dir / "proposal_replay_results.jsonl")
    summary = {
        "num_ctis": len(ctis),
        "proposal_records": len(proposals),
        "proposal_accepts": count_status(proposal_results, "accepted_initial"),
        "proposal_sat_failures": count_status(proposal_results, "sat_failed_initial"),
        "repair_requests": len(read_jsonl(replay_dir / "repair_requests.jsonl")),
        "repair_records": len(repairs),
        "invalid_llm_json": sum(1 for r in proposals + repairs if "invalid_json" in r.get("short_reason", "")),
    }
    (replay_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0
```

- [ ] **Step 8: Add main parser**

Append:

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Pono LLM repair replay driver")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("propose", "repair", "summarize"):
        p = sub.add_parser(name)
        p.add_argument("--replay-dir", required=True)
        p.add_argument("--model", default=os.environ.get("PONO_LLM_MODEL", ""))
        p.add_argument("--max-ctis", type=int, default=50)
    args = parser.parse_args()
    if args.cmd == "propose":
        return cmd_propose(args)
    if args.cmd == "repair":
        return cmd_repair(args)
    if args.cmd == "summarize":
        return cmd_summarize(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Make executable and syntax-check**

```bash
chmod +x llm_worker/offline_repair_driver.py
python3 -m py_compile llm_worker/offline_repair_driver.py
```

Expected: command exits with status 0 and no output.

- [ ] **Step 10: Commit**

```bash
git add llm_worker/offline_repair_driver.py llm_worker/prompts/offline_proposal.txt llm_worker/prompts/offline_repair.txt
git commit -m "Add offline LLM proposal and repair driver"
```

---

### Task 6: Apply repair records during offline replay

**Files:**
- Modify: `engines/ic3base.cpp`
- Modify: `engines/llm_generalizer.cpp`

- [ ] **Step 1: Add a separate result writer for repair replay**

Change `write_replay_result` in `engines/llm_generalizer.cpp` so it chooses the output file by status prefix:

```cpp
  const bool repair_status = status.find("repair_") == 0;
  const std::string out_path = replay_dir_ + (repair_status
      ? "/repair_replay_results.jsonl"
      : "/proposal_replay_results.jsonl");
  std::ofstream fout(out_path, std::ios::app);
```

Keep the JSON body unchanged.

- [ ] **Step 2: Extend offline hook to check repairs after failed proposal**

Edit the bottom of `process_offline_llm_for_cti` after writing the initial SAT failure:

```cpp
  if (!diffs.empty()) {
    llm_gen_->write_repair_request(ctx, proposal, diffs);
  }

  LLMIdCandidate repair;
  if (!llm_gen_->get_repair(ctx.cti_id, repair)) return;

  std::set<size_t> repaired_keep(proposal.keep_ids.begin(), proposal.keep_ids.end());
  for (size_t id : repair.add_back_ids) repaired_keep.insert(id);
  std::vector<size_t> repaired_keep_ids(repaired_keep.begin(), repaired_keep.end());

  IC3Formula repaired_cube = cube_from_keep_ids(cube, repaired_keep_ids);
  IC3Formula repaired_blocking = blocking_from_keep_ids(cube, repaired_keep_ids);
  std::vector<LLMWitnessDiff> repair_diffs;
  std::vector<size_t> remaining_drop;
  for (size_t id : proposal.drop_ids) {
    if (!repaired_keep.count(id)) remaining_drop.push_back(id);
  }

  bool repair_ok = check_llm_candidate_with_witness(
      ctx.frame_idx, repaired_cube, ctx, remaining_drop, repair_diffs);
  if (repair_ok) {
    constrain_frame(ctx.frame_idx, repaired_blocking, true);
    llm_gen_->stats_.num_accepted++;
    llm_gen_->write_replay_result(ctx.cti_id, "repair_accepted", ctx.frame_idx,
                                  cube.children.size(), repaired_cube.children.size(),
                                  repair.short_reason);
  } else {
    llm_gen_->write_replay_result(ctx.cti_id, "repair_sat_failed", ctx.frame_idx,
                                  cube.children.size(), repaired_cube.children.size(),
                                  "repair still includes a reachable successor");
  }
```

- [ ] **Step 3: Build**

```bash
make -j$(nproc) -C build
```

Expected final lines include:

```text
Built target pono-bin
```

- [ ] **Step 4: Commit**

```bash
git add engines/ic3base.cpp engines/llm_generalizer.cpp
git commit -m "Replay repaired LLM candidates"
```

---

### Task 7: Add Python unit tests for the offline driver

**Files:**
- Create: `tests/test_offline_repair_driver.py`

- [ ] **Step 1: Write tests**

Create `tests/test_offline_repair_driver.py`:

```python
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "llm_worker"))

import offline_repair_driver as drv


def test_extract_json_object_strips_markdown():
    row = drv.extract_json_object('```json\n{"keep_ids":[0],"drop_ids":[1]}\n```')
    assert row == {"keep_ids": [0], "drop_ids": [1]}


def test_normalize_proposal_filters_invalid_ids():
    cti = {"cti_id": "c1", "literals": [{"id": 0}, {"id": 1}, {"id": 2}]}
    raw = {"keep_ids": [0, 9], "drop_ids": [1, 9], "confidence": "high", "short_reason": "x"}
    row = drv.normalize_proposal(raw, cti)
    assert row["cti_id"] == "c1"
    assert row["keep_ids"] == [0]
    assert row["drop_ids"] == [1]


def test_normalize_proposal_infers_drop_ids():
    cti = {"cti_id": "c1", "literals": [{"id": 0}, {"id": 1}, {"id": 2}]}
    row = drv.normalize_proposal({"keep_ids": [2]}, cti)
    assert row["drop_ids"] == [0, 1]


def test_normalize_repair_allows_only_witness_diff_ids():
    req = {
        "cti_id": "c1",
        "failed_keep_ids": [0],
        "sat_witness_diff": [{"literal_id": 1}, {"literal_id": 3}],
    }
    row = drv.normalize_repair({"add_back_ids": [1, 2, 3]}, req)
    assert row["base_keep_ids"] == [0]
    assert row["add_back_ids"] == [1, 3]


def test_jsonl_roundtrip(tmp_path):
    path = tmp_path / "x.jsonl"
    drv.append_jsonl(path, {"b": 2, "a": 1})
    assert drv.read_jsonl(path) == [{"a": 1, "b": 2}]
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest tests/test_offline_repair_driver.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_offline_repair_driver.py
git commit -m "Test offline LLM repair driver helpers"
```

---

### Task 8: End-to-end smoke test with fake proposal records

**Files:**
- Modify only if needed to fix compile/runtime issues found by the smoke test.

- [ ] **Step 1: Build**

```bash
make -j$(nproc) -C build
```

Expected final lines include:

```text
Built target pono-bin
```

- [ ] **Step 2: Run offline dump on a selected benchmark**

Use the benchmark that produced CTIs in the prior E2E run. Set `BENCH` to that absolute path:

```bash
REPLAY=/tmp/pono_offline_replay_smoke
rm -rf "$REPLAY"
build/pono -e ic3ia --llm-gen-mode offline-dump --llm-replay-dir "$REPLAY" "$BENCH" || true
test -s "$REPLAY/static_context.json"
test -s "$REPLAY/cti_contexts.jsonl"
head -1 "$REPLAY/cti_contexts.jsonl"
```

Expected: both `test -s` commands pass and `head` prints a JSON object containing `cti_id` and `literals`.

- [ ] **Step 3: Create fake full-cube proposals**

Run:

```bash
python3 - <<'PY'
import json, pathlib
replay = pathlib.Path('/tmp/pono_offline_replay_smoke')
out = replay / 'proposals.jsonl'
with (replay / 'cti_contexts.jsonl').open() as f, out.open('w') as g:
    for line in f:
        cti = json.loads(line)
        ids = [int(l['id']) for l in cti['literals']]
        row = {
            'schema_version': 1,
            'cti_id': cti['cti_id'],
            'mode': 'proposal',
            'keep_ids': ids,
            'drop_ids': [],
            'confidence': 'low',
            'short_reason': 'smoke full cube proposal'
        }
        g.write(json.dumps(row, sort_keys=True) + '\n')
PY
```

Expected: `/tmp/pono_offline_replay_smoke/proposals.jsonl` exists and has the same number of lines as `cti_contexts.jsonl`.

- [ ] **Step 4: Replay fake proposals**

```bash
build/pono -e ic3ia --llm-gen-mode offline-check --llm-replay-dir "$REPLAY" "$BENCH" || true
ls -l "$REPLAY"/*replay_results.jsonl "$REPLAY"/repair_requests.jsonl 2>/dev/null || true
```

Expected: `proposal_replay_results.jsonl` exists. Some full-cube proposals may pass and some may fail depending on frame timing; the required smoke condition is that replay parses proposals and writes result records without crashing.

- [ ] **Step 5: Summarize**

```bash
python3 llm_worker/offline_repair_driver.py summarize --replay-dir "$REPLAY"
test -s "$REPLAY/summary.json"
```

Expected: printed JSON includes `num_ctis`, `proposal_records`, and `proposal_accepts`.

- [ ] **Step 6: Commit runtime fixes**

If any fixes were needed:

```bash
git add engines llm_worker tests options docs
git commit -m "Fix offline LLM replay smoke issues"
```

If no fixes were needed, skip this commit.

---

### Task 9: Document offline replay workflow

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add architecture section**

Append to `docs/ARCHITECTURE.md`:

```markdown
## Offline LLM Repair Replay

Offline replay is the experimental path for testing whether LLM proposals can become solver-accepted IC3/PDR lemmas without blocking the live IC3 loop on LLM latency.

Workflow:

```text
1. Pono offline-dump
   -> static_context.json
   -> cti_contexts.jsonl

2. Python propose
   -> proposals.jsonl

3. Pono offline-check
   -> proposal_replay_results.jsonl
   -> repair_requests.jsonl

4. Python repair
   -> repairs.jsonl

5. Pono offline-check
   -> repair_replay_results.jsonl

6. Python summarize
   -> summary.json
```

The static context is heuristic prompt input only. Every accepted lemma is checked by Pono with the full transition relation and the live PDR frame sequence.

Example:

```bash
REPLAY=llm_replay/foo
build/pono -e ic3ia --llm-gen-mode offline-dump --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py propose --replay-dir "$REPLAY" --model deepseek/deepseek-v4-pro
build/pono -e ic3ia --llm-gen-mode offline-check --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py repair --replay-dir "$REPLAY" --model deepseek/deepseek-v4-pro
build/pono -e ic3ia --llm-gen-mode offline-check --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py summarize --replay-dir "$REPLAY"
```
```

- [ ] **Step 2: Commit docs**

```bash
git add docs/ARCHITECTURE.md
git commit -m "Document offline LLM repair replay workflow"
```

---

### Task 10: Final verification before reporting completion

**Files:**
- No source edits unless a verification failure requires a fix.

- [ ] **Step 1: Run Python tests**

```bash
python3 -m pytest tests/test_offline_repair_driver.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 2: Build C++**

```bash
make -j$(nproc) -C build
```

Expected final lines include:

```text
Built target pono-bin
```

- [ ] **Step 3: Check git status**

```bash
git status --short
```

Expected: either clean working tree or only intended experiment artifacts ignored by `.gitignore`.

- [ ] **Step 4: Report metrics to the user**

Report:

```text
Implemented offline-dump/offline-check modes.
Implemented ID-based proposal replay.
Implemented SAT witness diff repair requests.
Implemented Python proposal/repair/summarize driver.
Verification: pytest result, build result, smoke-test replay result.
```

---

## Self-Review

Spec coverage:

- 0A static context: Task 3.
- 0B dynamic CTI context: Task 3.
- ID-based proposals: Tasks 2 and 5.
- Solver replay inside Pono: Tasks 4 and 6.
- SAT witness diff: Task 4.
- LLM repair: Tasks 5 and 6.
- JSONL summary: Task 5.
- Documentation: Task 9.

Placeholder scan:

- The plan contains no deferred implementation labels.
- Every command includes the expected outcome.
- Each new file has concrete content to start from.

Type consistency:

- `CTILiteral.id` is `size_t`; Python serializes IDs as JSON numbers.
- `LLMIdCandidate.keep_ids`, `drop_ids`, and `add_back_ids` are all `std::vector<size_t>`.
- Replay result statuses used by C++ match the Python summary strings: `accepted_initial`, `sat_failed_initial`, `repair_accepted`, `repair_sat_failed`.
