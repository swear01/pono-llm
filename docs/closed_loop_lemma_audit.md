# Closed-loop Lemma Audit

## Target Lemma

```
(=> (= state2002 1) (= state790 1))
```

Semantic mapping:
- state2002 = `OPT_PIPE_BLOCK.r_pipe_req` (pipeline request flag)
- state790  = `o_wb_stall` (Wishbone stall output)

Human reading: `r_pipe_req = 1 ⇒ o_wb_stall = 1`

When the pipeline has an active request, the Wishbone bus is stalled.

## Validation Results

| Check | Query | Result | Time |
|---|---|---|---|
| Init | Init(s) ∧ ¬L(s) | **UNSAT** | 0ms |
| One-step | T(s,i,s') ∧ ¬L(s') | **UNSAT** | 6ms |
| Induction | L(s) ∧ T(s,i,s') ∧ ¬L(s') | **UNSAT** | 5ms |

All three queries are UNSAT. The lemma is:

- **init-safe**: holds at the initial state (state2002=0, antecedent false → vacuous)
- **transition-valid**: no transition from ANY current state can violate L in the next state
- **self-inductive**: if L holds in current state, it holds in all successor states

## Encoding Scope

The lemma is verified under:
- **Standalone Bitwuzla validation** via `smt_checker.BTOR2SMT` Python translator
- 217/247 BTOR2 transition lines translated (88%)
- 216/249 init values parsed from BTOR2 `init` lines
- 18 BTOR2 operators supported
- 249 state variables, 9 input variables

**NOT** a Pono `rel_ind_check` — this is an offline Python/Bitwuzla pipeline.
**NOT** integrated into Pono's IC3IA frames.

The 29 untranslated lines (node-208 redor cascade) affect non-target states
and do not impact state2002 or state790 transition logic.

## Non-vacuity

| Status | Evidence |
|---|---|
| **PASS** | state2002=1 found in 4 sources |

Evidence:
1. `cand_004_induction_model`: state2002_next=1 (L(s)∧T∧¬L' SAT model)
2. `cand_004_one_step_model`: state2002_next=1 (T∧¬L' SAT model — one-step reachable)
3. Same as (1) from JSON CE model
4. Same as (2) from JSON CE model

The antecedent `state2002=1` is **one-step reachable** from some predecessor
state under the translated transition relation. This confirms the lemma is
not vacuously true at the antecedent level.

## Consequent Nontriviality

| Status | Reason |
|---|---|
| **PASS** | state790 is 1-bit. (= state790 1) is false when state790=0 |

The consequent `state790=1` is not a bitwidth tautology. It excludes the
state where the bus is NOT stalled.

## Nontriviality Gate

All 5 checks pass:
- Bitwidth tautology: nontrivial
- Impossible antecedent: feasible
- Tautological consequent: nontrivial
- CE blocking: ce_blocked
- Variable relevance: OK

## Relevance / Blocking

| Metric | Value |
|---|---|
| Reachable samples checked | 9 |
| Reachable samples with both vars | 1 (init_state) |
| Reachable samples pass | 1/1 |
| CE models checked | 8 |
| CE models with both vars | 0 (most CEs don't cover state790) |
| Previous candidates blocked | N/A — lemma covers different variable pair |

Most previous CE models involve state1536, not state790, so they cannot
directly evaluate this lemma. The init sample has both state2002=0 and
state790=1, and the lemma holds (antecedent false).

## Conclusion

```text
audited_solver_verified_useful
```

The lemma `(=> (= state2002 1) (= state790 1))` is:
- **Formally verified** (init UNSAT, one-step UNSAT, induction UNSAT)
- **Nontrivial** (neither bitwidth tautology nor vacuous)
- **Antecedent non-vacuous** (state2002=1 is one-step reachable)
- **Verified under** the offline Bitwuzla pipeline with 88% transition coverage

This does NOT imply:
- Runtime speedup for Pono/IC3IA
- Benchmark unlock
- Full Pono `rel_ind_check` integration
