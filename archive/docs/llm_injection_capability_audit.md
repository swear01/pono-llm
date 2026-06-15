> Archived: 2026-06-15
> Reason: Path 1 per-CTI injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

# LLM Lemma Injection Capability Audit (Task 107A)

> **HISTORICAL — Path 1 research baseline (2026-06-03).**  
> `PONO_LLM_ASSERT_LIFTED_LEMMAS` runtime **will be deleted** with IC3 Frame v1 (not deprecated).  
> **Active integration:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

> Canonical reference for what Path 1 injection supported at audit time.
>
> Machine-readable matrix: [`logs/formal_yield/injection_capability_matrix.json`](../logs/formal_yield/injection_capability_matrix.json)
> Actual injected subsets: [`logs/formal_yield/task106b_actual_injected_lemmas.json`](../logs/formal_yield/task106b_actual_injected_lemmas.json)
> Grammar spec: [`docs/llm_injection_supported_grammar.md`](llm_injection_supported_grammar.md)

---

## One-Sentence Summary

> LLM injection is an **opt-in concrete assertion prototype** in `IC3IA::reset_solver()`.
> It is **not** a full formula-level lemma injector, IC3 frame integrator, or predicate-label abstraction path.

---

## What Injection Does

```text
lemma_list.txt (whitespace triplets)
      ↓
parse: ant_var1 ant_var2 cons_var
      ↓
conc_ts_.lookup("stateNN") → SMT bitvector state vars
      ↓
build (=> (and (= A #b0) (= B #b0)) (= C #b0))
      ↓
solver_->assert_formula(...) after each reset_solver()
      ↓
IC3IA proof search uses extra invariant constraints in concrete solver context
```

**Implementation:** [`engines/ic3ia.cpp`](../engines/ic3ia.cpp), `IC3IA::reset_solver()` (~L410–459).

**Enable:**

```bash
PONO_LLM_ASSERT_LIFTED_LEMMAS=1
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt
build/pono -e ic3ia -k 5 qspiflash_dualflexpress_divfive-p040.btor2
```

---

## What Injection Is NOT

| Mechanism | Status |
|---|---|
| Add lemma to IC3 frame clauses | Not implemented |
| Add lemma as IC3IA predicate abstraction label | Not implemented |
| Learned clause / rel_ind_check integration | Not implemented |
| Arbitrary SMT-LIB formula loader | Not implemented |
| JSON lemma file at runtime | Not implemented (Python pre-processes to `.txt`) |

Early `constrain_frame()` injection was rejected because that layer uses Boolean predicate labels, not direct BTOR2 `stateNN` bitvector terms. The working path bypasses abstraction via concrete `assert_formula`.

---

## Verified Pool vs Actually Injectable vs Actually Tested

| Pool | Count | Notes |
|---|---|---|
| Solver-verified lifted lemmas | **26** | From clause-family lifting on qspiflash p040 frames |
| C++-injectable (2-guard, all `#b0`) | **25** | `lift_025` excluded (single antecedent) |
| In `lemma_lists/*.txt` | **25** | Subset name `all_26` is a misnomer (25 lines) |
| Closed-loop verified lemma | **1** | `state2002=1 => state790=1` — **not injectable** |
| Nary mutex lemmas | **0** in inject pipeline | No parser support |

Regenerate counts:

```bash
python3 llm_worker/audit_injection_capability.py
```

---

## Injection Subsets Used in Experiments

| Subset | File | Lines | Saturation run (`p040_injection_saturation.json`) |
|---|---|---|---|
| `one_best` | `lemma_lists/one_best.txt` | 1 | 1 lemma injected |
| `top_5_by_score` | `lemma_lists/top_5_by_score.txt` | 5 | 5 lemmas |
| `all_26` | `lemma_lists/all_26.txt` | 25 | 25 lemmas (not 26) |

Closest equivalent to external "hybrid_top": **`top_5_by_score`** (5 state15-consequent lifted lemmas).

---

## Task 106B Clarification

**Task 106B / hybrid_top / "29 lemmas full mapping" do not exist in this repo.**

- "29" in [`docs/formal_yield_table.md`](formal_yield_table.md) refers to **unique original LLM candidates**, not verified injectable lemmas.
- Mapping lemmas to benchmark variants (offline Bitwuzla validation) ≠ injecting them into Pono.
- Safe conclusion for p040: **under the current injectable subset, no benchmark unlock was observed** — not "all verified lemmas are useless."

---

## Safe Claims

1. Dynamic text-file loader works; lemmas logged at first `reset_solver()`.
2. Opt-in only; zero overhead when env var unset.
3. 25/26 lifted verified lemmas match C++ grammar and appear in lemma list files.
4. Closed-loop lemma is solver-verified but **outside C++ grammar**.
5. Mechanically asserts concrete BTOR2 terms on every successful solver reset.

## Claims NOT Supported

1. No runtime speedup (within noise).
2. No qspiflash p040 unlock (still unknown/timeout).
3. No stable artifact reduction — see [`docs/p040_saturation_repro_audit.md`](p040_saturation_repro_audit.md).
4. No full Pono / IC3IA integration.
5. Cannot claim closed-loop or mutex lemmas were tested in Pono.

---

## Lemmas Verified But NOT Injected in Pono

| ID | Lemma | Reason |
|---|---|---|
| `lift_025` | `(=> (= state15 #0) (= state645 #0))` | Single antecedent; C++ requires 2-guard triplet |
| `closed_loop_r1_001` | `(=> (= state2002 1) (= state790 1))` | Needs `#b1` literal; C++ hardcodes `#b0` only |

---

## Next Grammar Extensions (Future Work)

1. Single-guard implication: `(=> (= A #b0) (= B #b0))` and `(=> (= A #b1) (= B #b1))`
2. Arbitrary `#b0` / `#b1` per literal (not all-zero)
3. Nary mutex: `(not (and (= A #b1) (= B #b1) (= C #b0)))`
4. SMT or JSON formula loader with explicit unsupported-lemma logging
5. Optional: predicate/frame integration via `add_predicate()` or `constrain_frame()`

---

## Related Docs

| Doc | Role |
|---|---|
| [`reset_solver_injection_code_audit.md`](reset_solver_injection_code_audit.md) | C++ implementation detail |
| [`reset_solver_injection_claim_boundary.md`](reset_solver_injection_claim_boundary.md) | Experiment claim limits |
| [`reset_solver_injection_soundness_note.md`](reset_solver_injection_soundness_note.md) | Soundness caveats |
| [`p040_saturation_repro_audit.md`](p040_saturation_repro_audit.md) | Nondeterminism / artifact noise |
| Superseded blocker docs | Historical; see banners in `concrete_*_blocker.md` |
