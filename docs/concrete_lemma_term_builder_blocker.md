# Concrete Lemma Term Builder Dry-Run

## Status: Blocked

Term construction is NOT the blocker. The concrete solver has all state
variables via `conc_ts_.lookup("state469")`. The term building code is
well-understood (see audit). The blocker is at the injection layer:
bitvector→Boolean predicate mapping for `constrain_frame()`.

## What Works

Building the concrete SMT term for a lifted lemma is straightforward:

```cpp
// Pseudocode — compiles with existing APIs
Term s = conc_ts_.lookup(varname);       // get state variable term
Sort bvs = s->get_sort();                // get bitvector sort
Term bv0 = solver_->make_term(0, bvs);    // #b0 of correct width
Term eq = solver_->make_term(Equal, s, bv0);  // (= stateN #b0)
Term impl = solver_->make_term(Implies, conj, conseq); // full lemma
```

All 26 lifted lemmas use variables that exist in `conc_ts_` since
BTOR2 node IDs match state variable names 1:1.

## What's Missing

The step from concrete term → IC3Formula → constrain_frame():

1. `constrain_frame()` expects `IC3Formula` with children from `predlbls_`
   (Boolean predicate labels), not bitvector equality terms.
2. To convert `(= state469 #b0)` → predicate label, IC3IA must either:
   a. Already have this as a predicate (check `predset_`), or
   b. Create a new predicate via `add_predicate()`
3. `add_predicate()` asserts `Equal(label, predicate_term)` on the solver,
   creating the Boolean abstraction.

## Decision

**concrete_lemma_term_builder_blocked**

The term building itself works. The injection path requires predicate
abstraction which is already documented. Use offline replay (WP5) for
impact estimation without C++ changes.
