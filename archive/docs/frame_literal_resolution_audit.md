> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Frame Literal Resolution Audit

## Summary

IC3IA frame clause literals reference abstract solver state variables
(e.g., `state538`) that represent Boolean predicate labels. These solver
state variables cannot be reliably matched to predicate expressions
using `to_string()` or `hash()` because:

1. `to_string()` gives solver-internal names (e.g., `state538`) in frame
   clauses, but user-provided names (e.g., `assump_598_0`) in the
   predicate dump — the solver renames terms between creation and usage.

2. `hash()` returns the SMT term hash, which should be stable for
   identical terms, but the term objects in `constrain_frame()` and
   `add_predicate()` appear to be different instances (likely because
   the solver normalizes or copies terms).

## What Frame Literals Look Like

Frame clause literals from IC3IA's abstract solver:
```
(= state93 #b1)     — positive literal (predicate true)
(not (= state538 #b0)) — negated literal (predicate false)
(= state545 #b0)    — positive literal (predicate false)
```

These are 1-bit bitvector state variables where:
- `(= stateNN #b1)` → the predicate represented by stateNN is true
- `(= stateNN #b0)` → the predicate represented by stateNN is false

## Relation to lbl2pred_ / predlbls_

- `add_predicate()` creates a Boolean predicate with `label(pred)` → `lbl`
- `lbl` is added to `predlbls_` and stored in `lbl2pred_[lbl] = pred`
- The abstract solver later assigns state variable names (e.g., `state538`)
  when these labels are used in the abstract transition system
- The solver-internal name cannot be predicted at `add_predicate()` time

## Attempted Approaches

| Approach | Result |
|---|---|
| `term->hash()` matching | 0/1159 matches — solver re-hashes terms |
| `to_string()` matching | 0/1 — solver-internal names differ from user labels |
| `inner_raw` from stripped `Not` | 0 matches — same name mismatch |
| Global reverse map | Not available — lbl2pred_ exists but solver renames keys |

## Recommended Solution

The most reliable approach is to modify `constrain_frame()` to call a
virtual method that IC3IA overrides, resolving frame literals through
`lbl2pred_` directly:

```cpp
// In IC3Base:
virtual smt::Term resolve_frame_literal(const smt::Term & lit) const {
    return lit;  // default: return unchanged
}

// In IC3IA override:
smt::Term resolve_frame_literal(const smt::Term & lit) const override {
    smt::Term inner = lit;
    if (lit->get_op() == smt::Not) inner = *(lit->begin());
    auto it = lbl2pred_.find(inner);
    if (it != lbl2pred_.end()) return it->second;
    return lit;
}
```

The frame dump would call `resolve_frame_literal()` and dump the resolved
predicate expression string alongside the raw solver representation.

## Current Blocker

Frame literal resolution requires modifying the IC3 base class to add a
virtual method. This is a small C++ change but requires recompiling all
IC3 variants (IC3, IC3IA, MBIC3) and is deferred to a future patch.
