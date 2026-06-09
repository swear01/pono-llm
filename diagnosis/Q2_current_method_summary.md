# Q2 current-method smoke diagnosis

Runs analyzed: **6**
Aggregate accept/API: **13.1%** (8/61)
rejected_initial feedback entries: **45**

## Init-semantics taxonomy (Q2 smoke)

- B2 (CTI/init mismatch): **100.0%**
- C2 (OR sibling at init): **0%**
- B1 (clause equals init): **0%**
- A (witness not in failed clause): **0%**

## Response shape

- Mean MIC top-1 shape match: **0.0%**
- Mean single-disjunct clauses: **100.0%**
- Mean CTI-literal copy in disjuncts: **98.4%**

## Interpretation

- **B2 still dominant** after Q2.1: model copies CTI-shaped literals that fail init witness check → Q3.1 witness templates + Q3.2 digest-negate.
- **Low MIC alignment**: blocks rarely match mechanical digest-negate top-1 → Q3.2.

## Per-run

- `A1_q2_r1`: accept/API 22.2% (RI taxonomy n=5)
- `A1_q2_r2`: accept/API 10.0% (RI taxonomy n=7)
- `A1_q2_r3`: accept/API 20.0% (RI taxonomy n=8)
- `A3_combined_r1`: accept/API 9.1% (RI taxonomy n=8)
- `A3_combined_r2`: accept/API 20.0% (RI taxonomy n=7)
- `A3_combined_r3`: accept/API 0.0% (RI taxonomy n=10)
