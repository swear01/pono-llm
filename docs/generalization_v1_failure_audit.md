> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Generalization v1 Failure Audit

## Summary

Task 102 proof-artifact-guided generalization v1 produced 42 unique candidates with 100% metadata compliance, but 0 solver-verified. Analysis of failure modes:

| Failure Type | Count | DSL-Preventable? |
|---|---|---|
| other_parse (free-form SMT) | 18 | Yes — DSL eliminates free-form SMT |
| unsupported_not_and | 1 | Yes — mapped to nary_mutex_3 schema |
| nontriviality (duplicate/contradictory guards) | 23 | Partially — DSL prevents duplicate vars but can't enforce logic validity |
| **Total** | **42** | |

## Example Failures

**Free-form SMT**: `(! (and (= state471 #b0) (= state790 #b1)))` — uses `!` negation, 3-variable conjunction not handled by parser. DSL would produce `(not (and ...))` with deterministic lowering.

**Nontriviality**: Candidates like `(= stateX #b0) AND (= stateX #b1)` or `(= stateX #b0) AND (= stateX #b0)` — duplicate/contradictory guards. DSL validates uniqueness of variables in guards.

## What DSL Prevents

1. Parse failures from free-form SMT: **Yes** — DSL removes all SMT generation from LLM
2. `(! ...)` vs `(not ...)` syntax: **Yes** — DSL lowerer produces consistent `not` 
3. Duplicate variables in guards: **Yes** — DSL validates uniqueness
4. Missing metadata: **Yes** — DSL validates required fields
5. Nontriviality (contradictory guards): **Partially** — DSL prevents duplicates but LLM can still output `(X=0 AND X=1)` if X appears once with both values

## What DSL Cannot Prevent

1. **Logic validity**: DSL can't verify that `X=0 AND Y=0 => Z=0` is actually inductive
2. **Bitwidth tautologies**: Requires separate nontriviality gate (already implemented)
3. **Direct frontier claims**: DSL allows `state15=0` as consequent — needs prompt-level avoidance

## Conclusion

DSL-constrained v2 should eliminate 19/42 parse failures but still needs nontriviality gate + prompt-level instruction to avoid the remaining 23 failures.
