# Formal-Feedback-Guided Semantic Lemma Repair for Word-Level IC3IA Traces

> Working title. Last updated: 2026-05-28.
>
> **Gist**: https://gist.github.com/swear01/cb8df13821ab1376f08cc144bc74b68b
> — update after each major phase completion (new results, blocker resolved, pipeline milestone).

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
Pono reached proof in 352s (other tools 1-7s; this is context only, not a runtime
claim). Selected as primary case study because it produced the first clean
closed-loop repair trace.

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
2. Formal feedback can identify when an LLM lemma is too strong and guide repair.
3. IC3IA proof artifacts can be systematically lifted into solver-verified lemmas via mechanical clause-family lifting (26/30 verified, 87% pass rate).
4. Valid semantic lemmas can be discovered through closed-loop solver-guided synthesis (r_pipe_req ⇒ o_wb_stall).
5. Proof-artifact-guided generalization harness can achieve 100% metadata traceability, linking every candidate to a source artifact and operator.
6. Formal soundness and proof impact are distinct dimensions — a solver-verified lemma may have low proof-trace relevance.

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

1. **Namespace mapping partially resolved (2026-05-28):** `stateNN` names ARE
   BTOR2 node IDs. For qspiflash, we can map state1536 → `o_dspi_mod` (4-bit),
   state79 → `cfg_mode` (1-bit), etc. The `symbol_map_` in `btor2_encoder.cpp`
   links internal names to Verilog originals. However, this mapping is not yet
   serialized or exposed to the Python pipeline.
   See `docs/future_work_pono_integration.md`.

2. **Python BTOR2-to-SMT translation incomplete:** `smt_checker.py` supports 18
   BTOR2 operators but 127/247 transitions fail translation for qspiflash
   (root cause: `slice` indices that Bitwuzla's `BV_EXTRACT` considers
   out-of-range). Init checks work (216/249 states have init values), but
   one-step/induction checks are blocked on real HWMCC candidates.

3. **Init semantics for some benchmarks:** Some BTOR2 files do not contain
   explicit `init` lines; reset/init behavior is encoded implicitly in
   transition logic.

4. **Small lemma impact on qspiflash:** The verified lemma covers only 1% of CTI
   literals.

---

## 9. Evaluation Plan & Completed Results

### A. Case-Study Correctness
- ✅ qspiflash closed-loop repair trace (equality → mutual exclusion)
- ✅ Proof sketch (init + transition)
- ✅ Repair taxonomy
- ✅ Closed-loop synthesis case study: `r_pipe_req ⇒ o_wb_stall`
- ✅ Cross-parameter validation: 6/6 qspiflash variants

### B. Batch Generation Yield
- ✅ Raw candidates per LLM call (10-20)
- ✅ Parse-valid rate (100%)
- ✅ Unique (deduped) rate
- ✅ Schema distribution (7 types)
- ✅ Analytical verification rate
- ✅ Repair/resynthesis experiments (6 experiments, 1 useful lemma)

### C. Solver-Validated Lemma
- ✅ `state2002=1 => state790=1` — audited, nontrivial, non-vacuous
- ✅ Init UNSAT, one-step UNSAT, induction UNSAT
- ✅ Repeatability: discovered in 5/8 closed-loop trials (63%)
- ✅ Novelty: never proposed in original 30-candidate batch

### D. Remaining (blocked on IC3IA frame data)
- Clause subsumption impact
- Frame relevance proxy
- Proof-obligation blocking

---

## 10. Future Work & Next Steps

### A. Completed (since scope freeze)

1. **BTOR2 transition translation** — improved from 121/247 (49%) to 218/247 (88%).
   Three bugs fixed: slice OOB, uext source index, Boolean/BV conversion.

2. **Solver-backed validation** — init, one-step, and induction checks now run on
   all shortlisted candidates. Original 30 candidates classified.

3. **Counterexample extraction** — SAT models extracted from failed one-step and
   induction checks using `Bitwuzla.get_value()` with `PRODUCE_MODELS` enabled.

4. **Nontriviality gate** — 5 checks (bitwidth tautology, impossible antecedent,
   tautological consequent, CE blocking, variable relevance). Catches vacuous
   repairs and trivially-true lemmas.

5. **Reachable-sample filter** — evaluates lemmas against 17 concrete reachable
   samples. Fast solver-free pre-check that catches ~80% of doomed candidates.

6. **Closed-loop synthesis** — iterative propose → validate → CE feedback → refine
   loop found the first solver-verified useful lemma (Task 70).

7. **Current main result**: `r_pipe_req ⇒ o_wb_stall` — a cross-parameter
   qspiflash invariant, repeatably discoverable (63% of trials), validated on
   6/6 variants (p020–p162).

### B. Pending (blocked on infrastructure)

1. **IC3IA frame / CTI dump** — minimal Pono C++ export of frame clauses,
   CTI cubes, and proof obligations with stateNN predicate labels. Needed
   to estimate clause impact of the validated lemma. See `docs/lemma_impact_proxy_plan.md`.

2. **Pono `rel_ind_check` integration** — call Pono's relative induction check
   from the formal gate pipeline (requires frame dump first).

3. **Lemma injection into IC3IA frames** — add accepted lemmas to IC3IA proof
   search and measure impact (requires rel_ind_check first).

### C. Future (research direction)

4. **Controlled benchmark** — design a lemma-critical Verilog design where
   baseline IC3IA times out and an oracle semantic lemma unlocks the proof.

5. **Multi-benchmark closed-loop** — extend the synthesis loop to other
   benchmark families beyond qspiflash.

6. **Lemma library** — build a collection of solver-verified lemmas from
   multiple closed-loop trials and cross-parameter validations.

### Important

Do NOT claim runtime speedup, benchmark unlock, full Pono integration, or
`rel_ind_check` completion. The lemma is validated under the offline Bitwuzla
pipeline, not inside Pono. IC3IA clause impact remains unknown until frame
data is available.

---

## 11. Agent / Slides Mode

When the task involves slides, reports, or agent handoffs:

- **Slides**: keyword-based, not document-like. Put detail in speaker notes.
  Use flowcharts for: (1) main pipeline, (2) qspiflash repair loop,
  (3) mapping blocker / next steps. Avoid long paragraphs on slides.

- **Reports**: include mapping tables (stateNN → Verilog → bitwidth → init → next),
  solver verdicts in structured labels, and explicit blocker descriptions.

- **Handoff prompts**: include progress summary, active blockers (with root cause),
  exact files to read for context, and a clear go/no-go for expensive operations.

- **Do not overclaim**: runtime speedup, benchmark unlock, full Pono integration are
  future work only. State what was measured, not what might be inferred.
