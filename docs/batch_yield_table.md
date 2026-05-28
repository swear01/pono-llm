
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
