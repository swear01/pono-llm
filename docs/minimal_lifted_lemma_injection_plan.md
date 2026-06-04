> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Minimal Lifted Lemma Injection Plan

> **Partially superseded (2026-06-03).** The `add_predicate()` path was not adopted.
> Implemented path: concrete assert in `IC3IA::reset_solver()`. See
> [`docs/llm_injection_capability_audit.md`](llm_injection_capability_audit.md).

## Goal

Inject solver-verified lifted lemmas as additional assertions in Pono
to test whether they accelerate IC3IA convergence, even without direct
clause-subsumption impact.

## Injection Points

| Point | Sound? | Easy? | Risk | Notes |
|---|---|---|---|---|
| As `IC3IA::add_predicate()` | Yes | Easy | Low | Adds lemma as an initial predicate |
| As frame-0 clause via `constrain_frame(0, ...)` | No | Easy | **Unsound** | Frame 0 is handled specially |
| As `solver_->assert_formula(lemma)` at init | Yes | Medium | Medium | Lemma must hold at init |
| As IC3IA assumption added before `check_until()` | Yes | Medium | Low-Medium | Similar to existing assumption pattern |

## Recommended: `add_predicate()` Injection

Add each lifted lemma as a predicate via `IC3IA::add_predicate()`. Since
the lemma is already verified as init-valid AND one-step-valid AND
induction-valid, adding it as a predicate is sound.

## Soundness Boundary

Only inject lemmas that were independently validated by:
- Init check: UNSAT
- One-step check: UNSAT  
- Induction check: UNSAT
- Under the offline Bitwuzla pipeline with 88% transition coverage

## Opt-In Interface (Implemented)

```bash
PONO_LLM_ASSERT_LIFTED_LEMMAS=1
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt
```

Text file format: `ant_var1 ant_var2 cons_var` (one line per lemma, all `#b0`).

**Planned but not implemented:**

```bash
PONO_LLM_INJECT_LEMMAS=1
PONO_LLM_LEMMA_FILE=logs/formal_yield/lifted_lemma_injection_dryrun.json
PONO_LLM_LEMMA_SUBSET=top_5_by_score
```

When env var is not set, behavior is unchanged.

## Current Blocker (Updated)

**Grammar too narrow**, not term mapping:

- C++ accepts only 2-guard `#b0` triplets (25/26 lifted lemmas)
- Single implication (`lift_025`) and closed-loop lemma (`#b1`) not injectable
- No nary mutex or SMT formula loader

The original predicate-mapping blocker applied to `add_predicate()` / `constrain_frame()`.
The adopted concrete-assert path bypasses that layer.

## Remaining Risk

- The 26 lifted lemmas were verified under 88% transition coverage
  (29/247 lines untranslated). If those missing transitions affect
  the lemma's validity inside Pono, injection could be unsound.
- The offline Bitwuzla pipeline may differ from Pono's internal solver
  configuration.
