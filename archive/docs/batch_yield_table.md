> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).


## Post-fix Batch Generation Verified

After fixing prompt contract and parser pipeline, batch generation is confirmed real:

| Prompt | Candidates | Parse | Schema types | Multi-var | Trivial |
|--------|-----------|-------|-------------|-----------|---------|
| v1 strict | 10 | 100% | 7 | 60% | 0 |
| v2 semantic | 20 | 100% | 6 | 50% | 0 |
| **Total** | **30** | **100%** | **7** | **53%** | **0** |

Conclusion: The earlier single-candidate-per-call result was caused by pipeline bugs
(prompt format + JSON parsing + reader single-line read), not an LLM limitation.

See `docs/formal_yield_table.md` for formal verification yield analysis.
