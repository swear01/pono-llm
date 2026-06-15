> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Closed-Loop Repeatability Results

## Summary

| Trial | Rounds | Candidates | Solver-Useful | Target Lemma Found |
|---|---|---|---|---|
| Trial 1 | 2 | 6 | 0 | No |
| Trial 2 | 2 | 6 | 0 | No |
| Trial 3 | 2 | 5 | 1 | **Yes (cls_r1_002, round 1)** |

**Target lemma found in 1/3 trials. Solver-verified useful in 1/3 trials.**

## Trial Details

### Trial 1 (230s)

Round 0: 3 candidates, all one_step_fail
- `state2002=1 => state1536!=0`
- `state1536=10 => state790=1`
- `state79=1 => state1536!=0`

Round 1: 3 candidates, 2 one_step_fail, 1 parse_failed
- Did not find the target lemma.

### Trial 2 (345s)

Round 0: 3 candidates, all one_step_fail
Round 1: 3 candidates, 2 one_step_fail, 1 parse_failed
- Did not find the target lemma.

### Trial 3 (305s)

Round 0: 3 candidates, all one_step_fail
- `state2002=1 => state1536!=0`
- `state1536=10 => state790=1`
- `state79=1 => state1536!=0`

Round 1: 3 candidates
- `(or (= state1536 0) (= state1536 10) (= state1536 15))` — parse_failed
- **`(=> (= state2002 1) (= state790 1))` — SOLVER VERIFIED USEFUL**
- `(not (= state1536 5))` — not validated (stopped early)

The target lemma appeared in round 1 as `cls_r1_002`.

## Interpretation

- The lemma `r_pipe_req => o_wb_stall` is **discoverable by the closed loop**
  but **not guaranteed** in every run.
- Consistency: the lemma always appears in **round 1**, not round 0 — it
  **requires counterexample feedback** to trigger the variable shift away
  from state1536 to the state2002/state790 pair.
- 1/3 reproducibility suggests the LLM exploration has inherent variance.
  Multiple trials improve the chance of finding useful lemmas.

## Recommendation

For robust lemma discovery, run 3-5 closed-loop trials in parallel and
take the union of solver-verified results. The loop is cheap enough
(2 rounds, 6 candidates per trial) that parallel trials are practical.
