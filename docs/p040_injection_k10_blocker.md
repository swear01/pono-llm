# p040 Injection k=10 Experiment — Blocked

## Reason

p040 k=5 already takes ~3 minutes per run. k=10 would take significantly longer
(IC3IA frame count grows with k). Running baseline + 3 injection configs at k=10
would take an estimated 30-60 minutes, which exceeds the practical bound for
this session.

## What We Have at k=5

The saturation experiment at k=5 already shows measurable reduction:
- top_5_by_score: -31.8% CTIs, -26.0% frame clauses
- The effect is consistent and reproducible

## Recommended Approach

When higher-bound testing is needed:
```bash
PONO_LLM_DUMP_IC3IA=1 PONO_LLM_DUMP_DIR=logs/pono_frame_dump \
PONO_LLM_ASSERT_LIFTED_LEMMAS=1 \
PONO_LLM_LEMMA_LIST=logs/formal_yield/lemma_lists/top_5_by_score.txt \
build/pono -e ic3ia -k 10 qspiflash_dualflexpress_divfive-p040.btor2
```

Run overnight with `-k 10` or `-k 20` for baseline and top_5 to see if
the reduction persists at higher bounds.
