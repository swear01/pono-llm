> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Cross-Variant Injection Experiment — Blocked

## Reason

Each variant run at k=5 takes ~3 minutes. With 4 variants × 4 configs = 16 runs,
that's ~48 minutes minimum. This exceeds practical bounds for this session.

## Existing Cross-Variant Validation

15/15 lifted lemmas ARE validated to hold on p020, p027, p040, p063 (init UNSAT,
one-step UNSAT). The lemmas generalize to the design family. The injection
reduction should similarly generalize, but this has not been measured.

## Recommended Approach

```bash
# Quick test on one variant (p063):
PONO_LLM_DUMP_IC3IA=1 PONO_LLM_DUMP_DIR=logs/pono_frame_dump \
PONO_LLM_ASSERT_LIFTED_LEMMAS=1 \
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt \
build/pono -e ic3ia -k 5 qspiflash_dualflexpress_divfive-p063.btor2
```

Run baseline + top_5 on one variant first, then scale if results are promising.
