> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# p040 Saturation Reproducibility Audit

## Verdict: `baseline_count_discrepancy_unresolved`

The artifact counts (CTIs, frame clauses) show significant variation between
runs at the same configuration (baseline, k=5):

| Run | Baseline CTIs | Baseline Frames | Notes |
|---|---|---|---|
| Run 1 (earlier) | 935 | 1934 | Original k=5 run |
| Run 2 (earlier) | 1175 | 2936 | Subsequent k=5 run |
| Run 3 (current) | 779 | 1271 | Current k=5 run |

The top_5_by_score showed -31.8% CTI reduction in Run 2, but shows +2.8%
INCREASE in Run 3. This indicates that the apparent reduction is within the
noise range of IC3IA's inherent nondeterminism.

## Root Cause

IC3IA is nondeterministic. The search path, number of refinements, and
resulting artifact counts can vary substantially between runs with
identical configuration. The initial observation of -31.8% reduction
was likely a favorable random draw, not a causal effect of the lemmas.

## Conclusion

p040 k=5 artifact counts are NOT reliable indicators of lemma injection
effect without repeated runs for statistical confidence (minimum 5-10
runs per configuration). Single-pair comparisons are misleading.

## Recommended Approach

Run 5-10 repetitions per configuration and report mean/median/min/max
artifact counts. Only then can a reliable delta be reported.
