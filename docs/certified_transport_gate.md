# Gate 5 — Known-Map Certified Transport Oracle

**Frozen:** 2026-07-13
**Branch:** `soundness-audit`
**Status:** preregistered; Gate 5A0 population/protocol feasibility is next;
no transformation implementation, utility experiment, map inference, or LLM
capture is authorized by this commit

**Execution status (2026-07-13; not a protocol amendment):** the Gate 5A0
population/schema implementation now exists and passes its focused tests. The
canonical census has not yet been run, no transformed variant exists, and all
frozen thresholds below remain unchanged.

## Research Question

Can an invariant already certified on a source BTOR2 transition system be
reused soundly and substantially more cheaply after a non-trivial change to
state representation or transition granularity?

This is an upper-bound proof-reuse experiment. It does not ask an LLM to infer
a map, generate an invariant, or repair a failed proof. The map is exact and
known by construction, but the transformation implementation is not trusted.
An independent validator must prove the map obligations for the concrete
source/target pair, and the transported invariant must still pass C1/C2/C3 on
the transformed original BTOR2.

The gate has three stages:

1. **Gate 5A0 — population/protocol feasibility:** establish a sufficiently
   diverse immutable source-certificate population, strict map schema, three
   non-trivial primary transformation families, independent validation
   obligations, soundness controls, and a fair regeneration baseline.
2. **Gate 5A — known-map oracle:** generate frozen transformed variants, prove
   the concrete maps, transport source certificates, re-certify them on the
   targets, and compare unamortized cost with regeneration.
3. **Gate 5B — hidden-map recovery:** authorized only if Gate 5A passes. It
   starts with deterministic/symbolic recovery; LLM map proposals remain last.

Gate 5A0 performs no utility comparison and makes no API call. If its
population or protocol thresholds are not met, the entire transport direction
stops before producing a large synthetic variant corpus.

## Non-Goals

This gate does not:

- reopen Gate 4B0 by increasing its branch cap or algebraic language;
- count `fib_23`/`fib_30` as a natural nonlinear population;
- increase natural benchmark coverage with transformed copies;
- trust a transformation because this repository generated it;
- accept sampling, bounded testing, BMC non-SAT, or SMT UNKNOWN as map proof;
- place a transported candidate into BTOR2 `constraint`/`assume`;
- infer maps with an LLM in Gate 5A0 or Gate 5A;
- treat alpha-renaming as a primary research success;
- enter paper mode merely because exact substitution works.

All transformed results are reported as **metamorphic proof-reuse** results,
separately from natural benchmark coverage.

## Formal Model and Trust Boundary

Let the source transition system be

```text
M = (X, U, I(X), A(X,U), T(X,U,X'), B_0(X), ..., B_(p-1)(X))
```

and the transformed system be

```text
M' = (Y, V, I'(Y), A'(Y,V), T'(Y,V,Y'),
      B'_0(Y), ..., B'_(p-1)(Y)).
```

`A` and `A'` denote the conjunction of all BTOR2 constraints. Every BAD
property is explicit; a checker may not silently keep only the last one.

A known transport map contains a functional target-to-source projection

```text
pi : Y -> X
```

and, where relevant, an input projection `eta` and a source-to-target embedding
`phi`. If `H(X)` is a source invariant that has already passed source-model
C1/C2/C3, its transported target candidate is

```text
H^pi(Y) = H(pi(Y)).
```

The source certificate is reusable evidence, not a target proof. The target
candidate is accepted only when the existing exact checker proves on the
transformed original BTOR2:

```text
C1': I'(Y) && A'(Y,V) && !H^pi(Y)             UNSAT
C2': H^pi(Y) && A'(Y,V) && T'(Y,V,Y')
     && A'(Y',V') && !H^pi(Y')                 UNSAT
C3': H^pi(Y) && A'(Y,V) && B'_k(Y)             UNSAT
     for every BAD property k.
```

SAT rejects the candidate. UNKNOWN, timeout, unsupported syntax, missing BAD,
hash mismatch, malformed map, or incomplete substitution also rejects it.
There is no generic or bounded silent fallback.

Three outcomes are stored separately:

```text
target_certificate_valid
map_validation_valid
transformation_equivalence_valid
```

A wrong map can accidentally produce a candidate that passes target C1/C2/C3;
that target safety certificate remains valid, but the run is not a valid
transport and cannot support a semantics-preservation claim.

## Independent Map Obligations

The validator reconstructs source and target semantics independently from the
two BTOR2 files and the strict map document. It must not call transformation-
generator helpers to reconstruct the expected target relation. Every finite-BV
obligation is discharged by exact SMT; only UNSAT accepts it.

### Common obligations

For every family, validate:

1. source/target bytes, certificate, map, parameters, generator revision, and
   validator revision against recorded SHA-256 values;
2. sort and width correctness of every projection/input/embedding term;
3. complete source-state and BAD-property coverage;
4. target initial-state soundness:

   ```text
   I'(Y) && A'(Y,V) => I(pi(Y))
   ```

5. target BAD observation correspondence for every property;
6. absence of undeclared auxiliary assumptions or model constraints.

### Exact-isomorphism obligations

T0, T1, and T2 have an explicit inverse embedding. In addition to the common
obligations, validate:

```text
pi(phi(X)) = X
phi(pi(Y)) = Y

I'(Y) <=> I(pi(Y))
A'(Y,V) <=> A(pi(Y), eta(Y,V))
T'(Y,V,Y') <=> T(pi(Y), eta(Y,V), pi(Y'))
B'_k(Y) <=> B_k(pi(Y))        for every k.
```

When the input vector is unchanged, `eta` is the explicit identity map; it is
still serialized and checked. Any SAT countermodel invalidates the concrete
variant. UNKNOWN does not establish an isomorphism.

### Stuttering/refinement obligations

T3 is not a one-step isomorphism. Its projection is the vector of committed
source-equivalent registers. Every target step must satisfy exactly one of:

```text
stutter: pi(Y') = pi(Y)

commit:  A(pi(Y), latched_U(Y))
         && T(pi(Y), latched_U(Y), pi(Y')).
```

The validator proves:

1. every target transition is classified by the fixed phase schedule as a
   projection stutter or one source commit;
2. non-commit phases preserve every committed source-equivalent register;
3. phase 0 is the only observation/input-latch point;
4. raw target inputs are copied into `latched_U` at phase 0 and never read by
   later microsteps;
5. every source update is committed atomically, with no omitted or premature
   committed-state update;
6. target constraints at phase 0 are exactly the source constraints under the
   current committed state and raw input; later phases use the latched input;
7. the only target BAD observation is

   ```text
   B'_k(Y) = observe(Y) && B_k(pi(Y));
   ```

8. the phase schedule cannot diverge in internal stuttering and returns to the
   observation phase after the fixed number of microsteps.

To call T3 semantics-preserving rather than merely target-safe, the validator
also proves bounded macro-step completeness by symbolic unrolling: every
admissible source transition from `X` under `U`, starting from the canonical
target embedding `phi(X)` and latching `U`, reaches the next observation state
with projection `X'` in the fixed number of target steps. The reverse target-
to-source simulation and this source-to-target macro completeness are reported
separately.

## Transformation Families

All parameters are deterministically derived from the base-model content hash
and the frozen seeds `11`, `23`, and `47`. There is no retry based on proof or
regeneration outcome. Variants are exact-content deduplicated before execution.

### T0 — Alpha-renaming and BTOR2 node-ID permutation

T0 changes state/input symbols and BTOR2 node numbering without changing the
state representation. It is a mandatory schema, substitution, provenance, and
hash smoke test with expected 100% success.

**T0 is never counted as one of the three primary transformation families and
cannot satisfy H6b, H6c, or H6d.**

### T1 — Invertible modular affine state recoding

For one invariant-relevant same-width state SCC, choose `k` in `{2,3}` and
encode

```text
Y = A*X + b  modulo 2^w.
```

The generator constructs `A` from invertible elementary matrices; equivalently
its determinant is odd in `Z/(2^w)Z`. Every primary matrix must mix at least
two states and must not be a permutation, signed permutation, or diagonal-only
recoding. `b` must contain at least one non-zero component. The exact matrix,
offset, modular inverse, transformed SCC, width, and seed are serialized.

The target transition is generated by exact substitution:

```text
Y' = A * F(A^-1*(Y-b), U) + b  modulo 2^w,
```

and the transported invariant substitutes `A^-1*(Y-b)` for the source states.
No implicit extension or mixed-width arithmetic is permitted.

### T2 — Bit-vector split/merge state encoding

The required primary T2 operation splits an invariant-relevant `w`-bit source
state into two target states:

```text
x = concat(x_hi, x_lo)
x_hi' = extract(w-1, h, F_x)
x_lo' = extract(h-1, 0, F_x).
```

`w >= 4`, `0 < h < w`, and each seed selects a distinct legal split point when
three exist. Every occurrence in init, transition, constraints, and BAD is
rewritten. The projection and inverse embedding explicitly use exact
`concat`/`extract`; regex or symbol-only rewriting is forbidden.

Merging two exact partitions into one state may be reported as a secondary T2
subgroup, but it cannot replace the required split subgroup or rescue a failed
T2 decision. T2 changes state-vector structure and is reported separately from
T1.

### T3 — Input-latched stuttering microstep refinement

T3 converts each source macro-step into a fixed four-phase target schedule:

1. observation/latch: constrain and latch the current source input;
2. compute the first deterministic partition of next-state expressions into
   shadow registers;
3. compute the remaining next-state expressions using only committed states
   and latched inputs;
4. atomically commit every source-equivalent register and return to phase 0.

The target state contains opaque committed registers, shadow/work registers,
latched inputs, and an explicit phase. The projection exposes only committed
registers. Intermediate shadow values are never source-visible. BAD is tested
only at phase 0. Source inputs are allowed to change arbitrarily at every
target step, as BTOR2 permits, but all post-latch phases ignore raw inputs.

The seeds change only the deterministic partition/order of shadow computation;
they do not change the four-phase semantics, observation point, or proof
budget. T3 requires at least two committed source updates. It is the required
non-isomorphic, transition-granularity-changing family: Gate 5 cannot authorize
follow-on work if T3 fails.

## Gate 5A0 Population Contract

Population selection and source-certificate normalization occur before any
transformed variant or regeneration result is inspected.

A safe base task is eligible only if it has:

- immutable dataset-relative BTOR2 identity and source bytes SHA-256;
- scalar bit-vectors and no arrays in v1;
- every BAD property explicitly represented;
- a machine-readable invariant AST using documented exact semantics;
- a source certificate with C1/C2/C3 all UNSAT on the original source BTOR2;
- immutable invariant-AST and certificate hashes;
- a stable source-family identity;
- no dependence on an undocumented solver symbol or local absolute path.

A Pono-returned SMT-LIB invariant may enter only after canonical parsing into
the transport AST, exact source-model recertification, and AST hashing. Raw
invariant strings are never transported by regex substitution.

The locally installed Pono executable is AddressSanitizer-instrumented. If its
`--show-invar` child cannot reserve the ASan shadow mapping under the inherited
hard address-space limit, the census records the deterministic exclusion
`show-invar-runtime-incompatible`; it does not retry with another engine or
silently rebuild Pono.

Gate 5A0 requires all of:

- at least **12 safe base tasks**;
- at least **8 independent source families**;
- at least three represented invariant classes: affine/relational,
  quadratic/polynomial, and phase-guarded or genuinely conjunctive;
- at least **8 applicable base tasks for each of T1, T2, and T3**;
- T3 applicability across at least three input-driven source families, so
  input-latch semantics is exercised rather than only no-input controls;
- at least four independently selected expected-unsafe controls for
  transformation/map-validation soundness;
- exact-content, source-family, parameter, and unwind-variant deduplication.

One source family contributes at most one unit to an independent-family count.
Multiple seeds and transformed variants never increase the base-task or source-
family count. If any population threshold is missing, the canonical Gate 5A0
decision is `population-insufficient` and transport stops without padding from
synthetic models or repeated widths.

## Strict Known-Map Schema

The planned schema identifier is `pono-certified-transport-map-v1`. Its core
shape is frozen as:

```json
{
  "schema": "pono-certified-transport-map-v1",
  "source": {
    "benchmark_id": "portable/source.btor2",
    "sha256": "..."
  },
  "target": {
    "benchmark_id": "transport/T1/source.seed11.btor2",
    "sha256": "..."
  },
  "transformation": {
    "family": "affine-recode",
    "version": 1,
    "seed": 11,
    "parameters": {},
    "parameters_sha256": "..."
  },
  "projection": {
    "state7": {
      "form": "sub",
      "args": [
        {"form": "ref", "ref": "state70"},
        {"form": "const", "const": "1", "width": 8}
      ]
    }
  },
  "input_map": {},
  "inverse_embedding": {
    "state70": {
      "form": "add",
      "args": [
        {"form": "ref", "ref": "state7"},
        {"form": "const", "const": "1", "width": 8}
      ]
    }
  },
  "observation_predicate": null,
  "property_map": [
    {"source_bad_index": 0, "target_bad_index": 0}
  ],
  "generated_map_invariants": [],
  "source_certificate_sha256": "...",
  "generator_commit": "...",
  "validator_version_sha256": "..."
}
```

Projection keys are source `stateN` references; values are target-state ASTs.
The parser rejects unknown fields, missing source states/properties, ambiguous
symbols, wrong widths, duplicate refs, unsupported forms, and mismatched
matrix dimensions. T3 requires a non-null observation predicate and explicit
macro schedule; exact families require a complete inverse embedding.

`generated_map_invariants` must be present and empty in v1. No auxiliary
relation may be hidden in BTOR2 constraints, validator assumptions, or target
certificate premises. A future non-empty relation language would require a new
preregistration and independent target C1/C2 certification for every relation.

## Validation and Soundness Suite

Before the official utility matrix, development controls must prove that the
validator rejects at the expected stage:

- source, target, source-certificate, parameters, generator, or validator hash
  mismatch;
- missing source state, input, BAD property, inverse term, or map branch;
- wrong projection or inverse;
- singular/even-determinant affine matrix;
- incorrect affine inverse or modular offset;
- swapped split halves, dropped bits, overlap, or wrong next-state extraction;
- T3 missing input latch, raw-input reuse after phase 0, wrong latched input,
  omitted/partial commit, committed-state mutation during a stutter phase,
  phase-cycle divergence, premature BAD observation, or missing observation;
- an unsupported AST operator or mixed width;
- a false source certificate or unsafe target candidate;
- injected SMT UNKNOWN/timeout.

All malformed/wrong-map cases must be rejected; none is repaired. Every
expected-unsafe transformed control must remain non-safe. Any accepted false
safe or false semantics-preserving claim stops the gate and starts a soundness
audit.

## Baselines

All configurations consume the same frozen target BTOR2 bytes and BAD set.

### B0 — Identity/no-map reuse control

Apply the source AST using only exact target refs with the same canonical
symbol/width, without structural projection. This is a diagnostic showing
whether the transformation actually changed the representation. It is not a
primary utility baseline and cannot satisfy a threshold.

### B1 — Strong deterministic regeneration

Regenerate a proof from transformed BTOR2 only. B1 receives no source
certificate, map, transformation parameters, or source model. Its fixed
portfolio contains the strongest current no-LLM components available before
variant generation:

- engine baseline (`ind`, `interp`, plain IC3IA);
- `static-ranked` relational seeding;
- balanced affine/static oracle;
- deterministic quadratic oracle;
- deterministic structural grammar routing;
- exact Houdini candidate certification;
- sound IC3IA predicate replay on the transformed original model.

The historical post-hoc origin of `static-ranked` remains disclosed, but using
it here makes regeneration harder to beat and avoids a weak-baseline transport
claim. Portfolio order, candidate caps, and total budget are frozen before the
first transformed result.

### B2 — Known-map transport oracle

B2 receives the certified source invariant, exact known map, and target BTOR2.
It executes, in order:

```text
independent map/transformation validation
-> strict AST substitution
-> target C1/C2/C3
```

Failure at one stage stops that row. B2 does not call the regeneration
portfolio and cannot fall back to an LLM or manual map.

### B3 — Target engine-only

Run `ind`, `interp`, and plain IC3IA on the target without source proof or map.
This arm distinguishes proof reuse from a transformation that merely makes the
target easy for existing engines. B3 is also a separately reported subset of
the broad B1 portfolio.

## Fixed Variants, Trials, and Budgets

For every applicable base/family pair, generate the three frozen seeds
`11,23,47`. A base-family cell counts as accepted only if all its frozen,
content-unique primary variants validate and certify; individual variant rates
are also reported. This prevents easy seeds from hiding a failed map.

Primary execution uses:

- five fresh process trials per variant/configuration;
- one 70-second total end-to-end budget per variant/configuration;
- a 20-second limit per individual exact SMT query within that total budget;
- fixed sequential configuration order and no concurrent benchmark load for
  canonical timing;
- no cross-trial solver/cache reuse.

Infrastructure errors, malformed artifacts, and configuration mismatches stop
the run; they are not converted to UNKNOWN. Logical UNKNOWN/timeout remains an
explicit unsuccessful proof result.

## Cost Accounting and Metrics

Primary B2 cost is unamortized:

```text
T_transport = T_map_validation
            + T_AST_transport
            + T_target_C1_C2_C3.
```

Map validation is never excluded from the primary time. Source-certificate
discovery and transformation generation are reported separately as prior
artifact construction, not hidden inside proof time. A secondary amortized
number may divide one validated map across multiple properties/invariants, but
it cannot satisfy H6c.

Primary B1 cost is:

```text
T_regen = T_candidate_generation
        + T_Houdini
        + T_certificate_or_IC3IA.
```

The fixed portfolio timeout is charged in full. For primary geometric means,
a successful configuration uses its measured end-to-end time; an unsuccessful
configuration is charged the full 70-second budget. This prevents fast
rejection from appearing as a speedup. Both-success uncapped paired speedup is
reported separately.

Required metrics are:

- source and target certificate validity;
- map validation and transformation-equivalence validity;
- variant-level and base-family-cell acceptance;
- fixed-budget solved sets for B1/B2/B3;
- unamortized effective-time geometric-mean speedup overall and per family;
- both-success paired speedup;
- map-validation, AST substitution, C1, C2, C3, generation, Houdini, and IC3IA
  time breakdown;
- candidate and SMT-query counts;
- peak RSS;
- source/transported AST nodes and canonical JSON/SMT2 bytes;
- formula-growth distribution;
- results clustered by original source family, invariant class, and transform
  family;
- all input, map, certificate, executable, command, and result hashes.

Natural source tasks and transformed variants are never combined into one
coverage count.

## Preregistered Decisions

### Gate 5A0 — population/protocol feasibility

Pass only if the complete population contract is met, T0--T3 and the independent
validator can be implemented under the frozen semantics, the expected-stage
negative suite passes, T3 macro-step validation is complete, and B1 can run on
the same target interface. Otherwise stop before the official utility matrix.

T0 success cannot compensate for a missing T1, T2, or T3 population.

### H6a — map and transformation validity

Pass only if:

- every frozen official primary variant passes every required independent map
  obligation with UNSAT and complete hashes;
- every exact family passes inverse/isomorphism validation;
- every T3 variant passes both target-to-source stuttering simulation and
  source-to-target bounded macro-step completeness;
- every wrong-map/transformation negative is rejected at the expected stage;
- there are zero false semantics-preserving claims.

UNKNOWN is rejection. A generator bug discovered after the official variants
are frozen requires a versioned rerun and preserved prior artifact, not removal
of the failed row.

### H6b — transported-certificate correctness

For **each of T1, T2, and T3 separately**:

- base-family-cell transported-certificate acceptance is at least 90%;
- every accepted target proof has C1/C2/C3 UNSAT on the transformed original
  BTOR2 for every BAD;
- false safe is zero;
- every malformed/candidate-soundness negative is rejected at its expected
  stage.

T0 is reported but excluded. Pooled acceptance cannot hide a failed family.

### H6c — proof-reuse utility

Pass only if all hold:

- overall primary unamortized effective-time geometric-mean B1/B2 speedup is
  at least 5x;
- each of T1, T2, and T3 has at least 2x effective-time geometric-mean speedup;
- T3 has at least 90% acceptance and, on at least three independent source
  families, either B2 is at least 5x faster than B1 or B2 succeeds within the
  fixed budget while B1 does not;
- B3 results show the gain is not explained solely by transformed targets
  becoming engine-trivial.

Map validation is included. An amortized-only, proof-text-only, or candidate-
count-only gain does not pass.

### H6d — follow-on authorization

Gate 5B is authorized only if H6a, H6b, and H6c all pass, T3 supplies the
required non-isomorphic utility, and formula growth remains bounded:

- median transported/source AST-node ratio at most 10x;
- no primary transported AST exceeds 50x its source or 50,000 nodes;
- no canonical candidate/query exceeds 5 MiB.

Failure of T3 stops transport research even if T1/T2 succeed. T0/T1-only
success is proof-engineering infrastructure, not authorization for map
inference.

## Gate 5B Ordering

Even after H6d, map inference proceeds in this order:

1. deterministic structural recovery;
2. symbolic/SMT affine or projection synthesis;
3. dependency-graph matching;
4. compiler-emitted mapping metadata;
5. one strict frozen LLM map-proposal capture only if the preceding methods
   fail on at least three independent families where the known-map oracle had
   demonstrated utility.

Every recovered map remains untrusted and must pass the same validator and
target C1/C2/C3. Invalid maps are not repaired before scoring. Gate 3's failed
LLM-over-structural routing result prevents assuming an LLM mapping advantage.

## Decision Table

| Outcome | Decision |
|---|---|
| Source-certificate population below Gate 5A0 threshold | Stop; do not generate a large synthetic corpus |
| Any transform/map negative accepted | Stop and perform a soundness audit |
| T3 validator or macro completeness unavailable | Stop before utility matrix |
| T1/T2 pass but T3 fails | Record proof-substitution infrastructure; stop transport research |
| T1/T2/T3 acceptance passes but H6c fails | Transport is correct but not useful; stop |
| H6a/H6b/H6c/H6d all pass | Authorize deterministic hidden-map recovery |
| Deterministic map recovery matches the oracle | Do not call an LLM |
| Deterministic recovery fails on >=3 oracle-useful families | Permit one frozen LLM proposal capture under a new preregistration |

## Planned Artifact and Reproduction Boundary

No Gate 5 artifact is created by this preregistration commit. A successful
Gate 5A0 implementation will later write a fresh canonical directory:

```text
artifacts/certified_transport_v1/
```

It must contain source population/certificates, transformed BTOR2 files, exact
maps and parameters, independent validation reports, transported ASTs, target
certificates, B0--B3 matrices, all negative cases, commands, tool revisions,
provenance, summary, and a recursive integrity manifest. Partial/smoke runs
cannot be summarized as the official gate.

## Gate 5A0 Implementation Boundary

The implemented census surface is deliberately limited to the first three
planned modules:

```text
scripts/build_transport_population.py
scripts/transport_schema.py
scripts/transport_invariant.py
```

`transport_schema.py` rejects duplicate JSON keys, unknown schema fields,
unfrozen transform seeds, non-empty v1 map assumptions, malformed hashes, and
population reports whose decision, proof rows, counts, or self-hash disagree.
`transport_invariant.py` performs structural AST substitution, canonicalizes a
documented subset of Pono-returned SMT-LIB formulas, and checks C1, C2, and C3
for every BAD on the original source model. SMT UNKNOWN is never a certificate.

`build_transport_population.py` validates the Phase 1+2 and representation
artifact identities, reconstructs previously certified deterministic phase
candidates, freshly re-runs Houdini where needed, canonicalizes eligible Pono
invariants, independently re-certifies every selected source invariant, applies
exact-content and source-family deduplication, and computes T1/T2/T3 structural
applicability. It may invoke local Pono `interp --show-invar` only to recover a
machine-readable invariant from a previously frozen no-LLM UNSAT row. It does
not call OpenRouter or any other LLM/API.

The representation bundle's recursive manifest is itself schema-, status-,
summary-, file-, and self-hash checked. Pono invariant recovery has independent
20-second execution and 20-second normalization deadlines, a 5 MiB raw-output
cap, and a 50,000-node expanded-AST cap. Exceeding any bound is an explicit
exclusion, never a fallback.

For the third invariant-class condition, v1 counts only the stricter
`phase-guarded` disjunct. A merely multi-line candidate list is reported as
`conjunctive` but is not treated as evidence of a genuinely conjunctive proof.
This conservative implementation cannot make the frozen threshold easier to
pass.

The builder refuses to overwrite its output or sibling `source_certificates/`
and `source_invariants/` directories. A failed build removes only the fresh
partial directories created by that invocation and propagates the error. A
successful population file records zero LLM/API calls, the exact Pono hash,
input summary hashes, source-certificate timings, exclusions, and a canonical
self-hash. The official census must be produced from committed code before any
transformation module is implemented.

## Execution and Commit Boundaries

1. **`research: preregister known-map certified transport oracle`:** this
   document and active-doc alignment only; no transformation code.
2. **`feat: add certified transport population and map schema`:** source-
   certificate census, strict map schema, AST transport, and tests. Apply the
   Gate 5A0 population stop before writing transformation generators.
3. **`feat: add exact BTOR2 transport transformations`:** T0, T1, T2, then T3;
   independent exact map validation and negative tests. No official utility
   matrix before T3 is complete.
4. **`feat: add transport versus regeneration matrix`:** fixed B0--B3 runners
   and summary/integrity validator.
5. **`data: record known-map certified transport oracle`:** fresh canonical
   `certified_transport_v1` artifact and final H6 decisions.

No paid API call is permitted in these five commits.

### Planned implementation surface

The next commits may add only the following Gate 5 modules before a separately
reviewed scope change:

```text
scripts/build_transport_population.py
scripts/transport_schema.py
scripts/transport_invariant.py
scripts/generate_transport_variants.py
scripts/validate_transport_map.py
scripts/run_transport_baselines.py
scripts/run_transport_gate.py
scripts/summarize_transport_gate.py
scripts/tests/test_transport_schema.py
scripts/tests/test_transport_invariant.py
scripts/tests/test_transport_transforms.py
scripts/tests/test_transport_map_validation.py
```

The planned top-level command contract is:

```bash
python3 scripts/build_transport_population.py \
  --phase1-summary artifacts/phase1_2_summary_v1.json \
  --representation-summary artifacts/representation_phase_v1/summary.json \
  --out population.json

python3 scripts/generate_transport_variants.py \
  population.json \
  --families rename,affine-recode,split-merge,stutter \
  --seeds 11,23,47 \
  --out variants/

python3 scripts/validate_transport_map.py \
  variants/ \
  --timeout-ms 20000 \
  --out map_validation/

python3 scripts/run_transport_gate.py \
  population.json variants/ map_validation/ \
  --configs target-engine,regen-deterministic,known-map-transport \
  --trials 5 \
  --timeout 70 \
  --out matrix/

python3 scripts/summarize_transport_gate.py \
  artifacts/certified_transport_v1
```

These are future interfaces, not evidence that the files currently exist.

## Amendment Policy

This protocol is frozen before population or transformation implementation.
Pre-measurement implementation clarifications require a dedicated commit that
states the reason and leaves this version in history. Once the source census or
first official transformed variant is written, population thresholds,
transformation definitions, seeds, baselines, budgets, metrics, and H6 criteria
cannot be relaxed.

An implementation bug requires a versioned rerun that preserves the earlier
artifact. Failed variants cannot be removed, renamed, or replaced after
inspection. A wider transformation language, auxiliary map invariant, different
phase semantics, or LLM mapping experiment is a new gate, not a repair.

## External Rationale

The validator trust model is motivated by per-run translation validation based
on independently checkable forward-simulation evidence, rather than trusting a
front-end implementation: [Parthasarathy et al., 2024](https://arxiv.org/abs/2404.03614).

As an empirical warning rather than a formal result about BTOR2, a 2025 study
found that manual inspection rejected 23 of 39 reused transformations described
as semantics-preserving because they changed program semantics. This motivates
independent validation of every concrete transform run:
[Hort, Vidziunas, and Moonen, 2025](https://arxiv.org/abs/2503.23448).
