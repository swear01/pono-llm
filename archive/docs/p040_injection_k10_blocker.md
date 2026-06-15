> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# p040 Injection k=10 Experiment — Blocked

## Reason

p040 k=5 already takes ~3 minutes per run. k=10 would take significantly longer
(IC3IA frame count grows with k). Running baseline + 3 injection configs at k=10
would take an estimated 30-60 minutes, which exceeds the practical bound for
this session.

## What We Have at k=5

Single-run saturation experiment at k=5 observed:
- top_5_by_score: -31.8% CTIs, -26.0% frame clauses (one run vs baseline CTIs=1175)

**This is NOT established as reproducible.** Later runs show IC3IA artifact counts
vary widely at identical config (779–1175 CTIs). See
[`docs/p040_saturation_repro_audit.md`](p040_saturation_repro_audit.md) and
[`docs/reset_solver_injection_claim_boundary.md`](reset_solver_injection_claim_boundary.md).
Do not claim stable artifact reduction from injection.

## Recommended Approach

When higher-bound testing is needed:
```bash
PONO_LLM_DUMP_IC3IA=1 PONO_LLM_DUMP_DIR=logs/pono_frame_dump \
PONO_LLM_ASSERT_LIFTED_LEMMAS=1 \
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt \
build/pono -e ic3ia -k 10 qspiflash_dualflexpress_divfive-p040.btor2
```

Run overnight with `-k 10` or `-k 20` for baseline and top_5 to see if
the reduction persists at higher bounds.
