> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Formal Yield Table

## Summary

| Metric | Value |
|---|---|
| Total candidates | 30 |
| Parse valid | 30 (100%) |
| Unique | 29 |
| Schema types | 7 |
| Multi-var | 16 (53%) |
| analytically verified | 1 |
| promising | 19 |
| needs solver | 9 |
| rejected trivial | 1 |

## Schema Distribution

| Schema | Count |
|---|---|
| range | 7 |
| disequality | 7 |
| guarded_implication | 7 |
| mutual_exclusion | 4 |
| equality | 2 |
| mode_implication | 2 |
| offset | 1 |

## Verdict Distribution

| Verdict | Count |
|---|---|
| promising | 19 |
| needs_solver | 9 |
| analytically_verified | 1 |
| rejected_trivial | 1 |

## Interpretation

Task 59 measures formal-gate readiness, not proof impact. Analytical checks are intentionally conservative.
1 candidates analytically verified.

## Solver Validation (Tasks 61-62)

5 candidates shortlisted for Bitwuzla-backed validation:

| Candidate | Init | One-step | Induction | Verdict |
|---|---|---|---|---|
| 1: `state1536=10 => state790=0` | UNSAT | blocked | blocked | init_pass_induction_blocked |
| 2: `state1536=0 => state1558=0` | UNSAT | blocked | blocked | init_pass_induction_blocked |
| 3: `state2002=1 => state1536=0` | UNSAT | blocked | blocked | init_pass_induction_blocked |
| 4: `!(state1536=10 && state79=1)` | UNSAT | blocked | blocked | init_pass_induction_blocked |
| 5: `state1536=11 => i_wb_data[12]=1` | blocked | blocked | blocked | mapping_blocked |

All 4 state-only candidates are init-safe. Transition checks blocked: Python
`BV_EXTRACT` rejects BTOR2 `slice` indices. Fix is the next priority.

See `docs/solver_validation_results.md` and `docs/mapping_spike_solver_shortlist.md`.
