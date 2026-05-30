# Concrete Assertion Injection — Blocked

## Status

Not implemented. Both injection paths are blocked:

1. **IC3IA predicate injection**: requires `lbl2pred_` mapping to convert
   bitvector equality `(= state469 #b0)` → Boolean predicate label.
   Mapping exists but not accessible at injection time without C++ changes.

2. **Concrete solver assertion**: requires `constrain_frame()` interface
   which expects `IC3Formula` with Boolean children. Raw `assert_formula()`
   works but requires `reset_solver()` override.

## Recommended Alternative: Offline Replay (WP5)

Without C++ changes, the best available method to estimate injection impact
is offline replay: compare frame clauses against injected lemmas using the
existing JSONL dump infrastructure.

## Ready-to-Run Command (when unblocked)

```bash
PONO_LLM_CONCRETE_ASSERT_LEMMAS=1 \
PONO_LLM_LEMMA_FILE=logs/formal_yield/lifted_lemma_injection_dryrun.json \
PONO_LLM_LEMMA_SUBSET=one_best_candidate \
build/pono -e ic3ia -k 5 qspiflash_dualflexpress_divfive-p040.btor2
```

## Required C++ Patch

1. Add `constrain_frame()` call in `check_until()` at `ic3base.cpp:189`
2. Convert lemma term via `ic3formula_conjunction()` → `ic3formula_negate()`
3. Call `constrain_frame(0, lemma_formula, true)`
4. Gate with `std::getenv("PONO_LLM_CONCRETE_ASSERT_LEMMAS")`
5. Override `IC3IA::reset_solver()` to re-assert concrete terms
