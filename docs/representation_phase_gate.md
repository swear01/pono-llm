# Representation-Aware Phase-Local Grammar Gate v1

**Status:** complete; all utility hypotheses failed, soundness passed
**Started:** 2026-07-12
**Branch:** `soundness-audit`

## Objective

The corrected Phase 1+2 and Gate 2 experiments leave zero LLM-specific solves
relative to the tested engine plus deterministic affine/quadratic portfolio.
This gate therefore does not test whether an LLM can express a formula outside
that portfolio. It tests three narrower hypotheses:

1. phase-conditioned templates prove natural software-origin tasks that the
   same global template language cannot prove;
2. source C exposes enough semantic structure to improve grammar and variable
   routing relative to a target-derived lifted recurrence and a raw-BTOR2 view;
3. under matched formal expressiveness, LLM routing reduces formal search more
   than deterministic structural routing after generation latency is included.

The gate ends with an explicit pass/fail decision for each hypothesis. Building
infrastructure without executing the matched experiment does not complete the
gate.

## Trusted Boundary

LLM output is an untrusted grammar route. It never becomes a BTOR2
`constraint`, `assume`, initialization fact, or transition restriction.

A route is expanded deterministically into predicate ASTs. In global mode the
AST is used directly. In phase-local mode each AST `I` is wrapped as
`phase => I`, and the conjunction

```text
H = AND_phase,candidate (phase => candidate)
```

is checked on the original BTOR2 model:

```text
C1: Init && constraints && !H                 UNSAT
C2: H && constraints && Trans && !H'          UNSAT
C3: H && constraints && BAD                   UNSAT
```

Only all-UNSAT C1/C2/C3 is a direct certificate. A non-certified predicate set
may be supplied to IC3IA only through `--initial-predicates`, where it extends
the abstraction vocabulary without under-approximating the concrete model.
`unknown` is never evidence. Expected-unsafe controls must never become safe.

Source/state or source/location metadata is not trusted for the safety verdict:
the resulting target-state formulas are still checked on the original BTOR2.
Bad metadata can reduce utility or invalidate a representation claim, but it
cannot justify accepting a failed target-level certificate.

## Route Schema

The shared output schema is `pono-llm-grammar-route-v1`:

```json
{
  "schema": "pono-llm-grammar-route-v1",
  "routes": [
    {
      "variables": ["i", "sum"],
      "family": "quadratic_recurrence",
      "relations": ["eq"],
      "signedness": "signed",
      "scales": [1, 2, 3, 4],
      "counter_shifts": [-1, 0, 1]
    }
  ]
}
```

The parser is strict: unknown fields, ambiguous symbols, duplicate variables,
mixed widths, invalid relation/signedness combinations, and out-of-contract
coefficient domains are errors. Routes and expanded predicate sets use
canonical JSON and SHA-256 identities.

v1 separates grammar selection from phase selection. The experiment runner
chooses either global mode or deterministic expansion over every extracted PC
phase. The LLM does not choose a source location in the primary experiment.
This avoids confounding representation quality with an unvalidated
source-location-to-PC map. Specific phase routing is deferred until the
all-phase experiment demonstrates value.

## Supported Grammar Families

v1 supports a bounded language already covered by, or directly comparable to,
the corrected deterministic baselines:

- `unary`: state versus an initialization/small constant;
- `pairwise_offset`: `x` versus `y + c`;
- `affine`: two- or three-variable normalized affine relations;
- `sum_equality`: one variable versus the sum of two others;
- `quadratic_recurrence`: `scale * accumulator` versus
  `counter * (counter + shift)`.

Relations are `eq`, `le`, and `ge`. `le`/`ge` compile to signed or unsigned BV
comparisons according to the route. Equality is independent of signedness.
The backend, not the LLM, constructs constants, modular negatives, and ASTs.

## Phase Contract

The first implementation supports only functional CPV/Kratos encodings with:

- exactly one explicit scalar program-counter state named `!pc`;
- an initialization and next expression for that state;
- finite PC constants appearing in equality tests with the PC;
- scalar bit-vector data states;
- exactly one BAD property for the paired pilot.

Each phase has a stable identity derived from the PC state, width, and value.
Missing or extra phases cannot make a certificate unsound because every
guarded formula is checked at target level. The extractor must not silently
guess a PC when the contract is ambiguous.

Generic RTL phase inference, relational `valid` encodings, CFG reconstruction,
and source-location mapping are outside v1.

## Paired Corpus Contract

The primary population is the pinned SV-COMP 2025 `safety-func` translation
set. Every selected task records:

- translation, source, and CPV revisions;
- source and BTOR2 relative paths and SHA-256 digests;
- expected verdict and property count;
- stable source-family identity;
- unique source-symbol-to-`stateN` mapping;
- PC state, width, initialization, and extracted phase values;
- structural eligibility and exclusion reason;
- deterministic baseline outcomes used for selection.

Selection happens before LLM results. Exact-content duplicates and related
parameter/unwind variants are grouped by source family. The target pilot is 20
independent tasks: 12 safe baseline-hard tasks, four safe controls, and four
unsafe soundness controls. If the eligible population is smaller, the actual
population is reported without padding or silent relaxation.

## Representation Arms

All arms share the exact route instructions, machine-model footer, variable
catalog, output budget, route cap, model, and formal backend.

1. **source:** original pinned C source;
2. **lifted:** a target-derived decoded transition/property recurrence with
   handcrafted invariant examples and role guesses removed;
3. **raw:** a deterministic BTOR2 property/transition cone preserving node IDs,
   operations, dependencies, state/init/next/constraint/BAD structure, and
   original symbols.

The primary comparison uses a deterministic cap of 6,000 lexical tokens under
the documented Unicode regex tokenizer. Full natural prompts are frozen beside
the capped prompts. Exact provider prompt/completion/total tokens are recorded
for every API call; the lexical cap is not misreported as the provider's model
tokenizer.

## Baselines and Matrix

Proof organization:

- global templates;
- all-extracted-phase guarded templates.

Routers:

- exhaustive bounded grammar;
- random budget-matched routing;
- deterministic BAD/transition-structure routing;
- frozen LLM routing;

LLM routing is evaluated separately for source, lifted, and raw views. The
formal candidate language and proof budgets remain identical.

The canonical bounded exhaustive grammar uses at most six source-mapped states,
constants 0/1 plus exact initial values, offsets `0, ±1, ±2`, affine coefficient
bound 2, consecutive-counter quadratic templates, and both signed and unsigned
comparisons. The fixed structural router uses at most eight routes chosen from
BAD/transition dependencies and signed C-like comparisons. Random routes are
candidate-budget matched to each valid LLM route.

## Executed Result

The official pinned population contains 267 translated tasks. Of these, 164
meet the scalar, single-BAD, functional-PC, and at-least-two-source-mapped-state
contract: 144 expected safe and 20 expected unsafe. The engine screen returns
32 UNSAT, 10 SAT, 38 UNKNOWN, and 84 timeout. A fixed-seed, exact-content- and
source-family-independent pilot was frozen before LLM calls: 12 safe
baseline-hard tasks, four safe controls, and four unsafe soundness controls.

The historical full21 route audit matches 158/353 formulas (44.76%) exactly,
modulo semantic no-op normalization, to the bounded grammar. This justified a
single paired capture, not a positive routing claim.

The paired capture made 60 OpenRouter calls (`deepseek/deepseek-v4-flash`,
reasoning disabled, temperature 0), consuming 142,814 total tokens and 229.16s
wall latency. Strict validation accepts 36/60 routes and rejects 24/60. Invalid
outputs are retained with exact width, arity, duplicate-variable, duplicate-
parameter, parameter-range, or candidate-cap errors; there is no repair or
fallback.

On the 12 baseline-hard tasks, all-phase solved sets are:

| Router/view | Solved tasks |
|---|---|
| LLM source | `benchmark05_conjunctive` |
| LLM lifted | `count_up_down-1` |
| LLM raw | `gj2007b`, `benchmark05_conjunctive` |
| random source | `count_up_down-1` |
| random raw | `gj2007b`, `count_up_down-1` |
| deterministic structural | all three above |

The structural global route solves `gj2007b` and
`benchmark05_conjunctive`; its all-phase form additionally solves
`count_up_down-1`. Thus phase conditioning adds one independent baseline-hard
proof, below the threshold of three. Source has zero unique proofs. No LLM arm
beats or adds a task over deterministic structural routing. Median formal
candidate reductions relative to the fixed-budget exhaustive pool are large
(source 81.67x, lifted 61.25x, raw 20.42x), but they do not establish LLM value
because the deterministic router covers the full three-task union and avoids
API latency.

Every one of the 12 routed UNSAT rows was independently audited on the original
BTOR2: four candidate conjunctions directly pass C1/C2/C3; eight Pono-returned
invariants independently pass C1/C2/C3. No unsafe control became UNSAT.

Canonical evidence is under
[`artifacts/representation_phase_v1/`](../artifacts/representation_phase_v1/).
This is one frozen capture per benchmark/view. Reliability and bootstrap
inference were preregistered secondary metrics but are not claimed: H2/H3 fail
the first gate, so repeated paid captures were not used to rescue the result.

## Primary Metrics

- direct C1/C2/C3 certificates;
- IC3IA-assisted original-model verdicts;
- expected-unsafe verdict preservation;
- unique natural solves by source family;
- route count and expanded/deduplicated candidate count;
- candidates and SMT queries tested before the first certificate;
- Houdini initialization/step query counts;
- certificate, model-checker, offline, generation, and end-to-end time;
- token usage and immutable prompt/response/route/candidate hashes;
- independent-capture reliability;
- family-level paired statistics and bootstrap confidence intervals.

The grammar reduction factor is:

```text
number of exhaustive candidates / number of routed candidates
```

Proof-only savings are reported but do not establish practical value unless
they survive end-to-end accounting.

## Pre-Registered Decisions

### H1 — Phase-local value

Pass only if phase-local templates add at least three independently grouped
natural safe proofs over the matched global language. Otherwise automatic
phase work stops after this gate.

**Decision: fail (1/3).** Retain `count_up_down-1` as a bounded positive case;
do not scale automatic phase extraction from this result.

### H2 — Representation value

Pass only if source routing adds at least three independent-family proofs over
both raw and lifted routing, or preserves the matched solved set with a robust,
substantial reduction in formal queries and end-to-end cost. If source provides
no upper-bound signal, a general BTOR recurrence lifter is not built.

**Decision: fail.** Source routing has zero unique solved family. Raw is the
strongest LLM view on this pilot, but both raw solves are covered by the
deterministic structural router.

### H3 — LLM routing value

Pass only if LLM routing preserves at least 90% of the exhaustive-oracle solved
set, reduces formal candidate/check counts by at least 10x, beats the best
deterministic structural router, and retains a net advantage after generation
latency. Otherwise the LLM-specific routing claim is rejected; deterministic
phase/grammar results may remain.

**Decision: fail.** The fixed-budget exhaustive all-phase run solves no
baseline-hard task, so exhaustive preservation is undefined rather than
vacuously 100%. Against the non-empty deterministic structural reference, the
source/lifted/raw arms preserve 1/3, 1/3, and 2/3 and add zero unique tasks.

### H4 — Soundness

Every claimed safe result must be a direct target-level certificate or a sound
Pono result on the original BTOR2. Any false safe result on an expected-unsafe
control stops the gate and triggers a soundness audit.

**Decision: pass.** False-safe count is zero; 12/12 routed UNSAT rows have an
independent target-level certificate.

## Execution Gates

1. **Complete:** run the existing frozen full21 captures through route classification before
   making new API calls. If structural routing dominates, do not spend a large
   routing-capture budget merely to improve a negative result.
2. **Complete:** run deterministic global versus all-phase templates on the frozen paired
   pilot. Large LLM capture begins only if H1 has a signal or the frozen route
   audit shows plausible semantic-routing value.
3. **Complete:** freeze prompts/routes/responses before replay. Replay never calls the LLM.
4. **Complete:** finish with canonical matrices, source hashes, immutable integrity files,
   and an explicit H1/H2/H3/H4 decision.

## Explicit Non-Goals

- LLM formula generation as the primary comparison;
- BTOR2 constraint/assumption injection;
- open-ended prompt tuning;
- another broad scan of the already exhausted raw-HWMCC population;
- generic BTOR2 decompilation or CFG reconstruction;
- relational `valid`-encoding lifting;
- iterative C1/C2/C3 repair;
- learned predicate ranking;
- arrays, transport/metamorphic transformations, polynomial proof kernels, or
  predicate-aware BVMul CEGAR.

This experiment did not meet H1, H2, or H3. Do not scale phase extraction,
source lifting, or grammar-routing captures by moving the threshold after the
fact. A continuation requires a new, separately preregistered hypothesis.
