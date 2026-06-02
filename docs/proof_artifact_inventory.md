# Proof Artifact Inventory

## Summary

All core proof artifacts are available for the qspiflash_divfive-p040 benchmark.

| # | Artifact Source | Type | Count | Usable |
|---|---|---|---|---|
| 1 | `qspiflash_p040_predicates.jsonl` | Predicate map | 245 | Yes |
| 2 | `qspiflash_p040_ctis.jsonl` | CTI dumps | 935 | Yes |
| 3 | `qspiflash_p040_frames.jsonl` | Frame clauses | 1072 | Yes |
| 4 | `state15_clause_families.json` | Clause families | 14 families | Yes |
| 5 | `clause_templates.json` | Template dist | 7 templates | Yes |
| 6 | `state15_lifted_candidates.json` | Lifted lemmas | 372 | Yes |
| 7 | `state15_lifted_validation_top50.json` | Validated lifted | 30 | Yes |
| 8 | Parallel sampling failed | Failed candidates | 56 | Yes |
| 9 | Transition slices | Explainability | 5 vars | Partial |

## Key Artifacts for Generalization

### Frame Clauses (1072)
Multi-literal OR clauses from IC3IA frames. 603 ternary (3-literal), 283 binary.
These are the primary generalization source — each clause encodes a local proof
step that can be lifted or generalized.

### State15 Clause Families (14 families)
Grouped by satellite variables. Dominant: ternary_2sats (289 clauses).
Each family shares core variables (state15, state17) with varying satellites.

### Lifted Lemmas (30 validated, 26 verified)
Mechanical clause lifting: OR → implication form. 87% verification rate.
All are proof-local (cover only source clause). Ready for family generalization.

### Failed Parallel Sampling (56 unique)
Results from think-none free-form sampling. 0% verification rate.
Provides concrete examples of unsupported syntax and nontriviality failures.

### Predicate Map (245)
Label-to-expression mapping. Required for resolving frame literals.
