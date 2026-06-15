> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Repaired Solver Validation Results

## Summary

| Verdict | Count |
|---|---|
| solver_verified_strong | 1 |
| init_pass_one_step_fail | 3 |
| init_fail | 1 |
| parse_failed | 1 |

## Results Per Repair

| Repair ID | Lemma | Source | Strategy | Init | One-Step | Induction | Verdict |
|---|---|---|---|---|---|---|---|
| cand_007_repair_1 | (=> (= state790 1) (= state1536 10)) | C1 | reverse_implication | SAT | SAT | SAT | init_fail |
| cand_007_repair_2 | (=> (= state1536 10) (= state790 1)) | C1 | weaken | UNSAT | SAT | SAT | init_pass_one_step_fail |
| cand_008_repair_1 | (=> (and ... (not i_cfg_stb)) ...) | C2 | add_guard | — | — | — | parse_failed |
| **cand_008_repair_2** | **(=> (= state1536 0) (<= state1558 1))** | C2 | **weaken** | **UNSAT** | **UNSAT** | **UNSAT** | **solver_verified_strong** |
| cand_004_repair_1 | (=> (= state2002 1) (not (= state1536 0))) | C3 | weaken | UNSAT | SAT | SAT | init_pass_one_step_fail |
| cand_004_repair_2 | (=> (= state2002 1) (>= state1536 10)) | C3 | schema_change | UNSAT | SAT | SAT | init_pass_one_step_fail |

## cand_008_repair_2 Analysis

The repaired lemma `(=> (= state1536 0) (<= state1558 1))` passed all three
checks:
- Init: UNSAT (state1536=0, state1558=0 satisfies the implication)
- One-step: UNSAT (no transition can produce state1536=0 AND state1558>1)
- Induction: UNSAT (lemma is self-inductive)

**However**: state1558 (`cfg_speed`) has bitwidth 1. A 1-bit value satisfies
`<= 1` trivially (possible values are 0 and 1). So this lemma is a **tautology**
— it is formally correct but semantically vacuous. It does not constrain the
state space in any useful way.

This illustrates a known challenge in lemma repair: **weakening can trivialize**.
The repair strategy correctly identified that the original lemma was overstrong,
but the weakened version provides no useful constraint.

## Other Repair Observations

- **cand_007_repair_1** (reverse implication): Init-fails because init has
  state790=1 but state1536=0, not 10.
- **cand_007_repair_2** (weakened consequent to state790=1): Still one-step-fails
  — there exist transitions where state1536=10 but state790=0.
- **cand_004_repair_1** (mode != 0): One-step-fails — mode=15 satisfies != 0
  but the counterexample shows mode=15 is reachable when request=1. The lemma
  is true but this was the expected counterexample path.
- **cand_004_repair_2** (mode >= 10): One-step-fails — mode can be < 10 when
  request is active in some transitions.

## Comparison to qspiflash Case Study

The qspiflash case study succeeded because the original lemma was **close to
correct** — just init-failing but transition-valid. The repair (equality →
mutex) preserved a meaningful semantic constraint.

In this batch, the original lemmas were **farther from correct** — they asserted
consequent values that don't match system behavior at all. The repair strategies
could not find a nontrivial inductive reformulation within the constraint of
using only the lemma variables.

## Added Lemma Parser Patterns

| Pattern | Example | Status |
|---|---|---|
| guarded implication | `(=> (= X V) (= Y W))` | supported |
| negated consequent | `(=> (= X V) (not (= Y W)))` | added |
| upper bound consequent | `(=> (= X V) (<= Y W))` | added |
| lower bound consequent | `(=> (= X V) (>= Y W))` | added |
| compound antecedent | `(=> (and ... input ...) ...)` | not supported (parse failed) |
