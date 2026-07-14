# Predicates, Not Assumptions

## A Soundness and Matched-Baseline Audit of LLM-Guided IC3IA

**Research program:** `pono-llm` / `soundness-audit`
**Frozen boundary:** `soundness-audit-final-v1` →
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`
**Closed:** 2026-07-14

## Executive summary

This project began with an apparently strong result: LLM-generated semantic
hints seemed to let Pono prove many software-origin BTOR2 safety tasks that its
ordinary engines could not solve. The first independent audit reversed that
interpretation. The hints had been inserted as BTOR2 constraints. They were
therefore assumptions that removed behaviors from the concrete model, not
candidate invariants whose truth had been established. Original-model
certification rejected all 32 independently checkable old proofs, and bounded
reachability found concrete violations for 30 of the 32 tested mutex hints.

The project then replaced assumption injection with sound IC3IA predicate
injection. LLM formulas became untrusted abstraction vocabulary. A false
formula could make the abstraction larger or slower, but it could no longer
manufacture a safety result for an under-approximated model. This repair was a
real systems contribution, but it also removed the dramatic apparent gains.

The remaining study asked a stricter empirical question: after original-model
certification, matched deterministic candidate languages, frozen replay,
end-to-end accounting, and preregistered stopping rules, what marginal value
remains attributable to the LLM? Across the evaluated Pono populations, the
answer is no defensible solved-set or search-efficiency advantage. Affine and
quadratic deterministic portfolios cover all current LLM solves. A broader
HWMCC gate removes the remaining apparent compactness result. Source, lifted,
and raw representations, phase conditioning, and LLM grammar routing fail
their frozen utility thresholds. Later nonlinear-certificate and transport
ideas stop at population feasibility before a utility claim is run.

This is not a coverage-improvement result. It is a falsification and evaluation
methodology result: unsound trust boundaries, weak baselines, best-run
reporting, and post-hoc mechanism expansion can create an apparent LLM
advantage that disappears under disciplined formal and empirical controls.

## 1. Research question

The target systems are software-origin bit-vector transition systems encoded
in BTOR2 and checked by Pono, especially IC3IA. The initial hypothesis was that
an LLM could recover semantic invariants obscured by compilation and use them
to improve IC3IA proof search.

The final research question became narrower and more defensible:

> Do LLM-generated formulas retain measurable marginal proof value when they
> are treated as untrusted proposals, checked on the original model, compared
> with deterministic methods of matched expressiveness, replayed from frozen
> artifacts, and charged for generation cost?

The answer is scoped to the models, candidate languages, solvers, budgets, and
populations in the released artifacts. It is not a universal statement about
LLMs or formal verification.

## 2. Trust boundary

### 2.1 Why constraint injection failed

Adding a formula `h(X)` as a BTOR2 constraint changes the transition system
from `M` to a restricted system `M_h`. A safety result for `M_h` proves only
that no bad state is reachable while `h` is assumed. If `h` excludes a
reachable bad or intermediate state, the result says nothing about safety of
the original `M`.

The old boolean-pair path committed exactly this error. Signal-name plausibility
was treated as semantic truth, and the proof consumer was asked to prove a
model from which counterexamples had already been removed. The independent
checker restored the correct obligations:

```text
C1: Init => Inv
C2: Inv && Trans => Inv'
C3: Inv => !BAD
```

All obligations are evaluated against the original BTOR2 transition system,
including every BAD property. An SMT UNKNOWN is not a proof.

### 2.2 Sound predicate injection

The repaired path uses:

```text
pono -e ic3ia --initial-predicates predicates.json original.btor2
```

`IC3IA::initialize()` parses each predicate and adds it to the abstraction
vocabulary. The concrete init, transition relation, constraints, and BAD
properties are unchanged. The abstract relation is refined while remaining an
over-approximation of concrete behavior. Both truth values of a candidate can
remain represented; the candidate is not asserted as an invariant.

The precise claim is therefore not that a false invariant is harmless. It is
that a false **candidate formula** cannot create a false safety proof through
assumption. It may still increase predicate count, SMT cost, refinement work,
or memory use.

### 2.3 Independent certification

Two complementary proof paths enforce the trust boundary:

- `cert_check.py` checks a returned invariant with exact bit-vector semantics.
- `candidate_cert_check.py` checks a candidate conjunction directly and uses
  exact Houdini elimination to retain only a C1/C2-valid subset before C3.

Bounded SAT witnesses may refute a candidate. Bounded UNSAT or timeout never
establishes induction. Arrays and unsupported forms are rejected or recorded as
limitations rather than silently approximated.

## 3. Matched formula baselines

The first sound experiments seemed to leave three affine LLM-only cases:
`93.c`, `fib_37`, and `fib_05`. That claim was relative only to Pono's engine
portfolio, not to a non-LLM candidate generator. Once affine templates were
matched, the apparent unique set disappeared.

Two nonlinear cases, `fib_23` and `fib_30`, provided a stronger test. Five
independent LLM captures per task produced a directly certifiable candidate set
in all ten captures. That is a genuine reliability result. It is not a
marginality result: a deterministic quadratic recurrence family certifies the
same tasks.

The corrected 21-task comparison records equal LLM and deterministic quadratic
solved sets: seven candidate-certified UNSAT tasks. Adding the ordinary engine
portfolio gives both sides eight UNSAT and two SAT results. The current
full21 LLM-specific UNSAT set is empty. LLM generation also dominates direct
certificate time on the reliable nonlinear cases.

The lesson is methodological. A verifier-native baseline and a deterministic
candidate baseline answer different questions. Comparing only with the former
can mislabel the value of a useful predicate language as value unique to the
LLM that happened to instantiate it.

## 4. Broader HWMCC gate

Gate 2 scanned 1,919 BTOR2 files, identified 86 unique eligible non-array
software-origin models, screened ordinary engines, and froze 11 new
deterministic-hard targets before LLM replay.

One raw predicate-seeding run solved `up.btor2`, while direct LLM Houdini solved
none of the 11 targets. The apparent new solve did not survive stronger
deterministic controls. A cap-200 static pool reproduced it, and a fixed
low-complexity relational ranker reproduced it with a much smaller successful
prefix and lower recorded proof time. The Gate 2 LLM-specific set is therefore
empty.

This gate also separates candidate discovery from proof use. A formula set can
help IC3IA without being an inductive invariant itself, because predicates are
abstraction vocabulary. That does not make the candidate provider unique, and
it does not remove the requirement for the final original-model proof.

## 5. Representation, phase, and grammar falsification

The paired representation study was designed before its LLM outcomes. It
pinned source, translation, and control-program revisions; censused 267
official translated tasks; retained 164 eligible source/BTOR pairs; and froze
a content- and family-independent 20-task pilot.

Each task was rendered in three matched views:

1. source C;
2. a target-derived lifted recurrence summary;
3. a raw BTOR2 property-cone sketch.

The LLM did not emit free-form proof text. It emitted a strict grammar route,
which a deterministic expander turned into predicates. Global and
phase-conditioned candidates were checked directly and then, if needed, used
only as IC3IA abstraction predicates on the original target.

The 60-call capture produced 36 valid and 24 invalid routes. Across 12 safe
baseline-hard tasks, the source, lifted, and raw arms solved one, one, and two
tasks respectively. A deterministic structural router covered the three-task
union. Source produced no unique task. Phase conditioning added one independent
task over the matched global route, below the threshold of three. All 12 routed
UNSAT results passed independent original-model certification, and no unsafe
control became UNSAT.

The gate therefore separates soundness from utility: soundness passed, while
the source-representation, phase-generalization, and LLM-routing hypotheses
failed their frozen thresholds.

## 6. Nonlinear proof calculus

A modular algebraic kernel was implemented to check identities over
`Z/(2^w)Z` without unsound division or cancellation. It validates polynomial
inductiveness certificates on `fib_23` and `fib_30`, and a 20-case negative
suite rejects malformed, unsupported, false-initial, and unsafe cases at the
expected stages.

The natural utility hypothesis was not run. In the frozen 267-task population,
39 tasks require arrays, 221 have no supported nonlinear update SCC, and all
remaining nonlinear SCCs exceed the frozen eight-branch cap. The v1 natural
primary population is therefore empty. Development controls demonstrate that
the checker is not vacuous; they cannot substitute for the absent population.

This is a population mismatch, not evidence that the kernel is ineffective on
an appropriate independently selected corpus. It also does not authorize
expanding the language after seeing the near misses.

## 7. Inductiveness-gap decomposition

Six frozen nonlinear candidates were examined to determine whether the next
problem was missing helpers, deeper induction, or proof-graph organization.
All six fail earlier: each equality is false in an initial state. C1 is SAT,
and exact Houdini removes the candidate during initial filtering. Their
one-step counterexample cubes are also reachable in the bounded checks.

Consequently, proof graphs, stronger induction, and helper search do not repair
the measured obligation. They would repair or replace false conjectures after
inspection, which is a different experiment. The result authorized only the
separately preregistered transport population census.

## 8. Certified transport population gate

The transport proposal asked whether an already certified source invariant
could be moved through exact known maps into three non-trivial target
representations: modular affine recoding, bit-vector split/merge, and an
input-latched stuttering refinement. Alpha-renaming was explicitly only a
sanity control.

Gate 5A0 ran before any transformed variant was generated. It required at
least 12 certified safe bases, eight independent families, the required
invariant classes, at least eight applicable bases for each primary transform,
three input-driven T3 families, and four unsafe controls.

The census found 11 certified bases and only six T1-applicable bases. All other
population conditions passed. Per the frozen rule, the project stopped before
generating a transformed BTOR2 file, validating a map, measuring proof reuse,
or calling an LLM. Transport utility therefore remains not run and unknown.

Eight potential interpolation-invariant recovery rows were unavailable because
the pinned local ASan Pono executable could not reserve shadow memory under the
inherited finite hard address-space limit. The official gate did not switch
binary, machine, memory policy, solver, or threshold after inspecting the
population. This limitation must remain visible; it cannot be used to
retroactively refill Gate 5A0.

## 9. What the study establishes

The strongest supported conclusion is about evaluation:

> LLM-generated hints can appear highly effective when assumptions,
> abstraction predicates, candidate validity, and proof success are
> conflated. Under original-model certification, matched deterministic
> expressiveness, frozen replay, end-to-end accounting, and preregistered
> stopping rules, the apparent LLM-specific advantage disappears on the
> evaluated software-origin BTOR2 populations.

The study also establishes a reusable trust boundary:

- LLM output is an untrusted proposal.
- Predicate injection may guide abstraction but does not certify a candidate.
- C1/C2/C3 all-UNSAT or a model check on the original transition system is
  proof evidence.
- SAT counterexamples refute; UNKNOWN has no evidential direction.
- Every BAD property, model hash, candidate hash, and frozen population must be
  explicit.

## 10. What the study does not establish

The results do not show that LLMs are never useful for verification. They do
not evaluate every invariant language, model checker, source verifier, or
compiler mapping. The algebraic and transport utility hypotheses are not-run,
not negative utility measurements. The corpus contains important selection and
representation constraints, and only one principal LLM/provider configuration
was used in the major captures.

The project also does not support a main-track coverage-improvement claim. Its
appropriate outputs are a thesis chapter, technical report, artifact or
reproducibility paper, workshop paper, student forum submission, or empirical
experience report centered on soundness and evaluation methodology.

## 11. Reproducibility and frozen boundary

The research program is frozen at:

```text
tag:    soundness-audit-final-v1
commit: 6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c
```

The canonical entry points are listed in
[`final_claim_ledger.md`](final_claim_ledger.md) and bound by
[`../artifacts/final_research_summary_v1.json`](../artifacts/final_research_summary_v1.json).
Each referenced modern gate artifact has a file hash and, where available, a
recursive integrity manifest. The early constraint audit predates the unified
artifact schema; its limitation is recorded rather than hidden by fabricating a
retroactive result bundle.

Commit `536a1753f5bb8c0be475dd5f7700045f11ab9f14` is a post-boundary
methodology addendum. It freezes an Oracle-First capability index and a public
external-artifact availability census, but runs no new Pono mechanism,
transformation, proof repair, or LLM/API experiment. It does not alter the
research boundary, claim ledger, or stopping decision.

Known environment limitations remain part of the record:

- the Gate 5 ASan/virtual-address incompatibility;
- the local LeakSanitizer failures in two C++ test executables;
- unavailable local Python `smt_switch` bindings for root binding tests;
- a later live OpenRouter integration test timeout, unrelated to the zero-call
  Gate 5A0 artifact.

## 12. Final decision and independent future work

`soundness-audit` is closed. It will not gain a Gate 6, replacement population,
new prompt, provider swap, repaired false candidate set, or expanded operator
language.

A future cross-tool soundness and matched-baseline audit is a separate research
question. It requires a new branch or repository, an independently selected
population, a fresh preregistration, and no use of current success/failure cases
as selection criteria. Likewise, translation-validated proof reuse or
source-level verifier-guided repair would be new projects rather than
extensions of this hypothesis tree.

The central research success is procedural: the project stopped when its
evidence no longer supported the desired positive claim, without changing the
proof boundary, baseline, population, or threshold to manufacture one.
