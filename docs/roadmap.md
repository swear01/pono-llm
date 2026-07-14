# Roadmap

**Updated:** 2026-07-14
**Branch:** `soundness-audit`

## Final Decision

The project has completed seven evidence stages:

1. constraint-injection soundness audit;
2. matched affine/quadratic formula baselines;
3. broad HWMCC residual scan and compactness falsification;
4. paired source/lifted/raw phase-local grammar-routing study;
5. proof-carrying modular algebraic certificate feasibility;
6. frozen nonlinear inductiveness-gap decomposition;
7. known-map certified-transport population feasibility.

The trust boundary is sound. The current LLM-specific research claim is still
negative: no solved task or routed solved-set advantage survives the matched
deterministic baselines. Gate 4B0 also found no v1-eligible natural primary
population, so it supplies a sound development kernel but no evaluated H5a
claim. The project does not support a coverage-improvement paper claim. Its
frozen evidence may support a soundness-methodology, reproducibility, or
negative empirical write-up without changing any baseline, population, or
threshold.

Gate 5A0 is complete and stopped `population-insufficient`: 11/12 certified
bases and 6/8 T1-applicable bases failed the frozen thresholds. All other
population conditions passed. No transformed variant or LLM call exists.
Gate 5A, proof-graph completion, stronger induction, and further mechanism
gates are closed under their preregistered decisions.

## Gate 0 — Soundness Repair (Complete)

- Constraint/assumption injection is retired as a proof method.
- 32/32 independently checkable old proofs fail C1/C2/C3.
- 30/32 tested mutex hints are reachable false invariants.
- LLM/static formulas are now untrusted IC3IA abstraction predicates.
- Direct certificates and Pono verdicts target the original BTOR2.

**Decision:** architecture retained; old apparent wins rejected.

## Gate 1 — Matched Formula Baselines (Complete)

- Balanced affine templates remove the former `93.c`, `fib_37`, and `fib_05`
  LLM-only interpretation.
- Five independent LLM captures certify `fib_23` and `fib_30` 10/10.
- A deterministic quadratic oracle certifies the same two tasks.
- Engine+deterministic and engine+LLM portfolios both cover eight UNSAT and two
  SAT cases in corrected full21.

**Decision:** matched affine/quadratic LLM-specific solve count is zero.

## Gate 2 — Dataset Ceiling (Complete)

- 1,919-file HWMCC census;
- 86 content-unique, non-array, preserved-software-name tasks;
- 11 new baseline/deterministic-hard targets after screening;
- LLM solves only `up.btor2`;
- corrected static cap-200 and post-hoc ranked cap-16/20 solve the same task;
- ranked deterministic replay is faster and equally reliable.

**Decision:** stop broad HWMCC mining and prompt tuning.

## Gate 3 — Paired Representation and Phase-Local Grammar (Complete)

Pinned official inputs:

- SV-COMP 2025 translation `d983801...`;
- SV-Benchmarks source `1e5856d...`;
- CPV `2b20529...`.

Population and pilot:

- 267 translated safety-func tasks;
- 164 eligible paired scalar tasks;
- 20 independent pilot tasks selected before LLM results.

Implemented:

- strict grammar-route schema;
- bounded signed/unsigned deterministic grammar;
- conservative functional-PC phase extraction;
- source/lifted/raw matched prompts;
- exhaustive, structural, random, and frozen LLM routing;
- direct and returned-invariant C1/C2/C3 audits.

Results:

- 36/60 LLM routes valid; 24/60 rejected explicitly;
- source/lifted/raw solve 1/1/2 baseline-hard tasks;
- deterministic structural-all solves the union of three;
- structural-global solves two; phase conditioning adds one;
- no source-unique or LLM-over-structural task;
- 0 false safe; all 12 routed UNSAT rows independently certified.

| Gate hypothesis | Result |
|---|---|
| H1: >=3 phase-only families | **fail: 1** |
| H2: source representation advantage | **fail: 0 source-unique** |
| H3: LLM routing advantage | **fail: 0 over structural** |
| H4: soundness | **pass** |

**Decision:** close the representation/phase/grammar-routing gate. Do not scale
the source corpus, phase extractor, route repair, or paid captures from this
evidence.

## Gate 4 — Proof-Carrying Modular Algebraic Certificates (Complete; Stop)

The user selected Candidate B. The complete preregistration is
[`docs/algebraic_certificate_gate.md`](algebraic_certificate_gate.md).

Gate 4B0 asked whether a small exact `Z/(2^w)Z` polynomial-identity kernel could
remove a real nonlinear C2 bottleneck. C1 and C3 remain exact original-model
checks. The strict kernel, solver reconnaissance, Pono matrix, rejection suite,
population selector, and artifact validator were implemented without an LLM.

### Completed B — Proof-carrying algebraic certificates

Question: can semantic proposals include a modular polynomial derivation that a
small trusted kernel verifies without generic BVMul proof search?

Required controls:

- exact `Z/(2^w)Z` semantics and width/extension handling;
- at least three recurrence families, not only triangular sums;
- deterministic normalizer baseline;
- malformed derivations rejected, never repaired silently.

Gate 4B0 used `fib_23`/`fib_30` only as development controls and recorded a
fixed Z3/PolySAT/Pono reconnaissance matrix. Both controls pass, and the
20-case rejection suite rejects 20/20 with zero false safe. However, the frozen
267-task official population yields 39 array exclusions, 221 tasks without a
v1 nonlinear update SCC, seven tasks whose nonlinear SCCs all exceed the frozen
eight-branch cap, and therefore **zero v1-eligible natural task**.

H5a is **not run**, H5b is **not authorized**, development H5c passes, and
primary H5c is not run. The branch cap and v1 language are not widened after
the result. No LLM call was made.

**Decision:** stop Gate 4B0 and proceed to the separately preregistered
known-map certified-transport oracle. Do not relabel development controls or
synthetic models as natural H5a evidence.

### Frozen nonlinear inductiveness-gap diagnostic (complete)

Six frozen nonlinear candidates were checked before authorizing helper search,
k-induction, or proof-graph work. All six fail C1 in an initial state and exact
Houdini removes them during initial filtering. The measured failure is therefore
candidate falsity, not insufficient induction depth or proof organization.
Repairing or replacing a candidate after observing its C1 witness is a new
experiment and is not authorized here.

**Decision:** reject the repair-gap hypothesis; do not open proof-graph,
stronger-induction, or helper-search work for these six cases.

### Dormant C — Independently selected local-certificate corpus

Question: is the one observed phase-only task representative in a population
selected by control-flow structure rather than current proof outcomes?

This is allowed only with a new frozen population and deterministic local
template oracle. It must not reuse the current three successes as the selection
criterion. Go only if at least three independent natural phase-only families
survive.

## Gate 5 — Known-Map Certified Transport Oracle (Stopped)

The frozen protocol is
[`docs/certified_transport_gate.md`](certified_transport_gate.md). It treats
known-map transport as an upper-bound proof-reuse gate, not evidence that map
inference or LLM mapping is useful.

### Gate 5A0 — population/protocol feasibility (complete: STOP)

Before transformation code, census already certified, machine-readable source
invariants. Continue only with at least 12 base tasks, eight independent source
families, three invariant classes, and at least eight applicable bases for each
primary transform. T3 must include at least three input-driven families. If the
population is smaller, stop without padding it with synthetic or width variants.
The census independently re-certified every selected invariant for every BAD,
validates upstream hashes, deduplicates source families, and reports exact
T1/T2/T3 applicability. No transformed file may be generated before this
decision is committed. The official result is 11 safe bases, 11 source
families, six T1-applicable bases, 11 each for T2/T3, ten input-driven T3
families, and four unsafe controls. The failed `safe_base_count` and
`T1_applicable_base_count` conditions stop Gate 5 before variant generation.

### Gate 5A — known-map oracle (not authorized)

- T0 alpha-renaming/node-ID permutation is a sanity control and never counts.
- T1 is non-trivial invertible modular affine state recoding.
- T2 is bit-vector split encoding with exact concat/extract projection.
- T3 is a fixed input-latched stuttering microstep refinement with observation-
  guarded BAD and independently validated macro-step completeness.

Every concrete transformation/map must pass exact independent validation;
UNKNOWN rejects it. Every transported invariant is then rechecked with C1/C2/C3
on the transformed original BTOR2. Map validity, transformation equivalence,
and target-certificate validity remain separate verdicts.

Primary utility includes map-validation cost and compares against target
engine-only plus the strongest current deterministic regeneration portfolio.
H6 requires >=90% acceptance separately for T1/T2/T3, >=5x overall
unamortized geometric-mean speedup, >=2x per family, zero false safe, and T3
utility on at least three independent source families. T1/T2 without T3 is an
infrastructure result and stops the research direction.

### Gate 5B — map recovery (blocked)

Only all Gate 5A H6 criteria authorize hidden-map recovery, in this order:
deterministic structure, symbolic/SMT synthesis, graph matching, compiler
metadata, then at most one newly preregistered frozen LLM proposal capture.
Gate 5A0 and Gate 5A make no LLM/API calls.

## Closure boundary

The mechanism roadmap is closed with no Gate 6. Tag
`soundness-audit-final-v1` points to
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`. The final
[claim ledger](final_claim_ledger.md),
[research narrative](final_research_narrative.md), and
[machine-readable summary](../artifacts/final_research_summary_v1.json) are the
authoritative closure records.

[`oracle_first_capability_gates.md`](oracle_first_capability_gates.md) and its
ledger are a frozen post-boundary methodology addendum. Their external
artifact-availability STOP did not authorize a replacement corpus, another
external target, or a mechanism extension. A later explicitly authorized
append-only R1 event qualified newly public bytes at a pinned Quokka commit
without modifying that STOP. R1 stopped at the frozen smoke because
classification stability was 72% rather than 90%; it authorizes no full run.

## Bounded Nonlinear Work

Predicate-aware BVMul CEGAR remains outside this closed program. A future
independent project could preregister it only when a newly selected natural
case:

1. survives affine/quadratic deterministic generation;
2. has a correct candidate independently certified or localized to BVMul cost;
3. cannot be solved by direct modular normalization;
4. supplies a fixed five-day kill criterion.

The existing `fib_23`/`fib_30` cases do not satisfy this trigger because direct
deterministic certificates already solve them.

## Permanent Non-Goals

- BTOR2 hint constraints as proof assumptions;
- BMC/SMT UNKNOWN treated as evidence;
- generic BTOR2 decompilation;
- open-ended prompt/model/round tuning;
- best-run-only reporting;
- arrays as a main synthesis direction;
- generic nonlinear SMT solver development;
- publication claims based on the current small solved sets.

Canonical Gate 3 evidence:
[`artifacts/representation_phase_v1/`](../artifacts/representation_phase_v1/).

Canonical Gate 4B0 evidence:
[`artifacts/algebraic_certificate_v1/`](../artifacts/algebraic_certificate_v1/).
