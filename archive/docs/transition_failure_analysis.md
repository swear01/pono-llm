> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Transition Failure Analysis

Generated from counterexample models + transition slices.

## Summary

| Candidate | Failure | CE Values | Transition Root Cause | Recommendation |
|---|---|---|---|---|
| C1: state1536=10=>state790=0 | one_step_fail | 1536=10, 790=1 | No causal link between mode and stall | reject |
| rsyn_001: state1536=15=>state2002=1 | one_step_fail | 1536=15, 2002=1 | Shared deps but 1536=15 reachable without 2002=1 | need stronger guard |
| rsyn_002: !(state1536=15&&state2002=0) | one_step_fail | 1536=15, 2002=1 | CE doesn't show violation but other transitions do | reject |

(Full analysis in JSON at `logs/formal_yield/transition_failure_analysis.json`)
