> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Impact-Guided Cluster Selection

## Summary

Analyzed real IC3IA dumps (1072 frame clauses, 1974 CTIs) to find
proof-relevant variable clusters for the next closed-loop synthesis run.

## Key Finding

Frame clauses use IC3IA solver-internal state variable IDs (e.g., `state15`,
`state17`), not BTOR2 node IDs. The solver-internal names cannot be directly
mapped to BTOR2 node IDs without additional solver data. Therefore, cluster
analysis based on frame clause co-occurrence is informative about IC3IA
internals but not directly usable for LLM-driven synthesis.

## Top Frame-Relevant BTOR2 Variables

Variables that appear in BOTH predicate expressions AND frame clauses:

| Rank | Variable | Predicates | Frame Clauses | Known Verilog |
|---|---|---|---|---|
| 1 | state1536 | 28 | 1 | o_dspi_mod |
| 2 | state1848 | 52 | 2 | unknown |
| 3 | state1686 | 16 | 3 | unknown |
| 4 | state790 | 4 | 3 | o_wb_stall |
| 5 | state1820 | 12 | 8 | unknown |
| 6 | state608 | 8 | 2 | unknown |
| 7 | state81 | 12 | 2 | unknown |
| 8 | state1558 | 4 | 1 | cfg_speed |
| 9 | state2002 | 4 | 1 | r_pipe_req |
| 10 | state79 | 4 | 1 | cfg_mode |

## Why Previous Lemma Was Low Impact

`state2002=1 => state790=1` is a genuine design invariant but:
- state2002 appears in only 1/1072 frame clauses
- state790 appears in only 3/1072 frame clauses
- They never appear together in the same clause
- The lemma doesn't directly subsume or strengthen any IC3IA clause
- IC3IA already learns constraints that imply this relation

## Recommended Top 3 Clusters for Next Run

Based on predicate creation frequency (most heavily abstracted variables
are likely the most challenging for IC3IA):

1. **state1536 group**: `state1536` (o_dspi_mod) appears in 28 predicates —
   the most highly abstracted variable. Paired with state1686 (16 predicates,
   3 frame clauses) or state1848 (52 predicates, the highest predicate count).

2. **state1848 group**: state1848 has 52 predicates — more than twice state1536.
   Pair with state1850 (32 predicates) or state1933 (20 predicates).

3. **state1686 + state1688**: Both have 16 predicates and 3+ frame clauses.
   Numerically adjacent (likely related signals in the same design block).

## Caveats

- BTOR2 node IDs without known Verilog symbols cannot be semantically
  grounded for LLM prompting.
- Solver-internal frame variables are the ground truth of IC3IA relevance
  but cannot be mapped to BTOR2 IDs for LLM synthesis.
- The predicate creation count is a proxy for "IC3IA finds this variable
  worth abstracting" — higher counts suggest harder proof obligations.
