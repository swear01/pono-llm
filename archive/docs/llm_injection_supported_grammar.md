> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

# LLM Injection Supported Grammar

> **HISTORICAL — Path 1 text grammar.** Code **will be deleted** with IC3 Frame v1.  
> **Active spec:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) (structured AST, not text triplets).

> Precise specification of what Path 1 accepted at audit time.

---

## Environment Variables (Actual Implementation)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PONO_LLM_ASSERT_LIFTED_LEMMAS` | Yes (non-empty, not `"0"`) | unset → disabled | Enable injection block |
| `PONO_LLM_LEMMA_LIST` | No | `logs/formal_yield/lemma_list.txt` | Path to whitespace triplet file |

**Deprecated / planned names (not implemented):**

- `PONO_LLM_INJECT_LEMMAS` — from [`minimal_lifted_lemma_injection_plan.md`](minimal_lifted_lemma_injection_plan.md)
- `PONO_LLM_LEMMA_FILE` + JSON subset — not read by C++

---

## Text File Format

One lemma per line:

```text
ant_var1 ant_var2 cons_var
```

Example (`logs/formal_yield/lemma_lists/one_best.txt`):

```text
state469 state471 state15
```

Maps to SMT (all literals fixed to `#b0`):

```smt
(=> (and (= state469 #b0) (= state471 #b0)) (= state15 #b0))
```

Rules:

- Lines starting with `#` or empty lines are skipped
- Requires **≥3 whitespace-separated tokens**; first two are antecedents, third is consequent
- Variable names must exist in `conc_ts_` (typically `stateNN` BTOR2 node IDs)
- Missing variables are **silently skipped** (no error log per lemma)
- File is loaded **once** (static cache); assertions repeat on every `reset_solver()`

---

## C++ Term Construction

```cpp
auto mk_eq_bv0 = [this](const std::string & varname) -> Term {
    Term sv = conc_ts_.lookup(varname);
    if (!sv) return Term();
    Term bv0 = solver_->make_term(0, sv->get_sort());
    return solver_->make_term(Equal, sv, bv0);
};
// ...
Term ante = solver_->make_term(And, TermVec{eq1, eq2});
solver_->assert_formula(solver_->make_term(Implies, ante, eqC));
```

Only `#b0` (zero) equalities. No `#b1`, no negation, no OR consequents.

---

## Grammar Support Matrix

| Lemma type | Example | C++ inject | In lemma_lists | Notes |
|---|---|---|---|---|
| 2-guard implication, all `#b0` | `(=> (and (= A #b0) (= B #b0)) (= C #b0))` | **Yes** | 25/26 lifted | Primary supported form |
| Single implication, `#b0` | `(=> (= state15 #b0) (= state645 #b0))` | **No** | No | `lift_025`; needs 1-guard parser |
| Single implication, `#b1` | `(=> (= state2002 #b1) (= state790 #b1))` | **No** | No | Closed-loop lemma |
| Mixed `#b0`/`#b1` | `(=> (and (= A #b1) (= B #b0)) (= C #b1))` | **No** | No | Needs per-literal values |
| Nary mutex | `(not (and (= A #b1) (= B #b1)))` | **No** | No | No `Not`/`And` n-ary builder |
| OR consequent | `(=> (= A #b0) (or (= B #b0) (= C #b1)))` | **No** | No | — |
| Full SMT-LIB line | arbitrary | **No** | No | — |

---

## Python vs C++ Capability Mismatch

[`llm_worker/prepare_lifted_lemma_injection.py`](../llm_worker/prepare_lifted_lemma_injection.py) sets:

```python
info["supported"] = info["ante_count"] <= 2
```

This marks `lift_025` (`ante_count=1`) as `supported: true` in JSON dryrun, but **C++ still rejects it** because it always builds a 2-antecedent `And`. Treat C++ behavior as authoritative.

---

## Assertion Point in Solver Lifecycle

```text
IC3Base::reset_solver()
  → reset_assertions()
  → re-assert init/trans/bad/frame constraints

IC3IA::reset_solver()
  → super::reset_solver()
  → re-assert lbl2pred_ equalities
  → re-assert lifted lemmas (if enabled)
```

Assertions live at **solver context 0** and persist until the next reset.

---

## Generating Lemma List Files

From verified lifted lemmas (Python side):

```bash
python3 llm_worker/prepare_lifted_lemma_injection.py
# produces lifted_lemma_injection_subsets.json + dryrun
# lemma_lists/*.txt are derived manually or by downstream scripts
```

Audit injection coverage:

```bash
python3 llm_worker/audit_injection_capability.py
```
