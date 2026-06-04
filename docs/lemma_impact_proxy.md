> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Lemma Impact Proxy

**Lemma**: `(=> (= state2002 1) (= state790 1))`
**Impact**: `high_potential`

## CTI Analysis
| Metric | Count |
|---|---|
| total_ctis | 4 |
| ctis_with_state2002 | 3 |
| ctis_with_state790 | 2 |
| ctis_with_both | 2 |
| ctis_violating_lemma | 1 |
| ctis_satisfying_lemma | 1 |
| ctis_antecedent_true | 3 |
| highest_frame_any_cti | 15 |
| lemma_blocks | 1 |

## Frame Analysis
| Metric | Count |
|---|---|
| total_clauses | 3 |
| clauses_with_state2002 | 2 |
| clauses_with_state790 | 2 |
| clauses_with_both | 2 |
| potential_subsumeable | 2 |
| highest_frame_with_either | 12 |

## Notes
- CTI violation rate: 1/4 (25%)
- Clauses with both vars: 2/3 (66%)
- Lemma appears highly relevant to proof traces. Consider rel_ind_check integration.

## Interpretation
Impact: `high_potential`
