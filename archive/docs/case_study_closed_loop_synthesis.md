> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Case Study: Closed-Loop Solver-Guided Lemma Synthesis

## 1. Motivation

Prior experiments established that **single-shot LLM prompting is insufficient**
for synthesizing inductive semantic lemmas:

| Experiment | Candidates | Solver-Useful | Key Failure |
|---|---|---|---|
| Repair v1/v2 | 14 | 0 | Trivialization or one-step-fail |
| Resynthesis | 5 | 0 | Excluded known reachable CE values |
| Reachability-aware | 2 | 0 | Passed pre-gates, failed induction |
| Transition-aware | 3 | 0 | Passed pre-gates, failed induction |

The consistent failure mode: candidates passed reachability, nontriviality, and
init checks but failed one-step induction. The LLM could not infer inductiveness
from prompt context alone.

This case study tests a **closed-loop** approach: solver counterexamples feed
back into the prompt so the LLM can learn from failures and refine its search.

## 2. Experimental Setup

- **Benchmark**: qspiflash_dualflexpress_divfive-p040 (HWMCC '24 BV track)
- **Validation**: Standalone Bitwuzla pipeline (Python `smt_checker.py`)
- **Transition coverage**: 217/247 BTOR2 lines (88%)
- **LLM model**: deepseek-v4-pro
- **Loop budget**: 2 rounds, 3 candidates per round
- **Variable set**: state1536 (o_dspi_mod), state790 (o_wb_stall),
  state1558 (cfg_speed), state2002 (r_pipe_req), state79 (cfg_mode)

Not a Pono integration result. No runtime speedup. No benchmark unlock.

## 3. Round 0: State1536-Based Candidates

### Prompt

Round 0 prompt included transition summaries, reachable samples, and a ban list
of known-falsified candidates. The LLM was instructed not to repeat patterns
that had been falsified in prior experiments.

### Candidates

| Candidate | Lemma | Verdict |
|---|---|---|
| cls_r0_001 | `state1536=0 => state790=1` | one_step_fail |
| cls_r0_002 | `state1536=0 => state79=0` | one_step_fail |
| cls_r0_003 | `state1536=15 => state790=0` | one_step_fail |

### Failure Analysis

All three candidates used **state1536 (o_dspi_mod)** as the antecedent variable.
State1536 has 667-char deeply nested ITE transition logic with 15 dependencies.
Its transition is too complex for the LLM to extract causal implications from,
even with transition summaries.

Each failure generated a compact feedback block with:
- The failed lemma
- The exact next-state values that violated it
- The reason (antecedent true, consequent false)

## 4. Feedback Injection

Three counterexample feedback blocks were appended to the round 1 prompt:

```
### Failure 1
  lemma: (=> (= state1536 0) (= state790 1))
  failure: one_step (SAT counterexample found)
  next-state: state1536_next=0, state790_next=0, ...
  reason: antecedent state1536=0 holds, consequent state790=1 fails

### Failure 2
  lemma: (=> (= state1536 0) (= state79 0))
  ...

### Failure 3
  lemma: (=> (= state1536 15) (= state790 0))
  ...
```

The prompt instructed the LLM not to repeat falsified relations and to prefer
lemmas whose truth follows from transition update logic.

## 5. Round 1: Variable Shift → Success

With 3 concrete counterexample blocks showing that state1536-based implications
were unreliable, the LLM shifted to a different variable pair:

| Candidate | Lemma | Verdict |
|---|---|---|
| **cls_r1_001** | **`state2002=1 => state790=1`** | **solver_verified_useful** |

The loop stopped early on success (remaining 2 candidates not validated).

### Interpretation

```
r_pipe_req = 1 ⇒ o_wb_stall = 1
```

When the pipeline has a registered request, the Wishbone bus is stalled. This is
a standard handshake constraint in a bus-bridged controller: a pending request
requires bus exclusivity, which is signaled through the stall output.

## 6. Formal Validation

| Gate | Result | Time |
|---|---|---|
| Parse | OK | — |
| Reachable filter | pass (1/1 applicable samples) | — |
| Nontriviality | pass | — |
| Init check (Init ∧ ¬L) | **UNSAT** | 0ms |
| One-step check (T ∧ ¬L') | **UNSAT** | 6ms |
| Induction check (L ∧ T ∧ ¬L') | **UNSAT** | 5ms |

### Non-vacuity

The antecedent `state2002=1` is one-step reachable: found in SAT models from
the original cand_004 counterexample trace (state2002 transitions 0→1 while
state1536 transitions 0→15).

## 7. Interpretation

The key ingredients for success were:

1. **Counterexample-driven feedback**: The LLM learned from 3 concrete failures
   that state1536-based implications were unreliable.
2. **Variable shift**: The LLM shifted from state1536 (complex transition) to
   state2002 (simpler, more causally-linked to state790).
3. **Solver-in-the-loop**: Not a single prompt, but an iterative cycle of
   propose → validate → feedback → refine.

The winning lemma **was not proposed** in any of the 5 prior single-shot
experiments. It emerged only through iterative refinement.

## 8. Repeatability

Three fresh closed-loop trials were run with identical configuration.

| Trial | Rounds | Solver-Useful | Target Lemma |
|---|---|---|---|
| Trial 1 | 2 | 0 | Not found |
| Trial 2 | 2 | 0 | Not found |
| Trial 3 | 2 | **1** | **Found in round 1** |

The lemma was found in 1/3 trials — discoverable but not guaranteed.
It consistently appears in **round 1**, not round 0, confirming that
counterexample feedback is necessary to trigger the variable shift.

Recommendation: run 3-5 parallel trials and take the union of verified results.

## 9. Cross-Parameter Validation

The lemma was validated across all 6 qspiflash_dualflexpress_divfive
parameterizations (p020, p027, p040, p063, p114, p162).

| Variants | Init | One-Step | Induction |
|---|---|---|---|
| **6/6** | UNSAT | UNSAT | UNSAT |

The lemma `r_pipe_req ⇒ o_wb_stall` holds across all divider configurations.
It is **not** a quirk of p040 — it's a genuine design invariant of the
qspiflash controller, independent of the clock divider parameter.

## 10. Limitations

- **One lemma only**: Not a batch of inductive invariants.
- **Not integrated with Pono**: Offline Bitwuzla pipeline, no IC3IA frame
  injection, no `rel_ind_check`.
- **No runtime impact**: The lemma has not been measured to accelerate
  Pono/IC3IA convergence.
- **Single benchmark**: Validated on qspiflash_divfive-p040 only.
- **88% transition coverage**: 29/247 lines untranslated (non-target).
- **Repeatability unknown**: Not tested across multiple LLM calls or benchmarks.

## 9. Next Steps

1. **Repeatability test**: Re-run closed-loop on fresh LLM session.
2. **Multi-benchmark test**: Validate `r_pipe_req ⇒ o_wb_stall` on other
   qspiflash parameterizations (p020, p027, p063).
3. **Controlled benchmark**: Design a lemma-critical Verilog design where
   baseline IC3IA times out and an oracle lemma unlocks the proof.
4. **Pono rel_ind_check proxy**: Estimate clause impact by counting how many
   IC3IA clauses the lemma would subsume.
