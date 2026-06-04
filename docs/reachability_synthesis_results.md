> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Reachability-Aware Synthesis Results

## Summary

| Metric | Count |
|---|---|
| Candidates generated | 2 |
| Passed reachable filter | 2 |
| Passed nontriviality | 2 |
| Passed init check | 2 |
| Passed one-step | 0 |
| Passed induction | 0 |
| Solver-inductive | 0 |

## Candidate Results

| Candidate | Lemma | Schema | Reachable | Nontrivial | Init | One-Step | Induction | Verdict |
|---|---|---|---|---|---|---|---|---|
| rsyn_001 | `state1536=15 => state2002=1` | guarded_implication | pass | pass | UNSAT | SAT | SAT | one_step_fail |
| rsyn_002 | `!(state1536=15 && state2002=0)` | mutual_exclusion | pass | pass | UNSAT | SAT | SAT | one_step_fail |

## Interpretation

The reachability-aware synthesis produced 2 candidates. Both pass the first
three gates (reachable filter + nontriviality + init) — a significant
improvement over previous synthesis runs where candidates failed at the
reachable-consistency stage.

Both candidates propose a relation between state1536=15 (DSPI request-active
mode) and state2002=1 (pipeline request flag). The LLM correctly observed
that in all known reachable samples, state1536=15 is paired with state2002=1,
and proposed two formulations of this relation.

However, both fail one-step checks because the transition system can reach
states where state1536=15 but state2002=0 (or != 1). This demonstrates that:

1. **Reachable-constrained synthesis works** — no candidates contradict known samples
2. **Reachable samples alone insufficient** — inductiveness requires seeing
   the full transition relation, not just positive examples
3. **Gating order is validated** — reachable filter catches doomed candidates
   before SMT, but non-inductive candidates still require full solver checks

## Comparison: Three Synthesis Experiments

| Experiment | Candidates | Passed Reachable | Passed Init | Solver-Inductive |
|---|---|---|---|---|
| Repair v1 (CE feedback) | 8 | 4 | 3 | 0\* |
| Resynthesis (CE + var context) | 5 | 0 | 4 | 0 |
| **Reachability-aware** | **2** | **2** | **2** | **0** |

\*One was solver-verified but downgraded to trivial by nontriviality gate.

## Pipeline Architecture

```
Candidate → Gate 1 (reachable filter) → Gate 2 (nontriviality) → Gate 3 (init) → Gate 4 (one-step) → Gate 5 (induction) → ACCEPT
```

| Gate | Type | Cost | Example catch |
|---|---|---|---|
| Reachable filter | Concrete eval | Zero | `state1536 <= 14` when sample has 15 |
| Nontriviality | Bitwidth analysis | Zero | `(<= state1558 1)` when state1558 is 1-bit |
| Init check | Light SMT | Low | Reversed implication failing at reset |
| One-step | Full SMT | High | Plausible but non-inductive relations |
| Induction | Full SMT | Highest | Most expensive, only for one-step passers |
