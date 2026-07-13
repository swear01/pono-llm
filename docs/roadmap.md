# Roadmap

**Updated:** 2026-07-13
**Branch:** `soundness-audit`

## Current Decision

The project has completed four empirical gates:

1. constraint-injection soundness audit;
2. matched affine/quadratic formula baselines;
3. broad HWMCC residual scan and compactness falsification;
4. paired source/lifted/raw phase-local grammar-routing study.

The trust boundary is sound. The current LLM-specific research claim is still
negative: no solved task or routed solved-set advantage survives the matched
deterministic baselines. The project is not ready for a coverage-improvement
paper, and it must not enter paper mode merely because another gate completed.

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

## Gate 4 — Proof-Carrying Modular Algebraic Certificates (Active)

The user selected Candidate B. The complete preregistration is
[`docs/algebraic_certificate_gate.md`](algebraic_certificate_gate.md).

Gate 4B0 first asks whether a small exact `Z/(2^w)Z` polynomial-identity kernel
can remove a real nonlinear C2 bottleneck. C1 and C3 remain exact original-model
checks. No LLM capture is allowed until the deterministic kernel succeeds on at
least three independent natural recurrence families.

### Fallback A — Certified transport/metamorphic robustness

Question: can a certified invariant be transported across semantics-preserving
program/circuit transforms more efficiently and robustly than regenerated?

Required controls:

- exact transition-system isomorphism or independently validated translation;
- variable renaming, phase splitting, compiler optimization, and invertible
  affine modular state transforms reported separately from natural tasks;
- all transported formulas rechecked on the transformed original BTOR2;
- deterministic symbolic mapping baseline before LLM mapping.

Go only if transport adds robust success over regeneration on at least three
transformation families. Otherwise stop.

### Active B — Proof-carrying algebraic certificates

Question: can semantic proposals include a modular polynomial derivation that a
small trusted kernel verifies without generic BVMul proof search?

Required controls:

- exact `Z/(2^w)Z` semantics and width/extension handling;
- at least three recurrence families, not only triangular sums;
- deterministic normalizer baseline;
- malformed derivations rejected, never repaired silently.

Gate 4B0 uses `fib_23`/`fib_30` only as development controls, records a fixed
Z3/PolySAT/Pono reconnaissance matrix, and applies a sub-second/3x kill rule.
The full gate passes only with three held-out natural source families and zero
false-safe controls. Otherwise stop and run the known-map transport oracle.

### Dormant C — Independently selected local-certificate corpus

Question: is the one observed phase-only task representative in a population
selected by control-flow structure rather than current proof outcomes?

This is allowed only with a new frozen population and deterministic local
template oracle. It must not reuse the current three successes as the selection
criterion. Go only if at least three independent natural phase-only families
survive.

## Bounded Nonlinear Work

Predicate-aware BVMul CEGAR remains dormant. Start it only when a new natural
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
