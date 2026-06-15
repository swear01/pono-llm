> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Closed-Loop Repeatability — Extended Results

## Summary

8 total trials (3 original + 5 extended) over two sessions.

| Batch | Trials | Target Found | Verified Useful |
|---|---|---|---|
| Original (Task 74) | 3 | 1 (33%) | 1 (33%) |
| Extended (Task 75) | 5 | **4 (80%)** | **3 (60%)** |
| **Combined** | **8** | **5 (63%)** | **4 (50%)** |

## Extended Batch Details

| Trial | Time | Target Lemma | Verified Useful | Round Found |
|---|---|---|---|---|
| Trial 1 | 163s | Yes | Yes | 1 |
| Trial 2 | 277s | Yes | Yes | 1 |
| Trial 3 | 296s | No | No | — |
| Trial 4 | 155s | Yes | No | — |
| Trial 5 | 273s | Yes | Yes | 1 |

## Per-Trial Notes

### Trial 1 (163s)
Round 0: 3 candidates, all one_step_fail (state1536-based).
Round 1: LLM found `r_pipe_req => o_wb_stall` as first candidate → verified.

### Trial 2 (277s)
Round 0: 3 candidates, all one_step_fail.
Round 1: LLM found `r_pipe_req => o_wb_stall` → verified.

### Trial 3 (296s)
Round 0: 3 candidates, all one_step_fail.
Round 1: 3 candidates, all failed. Did not converge to the target lemma.

### Trial 4 (155s)
Round 0: 3 candidates, one_step_fail + some parse_failed.
Round 1: 3 candidates. Target lemma proposed but not ranked first — it was
likely validated after an earlier candidate that also failed, and the loop
stopped before reaching the useful one (or the useful one was later in the
list and not validated after an earlier solver failure).

Actually, looking more carefully: the target lemma was proposed but the loop
found it. However, the lemma was not verified as useful — this likely means
solver validation returned one_step_fail (unexpected — needs investigation).
The lemma format may have differed slightly between trials causing parse or
validation issues.

### Trial 5 (273s)
Round 0: 3 candidates, all one_step_fail.
Round 1: LLM found `r_pipe_req => o_wb_stall` → verified.

## Key Patterns

1. **Round pattern**: The target lemma always appears in round 1, never round 0.
   Counterexample feedback from round 0's state1536-based failures is
   necessary to trigger the variable shift.

2. **Success rate**: 50-63% across 8 trials. The lemma is discoverable but
   not guaranteed — there is inherent LLM variance.

3. **Latency**: 155-296s per 2-round trial. Practical for batch use.

4. **Trial 3 failure**: All candidates failed one-step. The LLM did not
   converge to the target pair within 2 rounds. Running round 3 might help.

5. **Trial 4 anomaly**: Lemma proposed but not verified useful — needs
   investigation into whether parse or solver issue.

## Recommendation

- **Production use**: Run 3-5 parallel trials and take union of results.
  Expected yield: ~1 solver-verified lemma per 3 trials.
- **Success rate could improve with**:
  - 3 rounds instead of 2 (more chances to converge)
  - Prompt guidance toward non-state1536 pairs in round 0
  - Explicit suggestion of state2002↔state790 after observing round 0 patterns
