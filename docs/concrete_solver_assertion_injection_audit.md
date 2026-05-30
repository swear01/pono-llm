# Concrete Solver Assertion Injection Audit

## Summary

Concrete solver assertion injection for lifted lemmas is **technically feasible**
but requires the same IC3IA predicate abstraction mapping as predicate injection,
making it blocked by the same underlying challenge.

## Candidate Injection Points

| Location | File/function | Can access BTOR2 state vars? | Can assert formula? | Risk |
|---|---|---|---|---|
| In `check_until()`, between init and while loop | `ic3base.cpp:178-189` | Yes (`conc_ts_.lookup()`) | Yes (`solver_->assert_formula()`) | Medium — needs `reset_solver` override |
| In `IC3IA::initialize()` after super::initialize() | `ic3ia.cpp:175` | Yes | Yes | Medium — too early, predicates not yet added |
| In `constrain_frame()` | `ic3base.cpp:876` | Requires abstraction | Yes (correct way) | **Low** — existing mechanism |
| Override `reset_solver()` | `ic3ia.cpp:395` | Yes | Yes | Medium — re-assert on every reset |
| Raw assert after solver is set up | Anywhere | Yes (state vars in conc_ts_) | Yes | **High** — lost on reset_solver |

## Required Term Construction

Building `(=> (and (= state469 #b0) (= state471 #b0)) (= state15 #b0))`:

```cpp
Term s469 = conc_ts_.lookup("state469");
Term s471 = conc_ts_.lookup("state471");
Term s15  = conc_ts_.lookup("state15");
Sort bv1 = s469->get_sort();
Term bv0 = solver_->make_term(0, bv1);
Term eq469 = solver_->make_term(Equal, s469, bv0);
Term eq471 = solver_->make_term(Equal, s471, bv0);
Term eq15  = solver_->make_term(Equal, s15, bv0);
Term ante = solver_->make_term(And, TermVec{eq469, eq471});
Term impl = solver_->make_term(Implies, ante, eq15);
```

This produces a valid SMT term in the concrete solver.

## Recommended Minimal Injection Point

Use `constrain_frame()` with the lifted lemma converted to an `IC3Formula`.
This is the same mechanism that `process_llm_candidates()` uses and is
integrated with the solver context management.

## Decision

**concrete_injection_blocked_missing_term_mapping**

The blocker is NOT term construction — the concrete solver has the state
variables. The blocker is that `constrain_frame()` expects `IC3Formula` with
children that are Boolean predicate labels (for IC3IA) or state variables
(for bit-level IC3). The lifted lemmas use BTOR2-level bitvector state
variables that need to be converted to Boolean predicates for IC3IA frame
insertion.

Specifically, `constrain_frame()` calls `constrain_frame_label()`:
```cpp
solver_->assert_formula(
    solver_->make_term(Implies, frame_labels_.at(i), constraint.term));
```

The `constraint.term` must be a formula over Boolean predicate labels. The
bitvector equality terms `(= state469 #b0)` are NOT Boolean labels — they
are concrete bitvector equalities. IC3IA would need to abstract them first.

## Blockers

1. Bitvector→Boolean predicate abstraction mapping not available at insertion time.
2. `constrain_frame()` interface requires `IC3Formula` with Boolean children.
3. Raw `assert_formula()` is unsound without `reset_solver()` override.
4. `reset_solver()` override requires maintenance burden.

## Next Patch

Option A: Add lemma through `IC3IA::add_predicate()` which already handles
term mapping. This requires the lemma to be expressed as a predicate expression
that IC3IA can abstract. The lemma `(=> (and A B) C)` would be decomposed
into `(or (not A) (not B) C)` and added as a disjunction.

Option B: Add lemma as a concrete assumption at `check_until()` entry, with
a `reset_solver()` override to re-assert it. Simpler but more invasive.

Option C: Offline replay (no C++ change). See Work Package 5.
