> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Reset-Solver Injection Soundness Note

## What Is Asserted

Only lemmas that were independently solver-verified under the offline
Bitwuzla validation pipeline (init UNSAT, one-step UNSAT, induction
UNSAT) are injected. The injection does NOT trust the LLM — it trusts
the formal solver.

## How Assertion Works

After each solver reset in `IC3IA::reset_solver()`, concrete BTOR2-level
lemma terms are asserted via `solver_->assert_formula(lemma)`. The terms
are built from `conc_ts_.lookup(varname)` to obtain the correct state
variables from the concrete transition system.

## Why This Is Different from Unsafely Trusting LLM

1. **Gating**: Only solver-verified lemmas are loaded.
2. **Opt-in**: Requires `PONO_LLM_ASSERT_LIFTED_LEMMAS=1`.
3. **Concrete terms**: Uses `conc_ts_` which mirrors the original BTOR2 design.
4. **No predicate abstraction**: Asserts BITVECTOR equalities directly, not Boolean predicates.
5. **No injection without env var**: Zero overhead when disabled.

## Remaining Soundness Caveats

1. **Solver context**: `reset_solver()` is called at solver context 0.
   Assertions at this level persist across all solver queries. The lemma
   MUST hold in all reachable states.

2. **Transition coverage**: Offline validation uses 88% transition
   translation. The 12% untranslated lines could theoretically contain
   transitions that violate the lemma.

3. **Lemma format**: Only `(=> (and (= A #b0) (= B #b0)) (= C #b0))` is
   supported. Other formats are silently skipped.

4. **Dynamic reader**: Only a text file format is supported. No JSON
   validation. Malformed lines are silently skipped.

## Safety Recommendations

1. Before using with higher k or unsolved benchmarks, verify that ALL
   lemma variables exist in `conc_ts_` (the current code silently
   skips missing variables).

2. Consider adding an assertion check: after building the lemma term,
   independently validate that `Init ∧ ¬lemma` is UNSAT using the
   solver before asserting.

3. For production use, add JSON schema validation and log unsupported
   lemmas explicitly.
