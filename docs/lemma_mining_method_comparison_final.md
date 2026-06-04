> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Lemma Mining Method Comparison — Final

| # | Method | LLM Calls | Candidates | Verified | Cross-Variant | Impact | Mechanical | Main Failure |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Naive LLM generation | 1 | 30 | 0 | — | — | No | Correlation, not causality |
| 2 | Repair v1/v2 | 2 | 14 | 0* | — | — | No | Trivialization / too far from truth |
| 3 | Reachability-aware synthesis | 1 | 2 | 0 | — | — | No | Plausible, not inductive |
| 4 | Transition-aware synthesis | 1 | 3 | 0 | — | — | No | Better structure, still fail |
| 5 | Closed-loop synthesis | 2 | 6 | 1 | 6/6 | **low** | No | Valid but low impact |
| 6 | Impact-guided LLM | 1 | 4 | 3 | — | low | No | Higher yield, same schema issue |
| 7 | Clause-family lifting | 0 | 372 | 26 | 15/15 | low | **Yes** | 87% pass, clause-specific |
| 8 | Offline injection replay | 0 | — | — | — | **225 clauses** | Yes | Upper bound only |

*Repair v1 had 1 solver-verified but downgraded to trivial.

## Key Trends

1. **Mechanical methods outperform LLM methods** (87% vs 0-25% pass rate).
2. **Cross-variant validation** confirms lifted lemmas are design-family invariants.
3. **Impact remains the bottleneck** — even 26 verified lemmas touch only 225/1072 clauses.
4. **LLM is best for exploration** (closed-loop found the first useful lemma).
5. **Script-based lifting is best for production** (reproducible, high pass rate, zero LLM cost).

## Recommended Pipeline

```text
IC3IA trace dumps
  → clause-family lifting (mechanical, high-yield)
  → cross-variant validation
  → offline impact replay
  → select subset for injection experiment
```
