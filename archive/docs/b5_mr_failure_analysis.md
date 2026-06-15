> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# B5-MR Failure Analysis

## Status

After context was unlocked (39 refinements, 3 context dumps), B5-MR
repair was attempted but produced 0 new valid repair predicates.

## Failure Classification

| Category | Status |
|---|---|
| Candidate generation | Unknown (logging gap) |
| Parse/type | Unknown |
| Duplicate check (bootstrap) | Unknown |
| Duplicate check (interpolant) | Unknown |
| Path implication | Unknown |
| Solver rejection | Likely (no valid results) |
| Too strong/weak | Unknown |

## Likely Root Cause

Without detailed per-candidate logging, the exact failure mode cannot
be determined. Possible causes:

1. **LLM generated predicates already in bootstrap set** — duplicates
   rejected before reaching solver.

2. **LLM predicates too strong** — fail path implication (not implied
   by the spurious trace).

3. **LLM predicates too weak** — fail to refine the abstraction.

4. **LLM output format mismatch** — parse or type failures silently
   rejecting candidates.

## Logging Gaps

See `docs/context_unlock_logging_gaps.md` for the full list of
needed logging fields that are currently unavailable.

## Next Step

Add per-candidate logging for parse, type, path-implication, duplicate,
and solver-rejection status. Re-run B5-MR with logging enabled to
determine which failure mode dominates.
