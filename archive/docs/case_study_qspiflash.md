> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Case Study: qspiflash_dualflexpress_divfive-p040

> First closed-loop formal-feedback-guided semantic lemma repair
> Last updated: 2026-05-28

## Benchmark

Quad SPI flash controller, HWMCC'24 word-level BV track.
BTOR2: `qspiflash_dualflexpress_divfive-p040.btor2` (3102 lines, 249 states, 11 inputs).
Pono reached proof in 352s (other tools 1-7s; runtime comparison is context only,
not a current claim).

**This benchmark produced all 30 batch-generation candidates** (v1 strict + v2 semantic
prompts) including the 5 solver-validation shortlisted lemmas. All `stateNN` names in
the candidates map directly to BTOR2 nodes in this file.

## Key State Variable Mappings

| stateNN | Bitwidth | Verilog Symbol | Init | Description |
|---------|----------|---------------|------|-------------|
| state79 | 1 | `cfg_mode` | 0 | Configuration mode flag |
| state790 | 1 | `o_wb_stall` | 1 | Wishbone stall output |
| state1359 | 1 | — | 0 | IC3IA predicate (repair case study) |
| state1361 | 1 | — | 0 | IC3IA predicate (repair case study) |
| state1536 | 4 | `o_dspi_mod` | 0 | DSPI mode register |
| state1558 | 1 | `cfg_speed` | 0 | Configuration speed flag |
| state2002 | 1 | `OPT_PIPE_BLOCK.r_pipe_req` | 0 | Pipeline block request |
| i_wb_data | 10 | `i_wb_data` | N/A | Wishbone data bus (primary input) |

The `stateNN` → BTOR2 node mapping is deterministic: `state1536` = BTOR2 line 1536.
This holds for ALL state variables in ANY BTOR2 file.

## Pipeline Trace

```
Step 1 — LLM Generation
========================
Context: CTI batch + BTOR2 transition + design_context + predicate role tags

LLM output:
  Lemma:    (= state1361 (bvnot state1359))
  Schema:   complement equality
  Variables: state1359 (1-bit), state1361 (1-bit)
  Intuition: state1361' = NOT(state1359') — the transition guarantees complement

Step 2 — Formal Init Check
===========================
Result: FAIL
  state1359 = 0
  state1361 = 0
  bvnot(0) = 1 ≠ 0
  → lemma false at reset

Step 3 — Repair Prompt
=======================
Context sent to LLM:
  - Failed lemma + failure type (init_failure)
  - Init witness: state1359=0, state1361=0
  - Transition structure: state1361' = NOT(state1359')
  - Instruction: weaken, add guard, or change schema

Step 4 — LLM Repair
=====================
LLM output:
  Lemma:    !(state1359 && state1361)
  Schema:   mutual exclusion
  Intuition: "Next-state complement relation implies they are never both 1"

Step 5 — Formal Verification
==============================
Init:  !(0 && 0) = 1  ✅
Trans: state1361' = NOT(state1359') ⇒ !(1 && 0) = 1  ✅
Induction: unconditionally inductive (T ⇒ lemma')  ✅

Step 6 — Interpretation
=========================
The LLM did NOT simply add a syntactic guard.
It reformulated the lemma from complement equality to mutual exclusion,
preserving the core semantic relation while fixing init violation.
This is schema-level semantic reformulation.
```

## Repair Taxonomy

| Original Schema | Failure Type | Repaired Schema | Operation |
|----------------|-------------|-----------------|-----------|
| complement equality | init failure | mutual exclusion | semantic weakening + schema change |

Operation: `x = !y` → `!(x && y)`. Weaker form that preserves the critical
invariant (they can never both be 1) while avoiding the init counterexample.

## Formal Proof Sketch

```
Given: state1361' = NOT(state1359')  (from BTOR2 transition)

Then:  state1359' ∧ state1361'
     = state1359' ∧ NOT(state1359')
     = FALSE

Therefore: NOT(state1359' ∧ state1361') is unconditionally inductive.
```

Precondition: state1359 and state1361 are 1-bit state variables (Boolean predicates).

## Limitations

- Lemma covers only 1% of CTI literals (4/482)
- Associated clause cluster has only 2 clauses
- No measurable runtime impact on this benchmark
- Does NOT claim speedup or proof unlock

## Batch Generation & Solver Validation

All 30 batch candidates were generated from this benchmark. The 5 solver-validation
candidates (guarded implications and mutual exclusion on state1536/state790/state1558/
state2002/state79) were shortlisted from these 30. See `docs/solver_validation_candidates.md`.

Init checks pass for all 4 state-only candidates (UNSAT). One-step/induction checks are
blocked by Python BTOR2-to-SMT transition translation failures (127/247 lines).
See `docs/solver_validation_results.md` and `docs/mapping_spike_solver_shortlist.md`.

## Significance

This case study demonstrates the complete closed-loop pipeline:
1. LLM generates a transition-causal semantic hypothesis
2. Formal check identifies the exact failure (init violation)
3. Failure model guides repair (semantic weakening instead of syntactic patch)
4. Repaired lemma is formally verified as inductive

The contribution is the **mechanism**, not the impact on this specific benchmark.
