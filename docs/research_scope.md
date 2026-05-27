# Formal-Feedback-Guided Semantic Lemma Repair for Word-Level IC3IA Traces

> Working title. Last updated: 2026-05-25.

---

## 1. Problem Statement

Pono/IC3IA already performs local clause generalization over individual proof
obligations: literal deletion, unsat-core minimization, subsumption, propagation,
and predicate refinement. These mechanisms operate on existing clauses or single
CTI cubes — they do not synthesize new semantic lemmas from clusters of related
CTIs.

This project addresses a complementary problem:

> Given clusters of related CTIs, frame-clause patterns, and transition-context
> summaries, can an LLM propose a new semantic lemma that explains or blocks
> multiple obligations simultaneously?

We are NOT replacing Pono's local clause generalization. We are adding a
cluster-level semantic lemma synthesis layer above it.

---

## 2. Core Hypothesis

LLMs are not reliable formal provers, but they may be useful **semantic
hypothesis generators**. If their outputs are filtered by formal checks and
repaired using failure feedback, they can produce nontrivial inductive lemma
candidates from model-checking traces.

The LLM proposes semantic guesses; soundness is guaranteed by formal gates.

---

## 3. Distinction from Pono Clause Generalization

| | Pono/IC3IA | This Project |
|---|---|---|
| Unit | Single CTI cube / proof obligation | Cluster of related CTIs / clauses |
| Operation | Literal deletion, unsat-core reduction | New semantic lemma synthesis |
| Output | Subset of original cube literals | Novel lemma not constrained to any CTI |
| Example | `a ∧ b ∧ c ∧ d` → `a ∧ c` | `x=¬y` fails init → `!(x && y)` |

---

## 4. Current Pipeline

```
IC3IA / CTI traces
  → CTI cluster mining (coverage, reset/trivial filters)
  → Cluster diversity scheduling
  → Cache-friendly batch prompting
  → LLM candidate generation (30 candidates/call, 2 clusters/batch)
  → Candidate canonicalization / schema validation / dedup
  → Analytical formal checks (init, one-step patterns)
  → Repair loop (failure model → LLM reformulation)
```

One LLM call generates ~30 diverse candidates across 2 clusters.
New lemma families discovered: bitslice disequality (`state1536[1:0] != 2'd1`).

---

## 5. Completed Case Study: qspiflash_divfive-p040

**Benchmark:** Quad SPI flash controller, HWMCC'24 word-level BV track.
Pono solved in 352s; other tools (rIC3, nuXmv) solved in 1-7s.

**Pipeline trace:**

```
Step 1 — LLM generation:
  Lemma: (= state1361 (bvnot state1359))
  Schema: complement equality
  Source: BTOR2 transition shows state1361' = NOT(state1359')

Step 2 — Formal init check:
  Result: FAIL
  Model: state1359=0, state1361=0  → lemma false at reset

Step 3 — Repair (failure-aware):
  Input: failed lemma + init witness + transition structure
  Output: !(state1359 && state1361)
  Schema: mutual exclusion

Step 4 — Validation:
  Init-safe: !(0 && 0) = true  ✓
  Inductive: state1361' = NOT(state1359') ⇒ never both 1  ✓
```

**Significance:** The repair is NOT syntactic rewriting. It is schema-level
semantic weakening: complement equality → mutual exclusion.

**Limitation:** Lemma covers 1% of CTI literals; cluster has only 2 clauses.
No measurable proof impact on this benchmark.

---

## 6. What This Project Claims

1. LLMs can infer transition-causal semantic relations from IC3IA trace context.
2. Formal feedback can identify when an LLM lemma is too strong.
3. Failure-aware repair can reformulate a rejected lemma into a weaker inductive
   candidate.
4. Cluster-conditioned batch prompting produces diverse semantic lemma candidates
   across multiple variable groups and lemma families.
5. Natural HWMCC sweet spots are rare; case mining with reset/trivial filters is
   necessary for selecting LLM-suitable bottlenecks.

---

## 7. What This Project Does NOT Claim (Yet)

1. **No Pono runtime speedup claim.**
2. **No claim that generated lemmas unlock previously unsolved benchmarks.**
3. **No full Pono frame-level `rel_ind_check` integration.**
4. **No injection of generated lemmas into Pono's IC3IA frames.**
5. **No replacement of Pono's existing clause generalization.**

These are explicitly listed as future work.

---

## 8. Current Limitations

1. **Namespace mismatch:** BTOR2/Verilog names (`cnt`, `f_cfglswrite`) do not
   directly match IC3IA predicate labels (`stateNN`). This blocks solver-backed
   checking on real benchmarks.

2. **Init semantics:** Some BTOR2 files do not contain explicit `init` lines;
   reset/init behavior is encoded implicitly in transition logic.

3. **Analytical checks only:** Current formal checks verify only recognizable
   patterns (mutual exclusion under complementary transition). Full solver-backed
   checking requires namespace mapping.

4. **Bitwuzla available but not yet usable on real candidates** due to namespace
   mismatch between IC3IA predicates and BTOR2 expressions.

5. **Small lemma impact on qspiflash:** The verified lemma covers only 1% of CTI
   literals.

---

## 9. Evaluation Plan

### A. Case-Study Correctness
- qspiflash closed-loop repair trace
- Formal proof sketch (init + transition)
- Repair taxonomy (equality → mutual exclusion)

### B. Batch Generation Yield
- Raw candidates per LLM call
- Parse-valid rate
- Unique (deduped) rate
- Schema distribution
- Analytical verification rate
- Repair candidate rate

### C. Case Mining Quality
- Clusters found
- Filtered by reset/trivial dominance
- LLM-suitable clusters remaining
- CTI coverage distribution

---

## 10. Future Work

1. **Pono predicate-to-BTOR2 mapping dump** — export IC3IA predicate label
   → underlying SMT expression / BTOR2 symbol mapping.

2. **Solver-backed formal gate** — Bitwuzla-based init/one-step/inductive checks
   on real candidates once namespace mapping is resolved.

3. **Pono `rel_ind_check` integration** — call Pono's relative induction check
   from the formal gate pipeline.

4. **Lemma injection into IC3IA frames** — add accepted lemmas to IC3IA proof
   search and measure impact.

5. **Unlock experiment** — on Pono-specific hard benchmarks (Pono timeout, other
   tools solved), test whether LLM-repaired lemmas enable proof completion.

6. **Controlled benchmark** — design a lemma-critical Verilog benchmark where
   baseline IC3IA times out and an oracle semantic lemma unlocks the proof.
