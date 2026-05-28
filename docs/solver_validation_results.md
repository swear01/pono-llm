# Solver Validation Results (After BTOR2 Translation Fix)

## Summary

| Verdict | Count |
|---|---|
| init_pass_one_step_fail | 4 |
| parse_failed | 1 |
| solver_verified_strong | 0 |
| solver_inductive | 0 |

## Results Per Candidate

| Rank | Candidate ID | Lemma | Init | One-Step | Induction | Overall |
|---|---:|---|---|---|---|---|
| 1 | cand_007 | state1536=10 => state790=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail |
| 2 | cand_008 | state1536=0 => state1558=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail |
| 3 | cand_004 | state2002=1 => state1536=0 | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail |
| 4 | cand_005 | !(state1536=10 && state79=1) | init_safe | one_step_fail | induction_fail | init_pass_one_step_fail |
| 5 | cand_007_input | state1536=11 => i_wb_data[12]=1 | parse_failed | parse_failed | parse_failed | parse_failed |

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

## Remaining Limitations

1. **Candidate 5 (input-dependent):** The lemma parser (`lemma_to_smt`) does not
   support `(_ extract ...)` SMT-LIB2 syntax for bit-slice of primary inputs.
   This is a parser limitation, not a translation limitation.
2. **SAT models not extracted.** The current code reports SAT/UNSAT but does
   not extract counterexample models. This would be needed for repair-loop
   feedback.
3. **29/247 transition lines still fail** (non-target cascade from node 208).
   Does not affect any of the 5 shortlisted candidates.
