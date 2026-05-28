# Solver Validation Results (After BTOR2 Translation Fix)

## Summary

| Verdict | Count |
|---|---|
| init_pass_one_step_fail | 4 |
| parse_failed | 1 |
| solver_verified_strong | 0 |
| solver_inductive | 0 |

## Results Per Candidate

| Rank | Candidate ID | Lemma | Init | One-Step | Induction | Overall | Failure Class |
|---|---:|---|---|---|---|---|---|
| 1 | cand_007 | state1536=10 => state790=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail | overstrong_implication |
| 2 | cand_008 | state1536=0 => state1558=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail | overstrong_implication |
| 3 | cand_004 | state2002=1 => state1536=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail | overstrong_implication |
| 4 | cand_005 | !(state1536=10 && state79=1) | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail | reachable_forbidden_mode |
| 5 | cand_007_input | state1536=11 => i_wb_data[12]=1 | parse_failed | parse_failed | parse_failed | parse_failed | n/a |

## Counterexample Models (2026-05-29)

SAT counterexample models were extracted for all 4 state-only candidates.
See `docs/solver_counterexample_analysis.md` for full details.

### Candidate 1: state1536=10 => state790=0

- **CE**: state1536 transitions 0→10, state790 transitions 0→1
- **Violation**: consequent expects state790=0 but gets 1 (stall IS active when mode=10)
- **Failure**: overstrong_implication — consequent value is wrong
- **Repair hints**: reverse implication or weaken consequent

### Candidate 2: state1536=0 => state1558=0

- **CE**: state1536 stays 0, state1558 transitions 0→1 (via i_cfg_stb=1)
- **Violation**: cfg_speed can be 1 even when mode=0 (IDLE)
- **Failure**: overstrong_implication — cfg_speed independently controlled
- **Repair hints**: add i_cfg_stb guard or reject

### Candidate 3: state2002=1 => state1536=0

- **CE**: state2002 transitions 0→1, state1536 transitions 0→15
- **Violation**: consequent expects state1536=0 but gets 15
- **Failure**: overstrong_implication — mode is non-zero when request active
- **Repair hints**: reverse consequent to != 0 or mode range constraint

### Candidate 4: !(state1536=10 && state79=1)

- **CE**: both state1536=10 AND state79=1 simultaneously reachable
- **Violation**: mutex is false — both conditions co-occur in real design
- **Failure**: reachable_forbidden_mode
- **Repair hints**: reject (co-occurrence is valid design behavior)

## Repair Prompt

A batch repair prompt was built at `logs/formal_yield/repair_batch_prompt.txt`
with counterexample models and repair hints for candidates 1-3 (candidate 4
classified as reject). LLM repair batch is pending (API key needed).

## Interpretation

All 4 state-only candidates pass init checks (UNSAT) — they hold at the reset
state. However, they all fail one-step transition checks (SAT) — there exist
reachable states where the lemma does NOT hold.

This confirms:
1. **Translation pipeline works.** Init, one-step, and induction queries
   generate and run without BTOR2 translation errors for state-only candidates.
2. **LLM-proposed lemmas are init-safe but too strong.** They are violated by
   some transition paths. This is the expected starting point for the repair
   loop.
3. **Solver output provides concrete counterexample info** (SAT model) that can
   feed back to the LLM repair step.
4. **SAT model extraction works** using `bz.Option.PRODUCE_MODELS`.

## Remaining Limitations

1. **Candidate 5 (input-dependent):** The lemma parser (`lemma_to_smt`) does not
   support `(_ extract ...)` SMT-LIB2 syntax for bit-slice of primary inputs.
2. **LLM repair batch not yet run:** API key not available in this session.
   Repair prompt is ready at `logs/formal_yield/repair_batch_prompt.txt`.
3. **29/247 transition lines still fail** (non-target cascade from node 208).
   Does not affect any of the 5 shortlisted candidates.
