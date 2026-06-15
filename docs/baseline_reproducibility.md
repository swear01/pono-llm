> **ACTIVE for v1 (2026-06-03)** — IC3IA nondeterminism affects E2E metrics design.  
> Spec: [`ARCHITECTURE.md`](ARCHITECTURE.md)

# Baseline Reproducibility

## Seed 42, k=5, 3 repetitions each

| Rep | Baseline CTIs | Baseline Frames | Top5 CTIs | Top5 Frames |
|---|---|---|---|---|
| 1 | 944 | 944 | 1354 | 2231 |
| 2 | 1119 | 2130 | 819 | 818 |
| 3 | 855 | 854 | 903 | 1156 |

| Metric | Baseline CTIs | Baseline Frames | Top5 CTIs | Top5 Frames |
|---|---|---|---|---|
| Mean | 973 | 1309 | 1025 | 1402 |
| Min | 855 | 854 | 819 | 818 |
| Max | 1119 | 2130 | 1354 | 2231 |
| Range | 264 | 1276 | 535 | 1413 |
| Top5 — Baseline | — | — | **+52** | **+93** |

## Verdict: `high_variance_counts`

With seed 42 and 3 repetitions, the distributions of CTI and frame counts
overlap heavily. Top5 shows a HIGHER mean CTI count (+52) than baseline.
The ranges overlap completely (819-1354 vs 855-1119).

**No reliable artifact reduction can be claimed from this data.**

The earlier -31.8% observation was a single-run favorable draw, not a
reproducible effect of the injected lemmas.

## Required for Future Claims

- Minimum 5-10 repetitions per configuration
- Multiple seeds (0, 1, 2, 42)
- Statistical test (Wilcoxon or t-test)
- Higher k (10+) to reduce relative variance
