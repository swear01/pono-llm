# Gate 4B — Proof-Carrying Modular Algebraic Certificates

**Frozen:** 2026-07-13
**Branch:** `soundness-audit`
**Status:** Gate 4B0 complete — **STOP**; H5a not run because the frozen
population contains no v1-eligible natural task; H5b was not authorized

## Research Question

Can an exact, small checker validate nonlinear fixed-width inductiveness by
checking a supplied polynomial identity over `Z/(2^w)Z`, instead of asking a
generic SMT or IC3IA backend to rediscover the proof through nonlinear
bit-vector search?

This gate separates two hypotheses:

- **H5a — kernel value:** modular algebraic certificates improve proof capacity
  or cost on natural nonlinear recurrences.
- **H5b — LLM value:** after H5a passes, an LLM proposes useful invariant bases,
  multipliers, residuals, or branch decompositions that the frozen bounded
  deterministic synthesizer does not find at matched cost.
- **H5c — soundness:** every accepted result is independently checkable on the
  original BTOR2 model, with zero false-safe controls.

Gate 4B0 tests H5a and H5c only. It makes no paid API calls. H5b remains blocked
until the deterministic kernel and natural population pass the gates below.

## Official Gate 4B0 Result

The canonical artifact is
[`artifacts/algebraic_certificate_v1/`](../artifacts/algebraic_certificate_v1/),
generated from implementation commit
`9e7e677507ad2baf9f357bc4ace52f80a457908d`. Its final summary SHA-256 is
`b0eb02c55af94cab2e232f920446edd4d98462368ee50be5183fcbeef8820ef5`, and
the recursive integrity-manifest SHA-256 is
`b0099cf1ea68d2ab92820e914fedf8f97a0a3b01657ac74a5f0f825db7d38056`.
No LLM or paid API call was made.

### Frozen-population outcome

The structural selector evaluated all 267 tasks in the already frozen Gate 3
official translated corpus without inspecting certificate success:

| Exclusion/selection result | Tasks |
|---|---:|
| array theory | 39 |
| no v1-supported nonlinear update SCC | 221 |
| nonlinear SCC exists, but exceeds the frozen eight-branch cap | 7 |
| eligible after source-family/content deduplication | **0** |
| available expected-safe baseline-hard primary tasks | **0** |
| available expected-unsafe primary controls | **0** |

The seven branch-cap near misses are `egcd2-ll`, `egcd3-ll`, `prod4br-ll`, and
`ps3-ll` through `ps6-ll`. Across them the scanner observes nine nonlinear
SCCs, and all nine exceed the preregistered branch cap. The cap, operator set,
width contract, and population were not widened after this observation.

Consequently, **H5a is not run**, rather than passed or failed: there is no
eligible natural primary obligation on which to evaluate the three-family
threshold or the B0 criterion. **H5b remains not authorized.** This result does
not show that modular certificates work on natural recurrence families, and it
does not justify synthetic examples as replacements for the absent population.

### Development-control reconnaissance

`fib_23` and `fib_30` remain non-primary controls. Five sequential trials per
task produced:

| Configuration | `fib_23` | `fib_30` |
|---|---:|---:|
| pinned Z3 4.13.1 integer blasting, exact C2 | UNSAT 5/5; 0.0287s | UNSAT 5/5; 0.0226s |
| local Z3 4.15.4 integer blasting, exact C2 | UNSAT 5/5; 0.0638s | UNSAT 5/5; 0.0478s |
| modular kernel core C2 | accepted 5/5; 0.00118s | accepted 5/5; 0.00117s |
| complete C1 + kernel C2 + C3 | accepted 5/5; 0.0116s | accepted 5/5; 0.0141s |
| plain IC3IA/Bitwuzla on the original model | UNKNOWN 5/5; 1.07s median | UNKNOWN 5/5; 1.34s median |
| certified-basis IC3IA/Bitwuzla | UNSAT 5/5; 9.95s | UNSAT 5/5; 16.12s |

Times are median wall seconds. Kernel-core timing is in-process, whereas Z3
timing includes a solver process, so the exploratory 24.4x/19.3x ratios are not
paper-quality like-for-like speedups and do not count toward H5a. Python Z3
4.16.0, local/pinned default Z3, and the explicitly activated pinned PolySAT
configuration each returned UNKNOWN in all ten control trials at the 20-second
solver limit. The PolySAT checkout is clean at
`16fb86b636047fd79ad5827f768b6f26d8812948`, and its mandatory independent
probe emitted `:polysat-*` statistics; parameter availability alone was not
accepted as activation evidence.

### Soundness and decision

- both development certificates pass original-model C1/kernel-C2/C3;
- all 20 malformed, provenance-tampered, unsupported, false-initial, and unsafe
  controls are rejected at their expected stage;
- wrong multipliers reach algebraic C2 rejection, the false-initial model
  reaches C1 SAT, and the unsafe model reaches C3 SAT;
- accepted false-safe controls: zero;
- primary H5c is not run because there is no primary population.

Gate 4B0 therefore stops without a positive or negative H5a verdict. Do not
post-hoc raise the branch cap, widen v1, substitute synthetic tasks, or start an
LLM capture under this gate. The next independent research gate is the
**known-map certified-transport oracle** described in
[`roadmap.md`](roadmap.md).

## Trusted Boundary

For one fixed width `w`, an invariant basis is a list of polynomial equalities

```text
P_0(X) = 0, ..., P_(m-1)(X) = 0  modulo 2^w.
```

For every branch `b` extracted by the checker from the BTOR2 next-state
functions, a certificate supplies multiplier polynomials `Q[i,j,b](X,U)` and
claims

```text
P_i(T_b(X,U)) = sum_j Q[i,j,b](X,U) * P_j(X)  modulo 2^w.
```

The checker expands both sides into canonical sparse polynomials, normalizes
every coefficient modulo `2^w`, and requires exact coefficient-map equality.
No division, cancellation, field assumption, sampling, model fitting, or SMT
result is trusted for C2. Zero divisors in `Z/(2^w)Z` do not affect soundness
because acceptance is a direct ring identity.

The complete safety decision remains:

```text
C1: Init && Constraints && !H       is UNSAT on the original BTOR2
C2: every extracted branch identity is accepted by the algebraic kernel
C3: H && Constraints && BAD         is UNSAT on the original BTOR2
```

Only C1 UNSAT, every C2 identity accepted, and C3 UNSAT is a certificate. SAT,
UNKNOWN, timeout, malformed input, missing branch, unsupported operator, or
hash mismatch rejects the certificate. The algebraic configuration never
falls back to generic C2 solving. Generic Z3 and Pono are separate baseline
configurations.

## v1 Kernel Contract

Gate 4B0 deliberately supports only:

- scalar bit-vector state and input variables;
- one explicit common width per polynomial component;
- modular constants;
- `add`, `sub`, and `mul` expression nodes;
- equality invariants represented as residual polynomials;
- functional next-state expressions;
- complete, checker-derived `ite` branch enumeration;
- at most 8 consistent branches;
- sparse monomials with non-negative integer exponents.

The checker rejects arrays, division, remainder, shifts, comparisons inside
polynomial expressions, quantifiers, `concat`, `slice`/`extract`, mixed-width
arithmetic, arbitrary `uext`/`sext`, and incomplete next-state definitions.
Constant-only extension nodes may be normalized only if the normalizer proves
their exact resulting modular constant; this exception is syntax normalization,
not mixed-width polynomial arithmetic.

Branch guards are extracted from BTOR2 and used only to enumerate complete
functional branches. A certificate cannot declare, remove, or weaken a branch.
The v1 algebraic identity must hold unconditionally for each extracted branch;
guard assumptions are not used to justify coefficient equality.

## Certificate Schema

The frozen schema identifier is
`pono-modular-algebraic-certificate-v1`. Every document records:

```json
{
  "schema": "pono-modular-algebraic-certificate-v1",
  "benchmark_id": "portable/relative/model.btor2",
  "benchmark_content_sha256": "...",
  "candidate_sha256": "...",
  "width": 19,
  "variables": ["state7", "state10", "state13"],
  "invariants": [
    {
      "id": "P0",
      "terms": [
        {"coefficient": "2", "powers": {"state13": 1}},
        {"coefficient": "-1", "powers": {"state7": 2}},
        {"coefficient": "1", "powers": {"state7": 1}}
      ]
    }
  ],
  "branches": [
    {
      "id": "<checker-derived-branch-id>",
      "guard_identity": "<checker-derived-guard-id>",
      "next_state_substitution": {
        "state7": [
          {"coefficient": "1", "powers": {"state7": 1}}
        ]
      },
      "multipliers": [[[{"coefficient": "1", "powers": {}}]]]
    }
  ]
}
```

`candidate_sha256` binds the ordered invariant-basis document. Terms, invariant
IDs, variable order, branch IDs, guard identities, complete next-state
substitutions, and matrix dimensions are strict. The checker reconstructs all
branch data from the original BTOR2 before checking multipliers. Duplicate
terms are combined modulo `2^w`; a zero polynomial is rejected as an invariant.
Unknown fields and missing fields are errors. The checker reports a canonical
certificate SHA-256 but never rewrites a rejected document.

## Gate 4B0 — Solver Reconnaissance

Before measuring the new kernel, build an immutable C2 query corpus from known
correct invariant bases. Each row binds:

- portable benchmark ID and original BTOR2 SHA-256;
- candidate/invariant-basis SHA-256;
- exact C2 query SHA-256;
- bit width, state/input count, branch count, polynomial degree;
- Z3 version and complete parameterization;
- Pono binary hash and engine invocation;
- result, reason-unknown, wall time, CPU time, and peak RSS.

Required baseline configurations are:

1. current `z3.Solver` C2 through `candidate_cert_check.py`;
2. the PolySAT paper implementation pinned to Z3 commit
   `16fb86b636047fd79ad5827f768b6f26d8812948`, invoked with the paper's
   explicit `sat.smt=true tactic.default_tactic=smt smt.bv.solver=1`
   configuration;
3. current Pono/Bitwuzla path on the original model;
4. the modular certificate kernel.

Pono is measured in a separate original-model matrix with explicit `bzla`:
plain IC3IA and IC3IA seeded with the already-certified polynomial basis. It is
not mixed into generic C2-query timing or used to compute a kernel C2 speedup.
Every BAD property is invoked explicitly.

The local default Z3 build is a separate arm. The experiment must not claim
that PolySAT ran merely because a Z3 build exposes `smt.bv.solver=1` or contains
PolySAT-related strings. The executable hash, source commit, complete command,
parameters, and solver statistics are required evidence; build or invocation
failure records the arm as unavailable and stops for diagnosis rather than
silently substituting another solver.

### B0 kill criterion

Stop the new kernel before population work if the best existing exact solver is
stable below one second on the primary nonlinear C2 obligations, or if the
kernel is less than 3x faster and adds no decisive result. In that case the
bottleneck is integration or candidate organization, not arithmetic checking.

`fib_23` and `fib_30` are development controls only. They test normalization,
branch completeness, modular wraparound, and agreement with the existing
direct certificates. They do not count toward H5a.

## Primary Population Contract

Population selection happens before any LLM call and before inspecting kernel
success. The source is the official translated corpus already pinned by Gate 3.
A task is eligible solely from structure and metadata:

- expected safe;
- scalar bit-vectors, no arrays;
- functional next-state relation;
- one BAD or an explicitly enumerated BAD set;
- a state-update SCC containing `var * var` or inferred polynomial degree >= 2;
- every relevant next expression fully translatable by the v1 contract;
- at most 8 extracted branches;
- one width per polynomial component;
- source-family/content deduplication.

Select 12–20 baseline-hard safe tasks from at least three recurrence families
and 4–6 expected-unsafe controls. A source family contributes at most one
primary task. Selection cannot use an LLM judgment, a known successful proof,
or resemblance to `fib_23`/`fib_30`.

At minimum, the selected population must contain natural examples of:

1. conserved residuals `P(X') = P(X)`;
2. mutually inductive polynomial bases;
3. guarded branch recurrences with different multiplier matrices.

Division/remainder, arrays, quantified memory, nonlinear inequalities,
number-theoretic gcd/lcm properties, square-root loops, and unsupported mixed
widths are excluded and counted explicitly.

## Matched Deterministic Baselines

Before H5b, freeze a bounded deterministic synthesizer with explicit caps for:

- invariant-basis degree;
- multiplier degree;
- coefficient magnitude/domain;
- number of variables and basis polynomials;
- branch count;
- total search nodes and wall time.

The comparison language and checker are identical for deterministic and LLM
certificates. Deterministic search may use exact linear algebra over modular
coefficient equations, but it may not inspect frozen LLM output or post-hoc
rank candidates using a successful task.

## Preregistered Decisions

### H5a — kernel value

Pass only if at least three independent natural source families obtain an
accepted certificate and each provides at least one of:

- generic exact C2 times out while the kernel succeeds;
- IC3IA/Pono times out while C1+kernel-C2+C3 succeeds;
- the kernel is at least 10x faster than the best exact generic C2 baseline.

Development controls and synthetic models do not count. Otherwise stop Gate
4B after documenting the negative result.

### H5b — LLM value

Run only after H5a passes. Pass only if either:

- LLM certificates solve at least three independent families not solved by the
  frozen bounded deterministic certificate search; or
- LLM preserves at least 90% of deterministic-oracle solves, reduces total
  certificate search nodes/candidates by at least 10x, and remains faster after
  generation latency is included.

Shorter proof text or fewer candidates without solved-set or end-to-end value
does not pass.

### H5c — soundness

- zero false-safe expected-unsafe controls;
- 100% rejection of the malformed-certificate suite;
- unsupported operators and widths explicitly rejected;
- UNKNOWN never accepted;
- C1/C3 always checked on the original BTOR2;
- every input, certificate, query, executable, and result bound by SHA-256;
- no repair, fallback, or manual certificate patching.

Any false-safe result stops the gate immediately and starts a soundness audit.

## Execution Order

1. Freeze this document and Gate 3 artifacts; do not repair Gate 3 routes.
2. Build the fixed C2 query corpus and record the existing solver matrix.
3. TDD the minimal sparse-polynomial kernel and malformed-certificate suite.
4. Re-run the same corpus with the kernel and apply the B0 kill criterion.
5. If B0 survives, freeze the natural primary population and deterministic
   synthesis caps.
6. Run H5a/H5c without an LLM.
7. Only after H5a passes, perform one strict, single-shot frozen LLM capture for
   H5b; expand to repeated captures only on a preregistered positive signal.

The first implementation does not modify Pono C++, add a generic SMT fallback,
perform proof repair, support inequalities, or invoke a CAS/Gröbner engine.

## Amendment Policy

This protocol is frozen by a dedicated Git commit before official Gate 4B0
measurements. Any pre-measurement correction requires a new commit that states
the reason and preserves the prior text in history. After the first official
solver matrix is written, the population contract, hypotheses, thresholds, and
kill criteria are immutable. Implementation bugs may be fixed only with a
versioned artifact rerun; earlier results remain preserved and are never
overwritten.

### Pre-measurement implementation amendment (2026-07-13)

Before the first official solver matrix, the v1 serialization was hardened to
bind `candidate_sha256`, checker-derived guard identities, and complete
next-state substitutions. Pono measurements were separated from C2-query
solver timings and split into plain versus certified-basis IC3IA arms. This
changes no population rule, hypothesis, threshold, branch cap, or kill
criterion; it prevents provenance ambiguity and cross-obligation timing.
