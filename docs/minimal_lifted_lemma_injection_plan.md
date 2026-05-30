# Minimal Lifted Lemma Injection Plan

## Goal

Inject solver-verified lifted lemmas as additional assertions in Pono
to test whether they accelerate IC3IA convergence, even without direct
clause-subsumption impact.

## Injection Points

| Point | Sound? | Easy? | Risk | Notes |
|---|---|---|---|---|
| As `IC3IA::add_predicate()` | Yes | Easy | Low | Adds lemma as an initial predicate |
| As frame-0 clause via `constrain_frame(0, ...)` | No | Easy | **Unsound** | Frame 0 is handled specially |
| As `solver_->assert_formula(lemma)` at init | Yes | Medium | Medium | Lemma must hold at init |
| As IC3IA assumption added before `check_until()` | Yes | Medium | Low-Medium | Similar to existing assumption pattern |

## Recommended: `add_predicate()` Injection

Add each lifted lemma as a predicate via `IC3IA::add_predicate()`. Since
the lemma is already verified as init-valid AND one-step-valid AND
induction-valid, adding it as a predicate is sound.

## Soundness Boundary

Only inject lemmas that were independently validated by:
- Init check: UNSAT
- One-step check: UNSAT  
- Induction check: UNSAT
- Under the offline Bitwuzla pipeline with 88% transition coverage

## Opt-In Interface

```bash
PONO_LLM_INJECT_LEMMAS=1
PONO_LLM_LEMMA_FILE=logs/formal_yield/lifted_lemma_injection_dryrun.json
PONO_LLM_LEMMA_SUBSET=top_5_by_score
```

When env var is not set, behavior is unchanged.

## Current Blocker

The 26 verified lemmas use the `(=> (and (= stateA #0) (= stateB #0)) (= state15 #0))`
format with variables `stateA`, `stateB`, `state15` that are BTOR2 node IDs.
These variables exist in the BTOR2 file and are accessible in Pono's concrete
transition system.

However, IC3IA operates on an ABSTRACT transition system where these
state variables become predicate labels. The phrase `(= state469 #b0)` is a
1-bit Boolean predicate in the abstract solver. In the concrete solver,
state469 corresponds to a bitvector state variable.

The injection must translate the lifted lemma from the BTOR2-level format
into the IC3IA abstract predicate format. This requires mapping
`stateA` → `concrete predicate expression` → `abstract label`.

Without this mapping at injection time, the lemma cannot be added as an
IC3IA predicate. The mapping EXISTS in the predicate dump but is not
available at Pono runtime.

## Alternative: Concrete Solver Injection

Instead of adding to IC3IA, add the lemma as a concrete assertion:
```
solver_->assert_formula(lemma_term)
```
This is simpler and doesn't require predicate mapping. The solver will
handle the translation.

## Recommended Path

For a quick experiment: add lemma as concrete assumption (not IC3IA predicate).
This is the simpler path and still provides useful signal about whether
the lemma helps convergence.

## Remaining Risk

- The 26 lifted lemmas were verified under 88% transition coverage
  (29/247 lines untranslated). If those missing transitions affect
  the lemma's validity inside Pono, injection could be unsound.
- The offline Bitwuzla pipeline may differ from Pono's internal solver
  configuration.
