> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Cross-Variant Lifted Lemma Validation

## Validation Table

15/15 lifted lemmas validated on 4 qspiflash variants.

| Lemma (abbreviated) | p020 | p027 | p040 | p063 |
|---|---|---|---|---|
| (state469=0 AND state471=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state469=0 AND state497=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state469=0 AND state636=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state469=0 AND state872=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state469=0 AND state879=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state455=0 AND state457=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state462=0 AND state464=0) => state15=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state17=0) => state552=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state469=0) => state471=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state469=0) => state497=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state469=0) => state636=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state469=0) => state872=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state552=0) => state17=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state367=0) => state369=0 | ✓ | ✓ | ✓ | ✓ |
| (state15=0 AND state369=0) => state367=0 | ✓ | ✓ | ✓ | ✓ |

✓ = init UNSAT, one-step UNSAT
All state IDs stable across variants (same BTOR2 encoding).

## Slide-Ready Summary

- 15/15 lifted lemmas pass across 4 qspiflash divider variants
- State IDs consistent — no remapping needed
- Lifting produces design-family invariants, not p040-specific artifacts
