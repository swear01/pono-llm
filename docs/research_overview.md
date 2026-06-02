# Research Overview

## One-Sentence Summary

We study whether LLMs, guided by model-checking proof artifacts and validated by formal solvers, can generalize local proof steps into sound and potentially useful semantic lemmas for hardware model checking.

## Core Research Problem

Hardware model checkers like IC3/IC3IA prove properties by iteratively refining a set of frame clauses — local proof artifacts that block specific counterexample paths. Many of these clauses encode similar or overlapping constraints. The question is: can we lift these local artifacts into broader semantic lemmas, checked for soundness by formal solvers, and measured for proof utility by impact analysis?

## Why Invariant Generalization

A model checker's frames contain hundreds of OR-clauses that are interconnected proof steps. A single frame clause like `(NOT state15) OR (NOT state469) OR state471` encodes a local relation. A generalization like `(state469 AND stateX) => state15` might cover many such clauses. Finding these generalizations is the core challenge.

## Method: Proof-Artifact-Guided Generalization

```text
model-checking proof artifacts (frame clauses, CTIs, predicates, clause families)
  → generalization proposal (mechanical lifting or LLM-guided)
  → formal correctness gate (init, one-step, induction via Bitwuzla/IC3IA)
  → proof-impact gate (clause coverage, CTI relevance, frontier involvement)
  → optional injection/evaluation (reset_solver concrete assertion)
```

## Pipeline Status

### Pono / IC3IA Thread

| Stage | Status |
|---|---|
| Proof artifact dumps | Working (predicate map, CTIs, frame clauses) |
| Clause-family lifting | 26/30 verified, 87% pass rate, all proof-local |
| Closed-loop synthesis | Found 1 useful lemma (r_pipe_req ⇒ o_wb_stall), low impact |
| Reset-solver injection | Mechanically works, IC3IA nondeterminism prevents stable measurement |
| QUOKKA-style cached sampling | Infrastructure complete, think-none yield currently zero |
| Generalization harness v1 | 100% metadata compliance, 0% formal yield |
| DSL-constrained harness v2 | Parse rate improved, yield still pending high-thinking baseline |

### CPAchecker / CEGAR Thread

| Stage | Status |
|---|---|
| Context bootstrap | 8 predicates → 39 refinements, ZERO_CONTEXT_TIMEOUT resolved |
| B5-MR repair | 0 valid repair predicates, logging gaps block failure analysis |

## What Worked

1. Formal-gated candidate validation pipeline
2. IC3IA proof artifact dump and resolution infrastructure
3. Clause-family lifting: mechanical, reproducible, 87% pass rate
4. Closed-loop solver feedback: discovered genuine design invariant
5. Reset-solver injection: mechanically implemented and opt-in
6. 100% metadata traceability in generalization harness v1

## What Failed or Was Downgraded

1. Single-run IC3IA artifact counts are unreliable — nondeterministic
2. Free-form think-none sampling: zero formal-gate yield
3. Proof-artifact-guided generalization v1: 0 solver-verified
4. Stable injection effect not established (high variance, small sample)
5. B5-MR repair: no valid new predicates yet

## Current Claim Boundary

**Allowed**: formal-gated validation works, mechanical lifting produces verified lemmas, closed-loop found a valid invariant, injection is mechanically implemented, metadata traceability is achievable.

**Not allowed**: runtime speedup, benchmark unlock, full Pono integration, claimed stable artifact reduction, claimed think-none replaces high-thinking, claimed solver-verified implies proof-useful.

## Next Experiments

1. DSL-constrained generalization harness v2 with high-thinking baseline
2. Controlled repeated injection experiments at k=3 to reduce variance
3. CPAchecker per-candidate B5-MR logging for failure classification
4. Cross-variant injection validation if baseline stabilizes
