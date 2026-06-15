> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

> **HISTORICAL — Path 1 was implemented then scheduled for deletion (2026-06-03).**  
> Not the active runtime path. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md).

# Concrete Assertion Injection — Blocked

> **Archive note:** This doc originally recorded blockers. Path 1 (`reset_solver` assert) was later implemented (Task 107A) and is now **scheduled for deletion** with IC3 Frame v1 — not maintained as production integration.

## Status (Historical)

This document originally recorded both injection paths as blocked. As of Task 107A:

1. **IC3IA predicate / frame injection** — still blocked (requires `lbl2pred_` / `constrain_frame()` mapping).
2. **Concrete solver assertion via `reset_solver()`** — **implemented** (opt-in, limited grammar).

## Current Working Command

```bash
PONO_LLM_ASSERT_LIFTED_LEMMAS=1 \
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt \
build/pono -e ic3ia -k 5 qspiflash_dualflexpress_divfive-p040.btor2
```

## Original Blocked Paths (Archive)

### IC3IA predicate injection

Requires `lbl2pred_` mapping to convert bitvector equality `(= state469 #b0)` → Boolean predicate label. Mapping exists but not used at injection time.

### constrain_frame() injection

Expects `IC3Formula` with Boolean children. Raw `assert_formula()` without `reset_solver()` override would be lost on reset — solved by overriding `IC3IA::reset_solver()`.

## Recommended Alternative: Offline Replay (WP5)

Still valid for impact estimation without running Pono: [`llm_worker/offline_injection_replay.py`](../llm_worker/offline_injection_replay.py).

## Deprecated Ready-to-Run Command

The env vars below were never implemented:

```bash
PONO_LLM_CONCRETE_ASSERT_LEMMAS=1 \
PONO_LLM_LEMMA_FILE=logs/formal_yield/lifted_lemma_injection_dryrun.json \
PONO_LLM_LEMMA_SUBSET=one_best_candidate
```

Use `PONO_LLM_ASSERT_LIFTED_LEMMAS` + `PONO_LLM_LEMMA_LIST` instead.
