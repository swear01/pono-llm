> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Concrete Solver Assertion Injection Audit

> **SUPERSEDED (2026-06-03).** The `constrain_frame()` path remains blocked, but
> **concrete assertion via `IC3IA::reset_solver()` is implemented.** See
> [`docs/llm_injection_capability_audit.md`](llm_injection_capability_audit.md).

## Summary (Updated)

Concrete solver assertion injection for lifted lemmas is **implemented** as an opt-in
prototype. The originally recommended `constrain_frame()` + `IC3Formula` path is still
blocked by predicate abstraction requirements.

## Candidate Injection Points (Historical)

| Location | Status |
|---|---|
| `constrain_frame()` | Still blocked — needs Boolean predicate labels |
| Override `reset_solver()` | **Adopted** — `engines/ic3ia.cpp` |
| Raw assert without reset override | Unsound — avoided |

## Required Term Construction

Building `(=> (and (= state469 #b0) (= state471 #b0)) (= state15 #b0))` works as documented below. This code path is live in production prototype.

## Original Decision

**concrete_injection_blocked_missing_term_mapping** — applied to `constrain_frame()` only.

## Current Decision

**concrete_injection_via_reset_solver_prototype**

Limited to 2-guard `#b0` triplets from text files. Not full formula integration.

## Blockers (Frame Path Only)

1. Bitvector→Boolean predicate abstraction mapping not available at `constrain_frame()` insertion time.
2. `constrain_frame()` interface requires `IC3Formula` with Boolean children.
3. Raw `assert_formula()` without `reset_solver()` override is unsound — resolved by override.

## Next Patch (Frame Path — Still Future)

Option A: `IC3IA::add_predicate()` with lemma decomposed to disjunction.
Option B: Concrete assumption at `check_until()` entry (superseded by implemented Option in reset_solver).
Option C: Offline replay — still useful; see WP5.
