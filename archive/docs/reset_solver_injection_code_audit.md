> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Reset-Solver Injection Code Audit

## Implementation Location

`engines/ic3ia.cpp`, `IC3IA::reset_solver()` method (line ~408-468).

## Dynamic Loader (Current State)

The code reads lemma specifications from a text file at `PONO_LLM_LEMMA_LIST`.
Format: `ant_var1 ant_var2 cons_var` (one lemma per line, all values #b0).

Environment:
- `PONO_LLM_ASSERT_LIFTED_LEMMAS=1` — enables injection
- `PONO_LLM_LEMMA_LIST=path` — text file with lemma triplets

## Term Construction

```cpp
auto mk_eq_bv0 = [this](const std::string & varname) -> Term {
    Term sv = conc_ts_.lookup(varname);
    if (!sv) return Term();
    Term bv0 = solver_->make_term(0, sv->get_sort());
    return solver_->make_term(Equal, sv, bv0);
};
```

Only `#b0` (zero) equalities are supported. All variables must exist in `conc_ts_`.

## Assertion Point

Asserted after `reset_solver()` and after label-predicate equalities are re-asserted. Lemma list is loaded ONCE (static variable) and re-asserted on every `reset_solver()` call.

## Behavior When Disabled

When `PONO_LLM_ASSERT_LIFTED_LEMMAS` is not set or set to "0", the entire block is skipped. Zero overhead.

## Risks

1. **Single assertion format**: Only `(=> (and (= A #b0) (= B #b0)) (= C #b0))`. Other lemma structures silently skipped.
2. **Text file only**: No JSON parsing. Requires Python pre-processing to generate text file from dryrun JSON.
3. **No safety validation**: Missing variables silently skipped. No check that the lemma was solver-verified.

## Decision

**hardcoded_injection_needs_refactor** — The dynamic loader added in the last session partially addresses this, but the lemma format is still restricted to `#b0` equalities with 2 antecedents.
