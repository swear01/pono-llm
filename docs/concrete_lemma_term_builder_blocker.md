> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Concrete Lemma Term Builder Dry-Run

> **SUPERSEDED (2026-06-03).** Term construction is not the blocker; injection is
> implemented via `reset_solver()` concrete assert. See
> [`docs/llm_injection_capability_audit.md`](llm_injection_capability_audit.md).

## Status: Blocker Resolved (Different Path)

Term construction was never the hard problem. The original blocker was choosing an
injection interface (`constrain_frame()` vs raw assert). The adopted path:

- Build concrete BV terms from `conc_ts_.lookup()`
- `assert_formula()` in `IC3IA::reset_solver()`
- Opt-in via `PONO_LLM_ASSERT_LIFTED_LEMMAS`

## What Works

```cpp
Term s = conc_ts_.lookup(varname);
Sort bvs = s->get_sort();
Term bv0 = solver_->make_term(0, bvs);
Term eq = solver_->make_term(Equal, s, bv0);
Term impl = solver_->make_term(Implies, conj, conseq);
solver_->assert_formula(impl);
```

All 25 injectable lifted lemmas use variables present in `conc_ts_`.

## Remaining Gap (Not Term Building)

The **predicate abstraction path** (`constrain_frame()` / `add_predicate()`) remains unimplemented. Current injection bypasses IC3IA labels and asserts concrete formulas directly.

## Decision (Updated)

**concrete_lemma_term_builder_resolved_via_reset_solver**

Use offline replay for frame-overlap estimates; use live injection for runtime experiments with claim boundaries in [`reset_solver_injection_claim_boundary.md`](reset_solver_injection_claim_boundary.md).
