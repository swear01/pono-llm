# Closed-loop Solver-Guided Synthesis Results

## Summary

| Metric | Value |
|---|---|
| Rounds run | 2 |
| Total candidates generated | 6 |
| Total validated | 4 |
| **Solver-verified useful** | **1** |
| One-step failures | 3 |
| Nontriviality failures | 0 |
| Reachable violations | 0 |
| Init failures | 0 |
| LLM rejections | 0 |

## Per-Round Results

| Round | Candidates | Best Verdict | Feedback Added |
|---|---|---|---|
| R0 | 3 | one_step_fail | 3 CE blocks (state1536-based lemmas all fail) |
| R1 | 3 | **solver_verified_useful** | — (stopped on success) |

## Solver-Verified Useful Lemma

| Candidate | Lemma | Init | One-Step | Induction |
|---|---|---|---|
| **cls_r1_001** | `(=> (= state2002 1) (= state790 1))` | UNSAT | UNSAT | UNSAT |

**Interpretation**: `r_pipe_req=1 ⇒ o_wb_stall=1` — when the pipeline has
an active request, the Wishbone bus is stalled. This is a genuine state
invariant of the qspiflash controller: pipeline requests require bus
exclusivity, expressed as a stall signal.

## How Feedback Improved Candidates

### Round 0: All State1536-Based Failures

| Candidate | Lemma | Verdict |
|---|---|---|
| cls_r0_001 | `state1536=0 => state790=1` | one_step_fail |
| cls_r0_002 | `state1536=0 => state79=0` | one_step_fail |
| cls_r0_003 | `state1536=15 => state790=0` | one_step_fail |

All three failed because state1536 (o_dspi_mod) has complex transition logic
that doesn't form simple implications with these consequent variables.

### Feedback to LLM

Three compact counterexample blocks showing:
- Exact next-state values that violated each lemma
- That state1536-based implications are unreliable
- That the transition relation doesn't support simple mode→flag implications

### Round 1: Shifted to New Variable Pair

The LLM learned from the feedback and proposed:
- **`state2002 => state790`** — NOT using state1536 at all!
- This is a different variable pair (r_pipe_req → o_wb_stall) that forms
  a genuine inductive invariant.

## Comparison to Previous Experiments

| Experiment | Rounds | Solver-Inductive |
|---|---|---|
| Repair v1 | 1 (fixed prompt) | 0 useful |
| Repair v2 | 1 (fixed prompt) | 0 useful |
| Resynthesis | 1 (fixed prompt) | 0 useful |
| Reachability-aware | 1 (fixed prompt) | 0 useful |
| Transition-aware | 1 (fixed prompt) | 0 useful |
| **Closed-loop** | **2** | **1 useful** |

The closed-loop approach is the only experiment that produced a
`solver_verified_useful` lemma.

## Key Insight

**Single-shot synthesis is insufficient.** The LLM needs iterative feedback
to converge toward genuine invariants. The closed-loop approach allows the
LLM to learn from failures, shift variable focus, and find relations that
are not obvious from a single prompt.

The winning lemma (`state2002 => state790`) was NOT proposed in any of the
5 previous single-shot experiments — it emerged only through iterative
refinement guided by counterexample feedback.

## Pipeline Pattern

```text
LLM propose
  → reachable filter (fast rejection)
  → nontriviality gate (fast rejection)
  → init check (light SMT)
  → one-step check (full SMT)
  → induction check (full SMT)
  → if fail: extract counterexample, feed back to LLM
  → LLM refine with new context
  → repeat until useful or exhausted
```

## Remaining Limitations

- Only one useful lemma found (not a batch of inductive invariants)
- State1536 remains difficult — its transition logic is too complex for
  LLM to reason about causally
- The loop converged by shifting away from state1536, which may not be
  viable for all benchmar contexts
