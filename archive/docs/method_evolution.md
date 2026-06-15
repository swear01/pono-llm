> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

# Method Evolution

> **2026-06-03:** Methods 1–8 are **historical offline research**. Runtime integration is **IC3 Frame v1** — online, frame-native, legacy code **to be deleted**. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md).

## 1. LLM Direct Generation

**What**: Batch prompt with CTI clusters → LLM proposes semantic lemma candidates.

**Result**: 30 candidates, 100% parse, 7 schema types. None solver-verified.

**Insight**: Single-shot prompting produces correlation-like candidates that don't capture inductive structure.

## 2. Formal Gates

**What**: Add reachable filter, nontriviality gate, init check, before expensive SMT.

**Result**: Gates filter ~80% of doomed candidates before solver checks.

**Insight**: Three-layer defense (reachable + nontrivial + solver) is effective and necessary.

## 3. Repair Loop

**What**: Counterexample feedback → LLM repair → re-validate.

**Result**: First case study (qspiflash equality→mutex). Repair v1 trivialized. Repair v2 avoided triviality but no useful lemma.

**Insight**: Repair alone insufficient when original candidates are too far from ground truth.

## 4. Reachability-Aware Synthesis

**What**: Include known reachable samples as positive constraints.

**Result**: Prevents excluding reachable CE values. Candidates pass pre-gates but fail induction.

**Insight**: Reachable samples are necessary but not sufficient for inductive synthesis.

## 5. Transition-Aware Synthesis

**What**: Include transition slice summaries for causal reasoning.

**Result**: Better-structured candidates (novel OR-consequent pattern). Still fail induction.

**Insight**: Transition context helps structure but doesn't produce induction without solver feedback.

## 6. Closed-Loop Synthesis

**What**: Iterative propose → validate → CE feedback → refine.

**Result**: First solver-verified lemma: `state2002=>state790` (r_pipe_req ⇒ o_wb_stall).

**Insight**: Solver-in-the-loop iteration is the critical ingredient. Single-shot prompts don't work.

## 7. Impact Analyzer

**What**: Analyze lemma's proof-trace relevance from IC3IA frame/CTI dumps.

**Result**: `state2002=>state790` has 0 CTI violations, 0 clauses with both vars → low_potential.

**Insight**: A valid, nontrivial, repeatably discoverable lemma can still have zero proof-trace impact.

## 8. Impact-Guided LLM Synthesis

**What**: Select high-proof-relevance variable clusters from dumps, prompt LLM.

**Result**: 3 verified lemmas in 1 round (up from 1 lemma in 2 rounds). Still all low impact.

**Insight**: Impact-guided cluster selection improves discovery rate but doesn't change impact because pairwise implications don't subsume multi-literal OR clauses.

## 9. Clause-Family Lifting

**What**: Mechanically convert every multi-literal IC3IA OR clause into equivalent implication forms.

**Result**: 26/30 verified (87% pass rate). All low impact — each explains only its source clause.

**Insight**: IC3IA frame clauses can be lifted into globally inductive lemmas with high success rate, but the lemmas are proof-local artifacts that don't compress clause families.

## 10. Family-Level Generalization (Current)

**What**: Group the 26 verified lifted lemmas by shared structure and derive broader lemmas.

**Goal**: Find lemmas that cover multiple clauses, not just source clauses.

**Status**: Pending.
