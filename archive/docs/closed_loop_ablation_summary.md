> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Closed-Loop Synthesis — Ablation Comparison

## Summary

Six experiments were run on the same benchmark (qspiflash_divfive-p040)
under the same offline Bitwuzla validation pipeline.

| # | Experiment | LLM Calls | Candidates | Pre-Gate Pass | Solver-Trivial | **Solver-Useful** | Key Failure Mode |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Repair v1 | 1 | 8 | 4 | 1 | **0** | weakening → trivialization |
| 2 | Repair v2 | 1 | 3 | 2 | 0 | **0** | still one-step-fail |
| 3 | CE-aware resynthesis | 1 | 5 | 0 | 0 | **0** | excluded known reachable CE values |
| 4 | Reachability-aware synthesis | 1 | 2 | 2 | 0 | **0** | plausible but not inductive |
| 5 | Transition-aware synthesis | 1 | 3 | 3 | 0 | **0** | plausible but not inductive |
| **6** | **Closed-loop synthesis** | **2** | **6** | **4\* (inc. 1 winner)** | **0** | **1** | — |

\*4 validated through the pipeline; 1 was reject, 1 was the winner (stopped early)

## Detailed Per-Experiment

### Experiment 1: Repair v1
- **Description**: Repair failed candidates using CE models
- **Candidates**: 8 (from 3 source failures)
- **Result**: 1 was solver-verified but downgraded to trivial:
  `state1536=0 => state1558 <= 1` (state1558 is 1-bit, `<= 1` is tautology)
- **Lesson**: Weakening can trivialize; need nontriviality gate

### Experiment 2: Repair v2
- **Description**: Repair with explicit nontriviality + CE-blocking constraints
- **Candidates**: 3 (1 per source, LLM correctly rejected 1)
- **Result**: 0 trivial, 0 useful — remaining 2 still one-step-fail
- **Lesson**: Original lemmas too far from ground truth for repair alone

### Experiment 3: CE-Aware Resynthesis
- **Description**: Synthesize new lemmas, not repair old ones
- **Candidates**: 5 (from 3 failure clusters)
- **Result**: 4/4 non-rejected candidates excluded known reachable CE values
  (e.g., `state1536 <= 14` when CE has state1536=15)
- **Lesson**: CE-only feedback causes LLM to assert CE values are impossible

### Experiment 4: Reachability-Aware Synthesis
- **Description**: Include positive reachable samples as constraints
- **Candidates**: 2
- **Result**: Both passed reachable filter + nontriviality + init, failed one-step
  (plausible relations that happen to not be inductive)
- **Lesson**: Reachable samples prevent false exclusions but don't guarantee induction

### Experiment 5: Transition-Aware Synthesis
- **Description**: Include transition slice summaries for causal reasoning
- **Candidates**: 3 (introduced novel `(or ...)` consequent pattern)
- **Result**: All 3 passed pre-gates, all failed one-step
- **Lesson**: Transition context helps structure but doesn't produce induction

### Experiment 6: Closed-Loop Synthesis
- **Description**: Iterative propose → validate → CE feedback → refine
- **Rounds**: 2 (round 0: 3 fails → round 1: 1 success)
- **Result**: `state2002=1 => state790=1` — solver_verified_useful
- **Key mechanism**: CE feedback caused LLM to abandon state1536 and shift to
  state2002/state790 — a variable pair that forms a genuine inductive invariant
- **Lesson**: Iterative solver feedback is the critical ingredient

## Key Insight

The six experiments form a clear progression:

```
Repair cannot fix fundamentally wrong lemmas.
→ Resynthesis excludes CE values without reachability context.
→ Reachability constraints prevent false exclusion but don't guarantee induction.
→ Transition context adds structure but not inductive reasoning.
→ Solver-in-the-loop iteration converges toward genuine invariants.
```

The winning lemma (`r_pipe_req ⇒ o_wb_stall`) was not proposed in any
single-shot experiment. It emerged only when the LLM received concrete
counterexample feedback showing which variable relations were unreliable.

## Architecture

The final pipeline architecture:

```
LLM propose candidates
  ↓
Gate 1: Reachable-sample filter (fast, solver-free)
  ↓
Gate 2: Nontriviality gate (fast, bitwidth analysis)
  ↓
Gate 3: Init check (light SMT)
  ↓
Gate 4: One-step check (full SMT)
  ↓
Gate 5: Induction check (full SMT)
  ↓
If SAT: extract counterexample → feed back to LLM → refine
  ↓
If UNSAT: ACCEPT (solver_verified_useful)
```
