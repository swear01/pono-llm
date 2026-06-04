> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Repair v2 Results — Nontriviality-Constrained Repair

## Motivation

Repair v1 produced 8 repairs. One (cand_008_repair_2) passed all solver checks
but was downgraded to `solver_verified_trivial` because `state1558` is 1-bit,
making `(<= state1558 1)` trivially true. This revealed a systematic weakness:
the naive repair prompt allowed the LLM to weaken lemmas into vacuous tautologies.

Repair v2 strengthens the prompt with explicit nontriviality and
counterexample-blocking constraints.

## Prompt Changes

| Constraint | Rationale |
|---|---|
| Ban `(<= x N)` for 1-bit vars (any bound is trivial) | Prevents the v1 tautology |
| Ban `(<= x N)` where `N >= 2^w-1` | Bitwidth tautology |
| Require CE-blocking explanation | Forces LLM to check against CE values |
| Bitwidth info provided per variable | LLM knows exact value ranges |
| "reject" as a valid strategy | OK to say the candidate is unsalvageable |

## Results

| Repair ID | Lemma | Strategy | Init | One-Step | Induction | Gate Verdict |
|---|---|---|---|---|---|---|
| cand_007_repair_v2_1 | `(=> (= state1536 10) (= state790 1))` | schema_change | UNSAT | SAT | SAT | init_pass_one_step_fail |
| cand_008_repair_v2_1 | `reject` | reject | — | — | — | rejected_by_llm |
| cand_004_repair_v2_1 | `(=> (= state2002 1) (not (= state1536 0)))` | schema_change | UNSAT | SAT | SAT | init_pass_one_step_fail |

**Summary**: 0 solver_verified_useful, 2 init_pass_one_step_fail, 1 rejected_by_llm.

### Cand 008: Correctly Rejected

The LLM **correctly rejected** cand_008 (cfg_speed vs mode relation) as unsalvageable:

> "The CE shows mode=0 and cfg_speed=1 is reachable. No nontrivial state-only
> implication between these signals that holds in all reachable states can be
> deduced. Adding a guard on transient inputs (e.g., i_cfg_stb) is not permissible
> for a state invariant."

This is the right behavior — the LLM recognized that cfg_speed is independently
controlled and no meaningful state invariant exists between these two signals.

### Cand 007 and Cand 004: Still One-Step-Fail

Both repairs are reasonable (nontrivial, block the CE) but fail the one-step
transition check. The LLM proposed:

- Cand 007: weaken consequent from `state790=0` to `state790=1` (matches CE)
- Cand 004: weaken consequent from `state1536=0` to `state1536 != 0` (mode non-zero when request active)

Both are nontrivial — neither is a bitwidth tautology. But both fail because
the transition system can reach states where the new consequent is also false
(e.g., state1536=10 with state790=0 for cand_007, or state2002=1 with state1536
being some non-15 value for cand_004).

## Interpretation

The repair-v2 prompt successfully prevented trivialization:
- No bitwidth tautologies were produced
- The LLM correctly rejected an unsalvageable candidate
- The remaining repairs are nontrivial but still fail one-step checks

The fundamental challenge is that the **original LLM proposals were too far from
correct** — they asserted consequent values that don't match system behavior at
all. Within the constraint of using only the original lemma variables, the LLM
cannot find a nontrivial inductive reformulation.

This supports the hypothesis that **repair alone is insufficient** when the
original proposals are poor. Better lemma quality at generation time (stronger
synthesis rather than weaker repair) would produce starting points that are
closer to correct, making repair more productive.

## Comparison: Repair v1 vs v2

| | Repair v1 | Repair v2 |
|---|---|---|
| Repairs generated | 8 (3 per candidate) | 3 (1 per candidate, more selective) |
| Trivial lemmas | 1 (bitwidth tautology) | 0 |
| Rejections | 2 (repeated original) | 1 (explicit reject with reasoning) |
| Solver-verified | 1 (downgraded to trivial) | 0 |
| Nontrivial but failed | 3 | 2 |

The v2 prompt reduced trivial responses but couldn't overcome the fundamental
distance between original proposals and ground truth.

## Recommended Next Steps

1. **Stronger synthesis, not weaker repair**: Instead of repairing overstrong
   lemmas, generate lemmas that are *weaker but causal* from the start (e.g.,
   ask LLM to rank candidate confidence and only propose low-risk relations).
2. **Multi-variable with context**: Include more transition-context variables
   in the repair scope rather than restricting to original lemma vars.
3. **BMC intermediate check**: Add a bounded model check (depth 2-3) between
   parse and full induction to catch obviously false lemmas earlier.
