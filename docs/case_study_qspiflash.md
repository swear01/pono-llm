# Case Study: qspiflash_dualflexpress_divfive-p040

> First closed-loop formal-feedback-guided semantic lemma repair

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

## Significance

This case study demonstrates the complete closed-loop pipeline:
1. LLM generates a transition-causal semantic hypothesis
2. Formal check identifies the exact failure (init violation)
3. Failure model guides repair (semantic weakening instead of syntactic patch)
4. Repaired lemma is formally verified as inductive

The contribution is the **mechanism**, not the impact on this specific benchmark.
