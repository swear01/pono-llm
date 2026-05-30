# Top Lifted Lemma Audit Pack

## Summary

5 selected lemmas across different injection subsets.

| Lemma | Source Frame | Init | One-Step | Induction | Cross-Variant | Subset |
|---|---|---|---|---|---|---|
| state469=0 ∧ state471=0 ⇒ state15=0 | 2 | UNSAT | UNSAT | UNSAT | 4/4 | one_best |
| state469=0 ∧ state497=0 ⇒ state15=0 | 2 | UNSAT | UNSAT | UNSAT | 4/4 | top_5 |
| state455=0 ∧ state457=0 ⇒ state15=0 | 2 | UNSAT | UNSAT | UNSAT | 4/4 | top_5 |
| state462=0 ∧ state464=0 ⇒ state15=0 | 2 | UNSAT | UNSAT | UNSAT | 4/4 | diverse_5 |
| state15=0 ∧ state17=0 ⇒ state552=0 | 2 | UNSAT | UNSAT | UNSAT | 4/4 | top_5_state15 |

## Detailed Audit: state469=0 ∧ state471=0 ⇒ state15=0

| Check | Result | Time | Notes |
|---|---|---|---|
| Parse | OK | — | Conjunction antecedent, 2 variables |
| Reachable filter | pass | — | No applicable samples |
| Nontriviality | pass | — | Not a bitwidth tautology |
| Init (Init ∧ ¬L) | UNSAT | 0ms | Holds at reset |
| One-step (T ∧ ¬L') | UNSAT | ~5ms | Transition cannot violate |
| Induction (L ∧ T ∧ ¬L') | UNSAT | ~5ms | Self-inductive |
| Cross-variant | 4/4 pass | — | p020, p027, p040, p063 |

**Source clause**: Lifted from IC3IA frame clause 2-literal OR form.

**Meaning**: From `(NOT state469) OR (NOT state471) OR state15`, lifted to
`(state469 AND state471) ⇒ state15=0`. IC3IA is trying to prove that when
both state469 and state471 are satisfied, state15 is forced to 0.

**Offline replay**: Touches 23 strongly overlapping clauses, 439 overlapping
clauses across frames 2-3.

**Injection recommendation**: Include in `one_best_candidate` subset for a
minimal smoke test.
