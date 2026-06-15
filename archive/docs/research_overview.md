> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

# Research Overview

> **2026-06-03 pivot:** Runtime integration is **IC3 Frame v1** — online CTI → structured JSON → Pono `rel_ind_check` → `constrain_frame`.  
> Legacy Path 1 (reset_solver injection) and offline mining runtime **will be deleted**.  
> **Spec:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

## One-Sentence Summary

We study whether LLMs, guided by model-checking proof artifacts and validated by Pono's native checks, can generalize CTIs into frame-native blocking clauses during online IC3/IC3IA proof.

## Core Research Problem

Hardware model checkers like IC3/IC3IA prove properties by iteratively refining a set of frame clauses — local proof artifacts that block specific counterexample paths. Many of these clauses encode similar or overlapping constraints. The question is: can we lift these local artifacts into broader semantic lemmas, checked for soundness by formal solvers, and measured for proof utility by impact analysis?

## Why Invariant Generalization

A model checker's frames contain hundreds of OR-clauses that are interconnected proof steps. A single frame clause like `(NOT state15) OR (NOT state469) OR state471` encodes a local relation. A generalization like `(state469 AND stateX) => state15` might cover many such clauses. Finding these generalizations is the core challenge.

## Method: Online Frame-Native Generalization (v1)

```text
IC3IA proof loop (live)
  → CTI + frame_snapshot + symbol_registry (Verilog)
  → LLM ic3_frame_response (structured AST, parallel K samples, reasoning_effort=none)
  → Pono rel_ind_check → constrain_frame / add_predicate
  → feedback retry on failure
```

Historical offline path (Bitwuzla closed-loop, clause lifting, reset_solver injection) remains documented as **HISTORICAL** research only. See [`DOC_INDEX.md`](DOC_INDEX.md).

## Pipeline Status

> **Below tables describe historical research (pre-v1).** Runtime integration is IC3 Frame v1 — not yet implemented. Path 1 injection **will be deleted**.

### Pono / IC3IA Thread (historical)

| Stage | Status |
|---|---|
| Proof artifact dumps | Working (predicate map, CTIs, frame clauses) |
| Clause-family lifting | 26/30 verified, 87% pass rate, all proof-local |
| Closed-loop synthesis | Found 1 useful lemma (r_pipe_req ⇒ o_wb_stall), low impact |
| Reset-solver injection | Prototype works (25/26 lifted injectable; closed-loop/mutex not); nondeterminism prevents stable measurement |
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
5. Reset-solver injection: mechanically implemented (limited grammar), opt-in; not full lemma pool
6. 100% metadata traceability in generalization harness v1

## What Failed or Was Downgraded

1. Single-run IC3IA artifact counts are unreliable — nondeterministic
2. Free-form think-none sampling: zero formal-gate yield
3. Proof-artifact-guided generalization v1: 0 solver-verified
4. Stable injection effect not established (high variance, small sample)
5. B5-MR repair: no valid new predicates yet

## Current Claim Boundary

> **Historical claims (pre-v1 offline / Path 1).** v1 success criteria: online `rel_ind_check` accept rate on p040, not offline Bitwuzla yield.

**Allowed (historical research):** formal-gated validation works, mechanical lifting produces verified lemmas, closed-loop found a valid invariant, Path 1 injection was mechanically implemented (to be **deleted**), metadata traceability is achievable.

**Not allowed:** runtime speedup, benchmark unlock, full Pono integration (until v1 E2E passes), claimed stable artifact reduction, claimed think-none replaces high-thinking for offline mining.

## Next Work (v1 implementation)

1. `ic3_frame_ast` C++ + JSON schema validator
2. Harness: Verilog registry + frame_snapshot + cache-friendly layers
3. Sidecar: parallel K + feedback retry + `reasoning_effort=none`
4. Delete legacy cube_subset / qf_smt / Path 1 runtime code
5. E2E qspiflash p040 with accept rate and latency metrics

See [`HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md).
