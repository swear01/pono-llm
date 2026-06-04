> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime path. See [`ic3_frame_v1_integration.md`](../ic3_frame_v1_integration.md).

# CTI Simplification + Benchmark Filtering — Implementation Plan

> **For agentic workers:** Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LLM generalization measurably effective — LLM candidates pass induction checks and IC3IA refinement count drops.

**Architecture:** Two parts: (C) find benchmarks where IC3IA baseline already solves but takes multiple refinement cycles; (A) simplify CTI SMT expressions into human-readable signal summaries so the LLM can understand what each literal means and produce meaningful keep/drop suggestions.

**Tech Stack:** C++17 / smt-switch Term API / Python sidecar / DeepSeek V4 Pro

---

### Task 1: Find IC3IA-solvable non-fast benchmarks (C)

**Files:**
- Modify: `scripts/run_benchmarks.py` (add `--find-solvable` phase)

- [ ] **Step 1: Add benchmark discovery phase**

Add a `find_solvable` phase that:
1. Reads competition CSVs, finds benchmarks where pono got sat/unsat and category != fast
2. Skips benchmarks that were `unknown` in competition
3. Verifies the .btor2 file exists on disk
4. Runs a quick baseline (our machine) to confirm it also solves with IC3IA
5. Records refinement count from pono stderr (grep for `refine`/`REFINE`/`Blocking phase`)

Add to `scripts/run_benchmarks.py` (after line ~220, inside `parse_args`):

```python
p.add_argument(
    "--find-solvable",
    action="store_true",
    help="Find IC3IA-solvable non-fast benchmarks from competition data",
)
p.add_argument(
    "--find-max",
    type=int,
    default=30,
    help="Max benchmarks to test in find-solvable phase",
)
```

And in `main()` (after line ~1316):

```python
if "find_solvable" in todo or args.find_solvable:
    results = run_find_solvable(args)
    if results:
        log(f"Found {len(results)} solvable benchmarks:")
        for r in results:
            log(f"  {r['name']:50s} {r['expected']:5s} {r['time']:6.1f}s  refinements={r['refinements']}")
    return 0
```

- [ ] **Step 2: Implement `run_find_solvable()`**

Add function before `main()`:

```python
def run_find_solvable(args: argparse.Namespace) -> list[dict]:
    """Find IC3IA-solvable non-fast benchmarks from competition data."""
    log("=== Phase: find-solvable ===")
    years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
    comp_map = load_competition_classification(args.hwmcc_dir)
    entries = collect_benchmarks(args.hwmcc_dir, years)

    # Filter: pono solved in competition, not fast, not unknown
    targets = []
    for e in entries:
        ce = match_entry_to_competition(e, comp_map)
        if not ce:
            continue
        if ce.category in ("medium", "slow"):
            targets.append((e, ce))
    targets = targets[:args.find_max]

    log(f"Testing {len(targets)} candidates...")
    pono_bin = str(_resolve_pono(args))
    results = []

    for e, ce in targets:
        name = pathlib.Path(e.path).name
        log(f"  testing: {name} (comp: {ce.result} {ce.wall_time:.0f}s {ce.category})")
        cmd = [pono_bin, "-v", "2", "-e", args.engine, "-k", str(args.bound), e.path]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=min(args.timeout, 300))
            stdout_text = (proc.stdout or "").strip().lower()
            stderr_text = proc.stderr or ""
            if stdout_text in ("sat", "unsat"):
                # Count refinement cycles from stderr
                refinements = len([l for l in stderr_text.splitlines()
                                  if "Blocking phase at frame" in l])
                if refinements > 0:
                    results.append({
                        "name": name,
                        "path": e.path,
                        "expected": e.expected,
                        "time": 0,
                        "refinements": refinements,
                    })
                    log(f"    ✅ solved, {refinements} blocking phases")
            else:
                log(f"    ❌ result={stdout_text[:20]}")
        except subprocess.TimeoutExpired:
            log(f"    ⏱ timeout")
        except Exception as exc:
            log(f"    ❌ error: {exc}")

    return results
```

- [ ] **Step 3: Run and select benchmarks**

```bash
python3 scripts/run_benchmarks.py --find-solvable --hwmcc-years 2020,2024,2025 --engine ic3ia --find-max 30
```

Expected: list of benchmarks with refinement counts. Pick 3-5 with 10+ refinements.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_benchmarks.py
git commit -m "Add --find-solvable phase to discover IC3IA benchmarks with refinements"
```

---

### Task 2: CTI SMT simplification (A)

**Files:**
- Modify: `engines/ic3base.cpp` — `collect_cti_literals()` + new `simplify_cti_literal()` helper
- Modify: `engines/ic3base.h` — declare helper (or keep as static in .cpp)

- [ ] **Step 1: Write the simplification helper**

Add to `engines/ic3base.cpp` before `collect_cti_literals()`:

```cpp
static std::string simplify_cti_literal(const smt::Term & term,
                                         const smt::SmtSolver & solver)
{
  // Walk the SMT expression tree to produce a human-readable summary.
  // Returns a string like "state383[4:0] >= 0  OR  ~input9[0]"

  smt::Op op = term->get_op();

  // Leaf: variable/symbol
  if (term->is_symbol() || op == smt::BV || op == smt::PrimOp(/*...*/)) {
    // Try to get a name
    try {
      return solver->get_smtlib_string(term);
    } catch (...) {
      return term->to_string();
    }
  }

  // Extract signals recursively
  std::vector<std::string> children_strs;
  for (auto it = term->begin(); it != term->end(); ++it) {
    children_strs.push_back(simplify_cti_literal(*it, solver));
  }

  // Map SMT operators to readable forms
  auto binop = [&](const std::string & sym) {
    return "(" + children_strs[0] + " " + sym + " " + children_strs[1] + ")";
  };

  switch (op.prim_op) {
    case smt::Not:     return "~" + children_strs[0];
    case smt::And:     return binop("∧");
    case smt::Or:      return binop("∨");
    case smt::Xor:     return binop("⊕");
    case smt::Implies: return binop("→");
    case smt::Equal:   return binop("=");
    case smt::Distinct:return binop("≠");
    case smt::BVNot:   return "~" + children_strs[0];
    case smt::BVAnd:   return binop("&");
    case smt::BVOr:    return binop("|");
    case smt::BVXor:   return binop("^");
    case smt::BVAdd:   return binop("+");
    case smt::BVSub:   return binop("-");
    case smt::BVMul:   return binop("*");
    case smt::BVUgt:   return binop(">");
    case smt::BVUge:   return binop("≥");
    case smt::BVUlt:   return binop("<");
    case smt::BVUle:   return binop("≤");
    case smt::BVSgt:   return binop(">ₛ");
    case smt::BVSge:   return binop("≥ₛ");
    case smt::BVSlt:   return binop("<ₛ");
    case smt::BVSle:   return binop("≤ₛ");
    case smt::BVSdiv:  return binop("/ₛ");
    case smt::BVShl:   return binop("<<");
    case smt::BVAshr:  return binop(">>ₐ");
    case smt::BVLshr:  return binop(">>");
    case smt::Concat:  return binop("++");
    case smt::Extract: {
      // (extract hi lo x) → x[hi:lo]
      return children_strs[2] + "["
             + std::to_string(term->get_indexed_op_idx0())
             + ":" + std::to_string(term->get_indexed_op_idx1())
             + "]";
    }
    case smt::Zero_Extend: return "zero_ext(" + children_strs[0] + ")";
    case smt::Sign_Extend: return "sign_ext(" + children_strs[0] + ")";
    case smt::Ite:   return "ite(" + children_strs[0] + ", "
                        + children_strs[1] + ", " + children_strs[2] + ")";
    default:
      // Fallback: get SMTLIB string for unrecognized ops
      return term->to_string();
  }
}
```

- [ ] **Step 2: Integrate into `collect_cti_literals`**

Modify `collect_cti_literals` in `engines/ic3base.cpp` to use the simplifier:

```cpp
std::vector<CTILiteral> IC3Base::collect_cti_literals(
    const IC3Formula & cube) const
{
  std::vector<CTILiteral> lits;
  assert(!cube.disjunction);
  for (const auto & child : cube.children) {
    CTILiteral lit;
    lit.term = child;
    if (child->get_op() == smt::Not) {
      smt::Term inner = *(child->begin());
      lit.varname = simplify_cti_literal(inner, solver_);
      lit.value = "false";
    } else {
      lit.varname = simplify_cti_literal(child, solver_);
      lit.value = "true";
    }
    // Truncate very long simplified strings
    if (lit.varname.size() > 200) {
      lit.varname = lit.varname.substr(0, 197) + "...";
    }
    lits.push_back(lit);
  }
  return lits;
}
```

- [ ] **Step 3: Simplify property name too**

In `capture_cti_context` (line ~1178), truncate property to first 200 chars:

```cpp
std::string raw_prop = ts_.get_name(bad_);
ctx.property_name = raw_prop.size() > 200 ? raw_prop.substr(0, 197) + "..." : raw_prop;
```

- [ ] **Step 4: Recompile and smoke test**

```bash
make -j$(nproc) -C build
```

Expected: compile without errors.

- [ ] **Step 5: Quick verification — generate one CTI and check output**

```bash
rm -rf /tmp/pono_simpl && mkdir -p /tmp/pono_simpl
timeout 10 ./build/pono -v 1 -e ic3ia -k 100000 \
  --llm-gen-mode async-cti --llm-candidate-language cube-subset \
  --llm-model deepseek-v4-pro \
  --llm-req-path /tmp/pono_simpl/req.jsonl \
  --llm-resp-path /tmp/pono_simpl/resp.jsonl \
  ~/hwmcc_benchmarks/2020/hwmcc20/btor2/bv/2019/mann/data-integrity/unsafe/arbitrated_top_n4_w16_d16_e0.btor2 2>/dev/null
head -1 /tmp/pono_simpl/req.jsonl | python3 -c "import sys,json; r=json.load(sys.stdin); print(f'literals: {len(r[\"literals\"])}'); [print(f'  [{i}] {l[\"varname\"][:100]}... = {l[\"value\"]}') for i,l in enumerate(r['literals'][:3])]"
```

Expected: varnames are simplified (e.g., `state383[4:0] > 0x0 ∨ ~input9[0]` instead of raw SMT).

- [ ] **Step 6: Commit**

```bash
git add engines/ic3base.cpp engines/ic3base.h
git commit -m "feat: simplify CTI SMT expressions to human-readable form for LLM"
```

---

### Task 3: Deduplicate CTI contexts

**Files:**
- Modify: `engines/llm_generalizer.cpp` — `write_cti_context()`
- Modify: `engines/llm_generalizer.h` — add hash set for dedup

- [ ] **Step 1: Add dedup set to LLMGeneralizer**

In `engines/llm_generalizer.h`, add to private members:

```cpp
std::unordered_set<std::string> sent_ctx_hashes_;
```

- [ ] **Step 2: Dedup in write_cti_context**

In `engines/llm_generalizer.cpp`, at the top of `write_cti_context`:

```cpp
void LLMGeneralizer::write_cti_context(const CTIContext & ctx)
{
  // Dedup: skip if we already sent a context with the same literals
  std::string ctx_hash;
  for (const auto & lit : ctx.literals) {
    ctx_hash += lit.varname + lit.value;
  }
  if (sent_ctx_hashes_.count(ctx_hash)) {
    return;
  }
  sent_ctx_hashes_.insert(ctx_hash);

  // ... rest of existing code
```

- [ ] **Step 3: Limit max CTIs per benchmark**

In `write_cti_context`, add a cap check after dedup:

```cpp
  if (stats_.num_requests >= 50) {
    return;  // skip, already sent enough CTIs
  }
```

- [ ] **Step 4: Recompile and commit**

```bash
make -j$(nproc) -C build
git add engines/llm_generalizer.cpp engines/llm_generalizer.h
git commit -m "feat: deduplicate CTI contexts and cap at 50 per benchmark"
```

---

### Task 4: End-to-end test with solvable benchmark

**Files:**
- No new files — manual testing phase

- [ ] **Step 1: Run baseline without LLM on selected benchmark**

```bash
timeout 300 ./build/pono -v 2 -e ic3ia -k 100000 <selected_benchmark.btor2> 2>&1 | grep "Blocking phase at frame" | wc -l
```

Record the number of blocking phases (= refinement cycles).

- [ ] **Step 2: Run with LLM**

```bash
export DEEPSEEK_API_KEY="sk-..."
rm -rf /tmp/pono_e2e && mkdir -p /tmp/pono_e2e
python3 llm_worker/sidecar.py --req-path /tmp/pono_e2e/req.jsonl --resp-path /tmp/pono_e2e/resp.jsonl --log-path /tmp/pono_e2e/log.jsonl --max-requests 50 --poll-interval 0.5 --model deepseek-v4-pro &
SPID=$! && sleep 1
timeout 300 ./build/pono -v 2 -e ic3ia -k 100000 \
  --llm-gen-mode async-cti --llm-candidate-language cube-subset \
  --llm-model deepseek-v4-pro \
  --llm-req-path /tmp/pono_e2e/req.jsonl \
  --llm-resp-path /tmp/pono_e2e/resp.jsonl \
  <selected_benchmark.btor2> 2>&1 | tee /tmp/pono_e2e/stderr.log
kill $SPID 2>/dev/null
```

- [ ] **Step 3: Compare**

```bash
# Baseline refinements
grep "Blocking phase at frame" /tmp/baseline.log | wc -l

# LLM refinements
grep "Blocking phase at frame" /tmp/pono_e2e/stderr.log | wc -l

# LLM candidate stats
grep "LLM_STATS\|candidate\|ACCEPTED" /tmp/pono_e2e/stderr.log
```

Expected: LLM accepted > 0, blocking phases reduced by at least 1.
