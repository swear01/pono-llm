> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# BTOR2 Transition Translation Triage

## Summary

| Metric | Before Fix | After Fix |
|---|---:|---:|
| Total transition lines | 247 | 247 |
| Translated | 121 (49%) | **218 (88%)** |
| Failed | 126 (51%) | 29 (12%) |

All 5 solver-validation shortlisted candidates now have their target state
transitions fully translated.

## Failure Types (After Fix)

| Error Type | Count | Example Node | Example Message |
|---|---|---|---|
| unknown (redor cascade) | 29 | node 208 | redor child concat fails — non-target states only |

All remaining failures are cascades from a single node: **208** (`redor 1 207`,
where 207 = `concat 104 206 205`). This affects 10 non-target state transitions
(states 367-1382). No solver-validation candidate depends on node 208.

## Root-Cause Bugs Fixed

| Bug | Location | Fix |
|---|---|---|
| slice out-of-range | `smt_checker.py:164` | Zero-extend source before extracting out-of-range bits, per BTOR2 semantics |
| uext source indexing | `smt_checker.py:186` | Changed `t(p[3])` → `t(p[2])`; expression source was indexed incorrectly |
| eq/ult/ulte Boolean→BV | `smt_checker.py:156-170` | BTOR2 `eq`/`ult`/`ulte` return 1-bit BV; Bitwuzla `EQUAL`/`BV_ULT` return Boolean. Added `_mk_bv1()` to convert via ITE(cond, 1, 0) |

### Bug Detail: slice OOB

BTOR2 allows `slice [hi:lo]` where `hi >= source_width`. Out-of-range bits are
defined as zero. Previously our translator rejected these, silently returning
`None`. Fix: zero-extend source to `hi+1` bits, then extract normally.

### Bug Detail: uext source indexing

Old code: `a = t(p[3] if len(p) > 3 else p[2])` — `p[3]` is the extension
width, not a node reference. Fixed to `a = t(p[2])` for the correct source node.

### Bug Detail: Boolean/BV mismatch

BTOR2 `eq`, `ult`, `ulte` produce 1-bit bit-vector results. Bitwuzla's
`EQUAL`, `BV_ULT`, `BV_ULE` produce Boolean terms. Boolean terms cannot be used
as operands to BV operations (`and`, `or`, `not`). Fix: `_mk_bv1()` wraps the
Boolean in `ITE(bool, bv1, bv0)` to produce a proper 1-bit BV.

## Candidate-Relevant Failures (Before Fix)

| State | Next Node | Root Failure | Fixed? |
|---|---|---|---|
| state1536 | L2968 | slice OOB + Boolean/BV mismatch | Yes |
| state790 | L2676 | Boolean/BV mismatch | Yes |
| state1558 | L2970 | slice OOB | Yes |
| state2002 | L3213 | Boolean/BV mismatch | Yes |
| state79 | L2172 | slice OOB + Boolean/BV mismatch | Yes |

## Dependency Cone for Shortlisted Candidates

| Candidate | Required next-state nodes | Cone size | Translation status |
|---|---:|---|---|
| 1: state1536=10 => state790=0 | L2968, L2676 | ~40 | **fully translated** |
| 2: state1536=0 => state1558=0 | L2968, L2970 | ~30 | **fully translated** |
| 3: state2002=1 => state1536=0 | L3213, L2968 | ~40 | **fully translated** |
| 4: !(state1536=10 && state79=1) | L2968, L2172 | ~30 | **fully translated** |
| 5: state1536=11 => i_wb_data[12]=1 | L2968 | ~30 | **fully translated** (state side only; i_wb_data is input) |

## Conclusion

Transition validation is no longer globally blocked. All 5 shortlisted candidates
can generate init, one-step, and self-induction queries. The remaining 29/247
failures are non-relevant cascade from a single redor node.
