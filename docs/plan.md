# Closed Research Plan

**Updated:** 2026-07-14
**Branch:** `soundness-audit`
**Status:** research program closed at `soundness-audit-final-v1`; no Gate 6,
replacement population, new mechanism, transformed variant, or LLM call is
authorized on this branch

## Final Research Position

The project has a sound trust boundary but still has no defensible
LLM-specific solve or search-efficiency claim.

Completed evidence now has six layers:

1. **Soundness repair:** LLM/static formulas are untrusted IC3IA abstraction
   predicates, never BTOR2 assumptions. Direct C1/C2/C3 certificates and
   original-model Pono verdicts are the only accepted safe results.
2. **Matched formula baselines:** deterministic affine and quadratic portfolios
   cover every full21 LLM solve. Gate 2 also removes the apparent compactness
   advantage on `up.btor2`.
3. **Matched grammar/representation gate:** source, lifted, and raw grammar
   routes were frozen and replayed on an independently selected official
   SV-COMP 2025 paired pilot. Phase conditioning, source representation, and
   LLM routing all miss their preregistered utility thresholds.
4. **Proof-calculus feasibility gate:** a strict modular-polynomial certificate
   kernel is sound on development controls, but the frozen official corpus has
   zero task inside its preregistered v1 language. H5a is not run and no LLM
   certificate capture is authorized.
5. **Inductiveness-gap decomposition:** all six frozen Gate 4B0-v2 candidates
   are `FALSE_CANDIDATE` at depth 0 and exact Houdini removes each during C1;
   proof-graph and stronger-induction work therefore do not apply.
6. **Certified-transport census:** 11 certified bases and six T1-applicable
   bases miss the frozen 12/8 thresholds. Gate 5 stops before variants.

This is not a coverage-improvement paper result. A closure report, thesis
chapter, reproducibility artifact, or negative empirical study may report the
frozen evidence, but no write-up may weaken a baseline, move a failed
threshold, or relabel a not-run hypothesis as a negative utility result.

## Completed Representation/Phase Gate

### Corpus and provenance

- Translation commit: `d9838013ea48568a21a106a7fc94f11c13ac5ad6`
- Source commit: `1e5856db49f3a4766f416cc60382aa92012b2939`
- CPV commit: `2b20529bf4cd49922a14e0514631a148ce69236f`
- Official translated population: 267 tasks
- Eligible under the scalar/single-BAD/functional-`!pc`/source-map contract:
  164 (144 safe, 20 unsafe)
- Engine screen: 32 UNSAT, 10 SAT, 38 UNKNOWN, 84 timeout
- Frozen pilot: 12 safe baseline-hard, four safe controls, four unsafe controls;
  20 unique contents and 20 source families

Selection and hashes were frozen before any representation-routing API call.

### Implemented kernel

- strict `pono-llm-grammar-route-v1` parser;
- unary, pairwise-offset, affine, sum, and consecutive-counter quadratic
  grammar families;
- canonical route/candidate identities;
- conservative functional CPV `!pc` phase extraction;
- `phase => predicate` candidate construction;
- sound Houdini C1/C2/C3 checking on the original BTOR2;
- IC3IA replay only through `--initial-predicates` on the original model;
- source/lifted/raw renderers with a deterministic 6,000-lexical-token cap and
  untruncated prompt archive;
- fixed bounded exhaustive, candidate-budget-matched random, and deterministic
  transition-structure routers;
- independent certification of every routed UNSAT row.

### Executed results

Historical full21 formulas exactly matching the fixed bounded grammar:
158/353 (44.76%).

Paired LLM capture:

- 60 calls, one per benchmark/view;
- OpenRouter `deepseek/deepseek-v4-flash`;
- reasoning disabled, temperature 0;
- 142,814 total tokens;
- 229.16s total wall latency;
- 36 valid routes, 24 strict-schema/typing/budget failures.

Baseline-hard solved sets under all-phase routing:

| Configuration | Solved set |
|---|---|
| LLM source | `benchmark05_conjunctive` |
| LLM lifted | `count_up_down-1` |
| LLM raw | `gj2007b`, `benchmark05_conjunctive` |
| random source | `count_up_down-1` |
| random raw | `gj2007b`, `count_up_down-1` |
| deterministic structural | `gj2007b`, `benchmark05_conjunctive`, `count_up_down-1` |

The deterministic structural global route solves the first two; all-phase adds
only `count_up_down-1`.

### Gate decisions

| Hypothesis | Threshold | Result | Decision |
|---|---|---|---|
| H1 phase-local | at least 3 independent phase-only natural proofs | 1 | **fail** |
| H2 source representation | at least 3 source-unique families or robust matched-cost preservation | 0 source-unique | **fail** |
| H3 LLM routing | >=90% reference preservation, >=10x reduction, beat structural, net end-to-end gain | candidate reduction only; no solve over structural | **fail** |
| H4 soundness | zero false safe | 0; all 12 UNSAT independently certified | **pass** |

The fixed-budget exhaustive all-phase pool solves no baseline-hard task, so its
preservation rate is recorded as undefined, not 100%. The non-empty structural
reference solves three; source/lifted/raw preserve 1/3, 1/3, and 2/3.

## Canonical Artifact

Entry point:

```text
artifacts/representation_phase_v1/summary.json
```

The directory contains the complete paired population, baseline screen, pilot,
all prompts, route responses, validation errors, matrices, reports, Pono
invariants, independent certificates, and a recursive SHA-256 manifest.

Reproduction sequence:

```bash
python3 scripts/build_paired_corpus.py \
  <svcomp25-to-btor2-repo> <sv-benchmarks-repo> \
  --out population.json

ASAN_OPTIONS=detect_leaks=0 python3 scripts/screen_paired_baseline.py \
  population.json <svcomp25-to-btor2-repo> \
  --out baseline_screen.csv --ic3ia-timeout 10 --workers 8

python3 scripts/select_paired_pilot.py \
  population.json baseline_screen.csv --out pilot.json

python3 scripts/representation_views.py \
  pilot.json <svcomp25-to-btor2-repo> <sv-benchmarks-repo> \
  --out views --lexical-token-budget 6000

ASAN_OPTIONS=detect_leaks=0 python3 scripts/run_paired_phase_matrix.py \
  pilot.json <svcomp25-to-btor2-repo> --out-dir exhaustive_phase_matrix \
  --workers 2 --candidate-cap 50000 --cert-timeout-ms 20000 \
  --pono-timeout 10 --ic3ia-max-refinements 2

python3 scripts/capture_grammar_routes.py \
  views <svcomp25-to-btor2-repo> --out route_capture

ASAN_OPTIONS=detect_leaks=0 python3 scripts/run_routed_phase_matrix.py \
  pilot.json views route_capture exhaustive_phase_matrix/matrix.csv \
  <svcomp25-to-btor2-repo> --out-dir routed_phase_matrix \
  --workers 4 --cert-timeout-ms 20000 --pono-timeout 10 \
  --ic3ia-max-refinements 2

ASAN_OPTIONS=detect_leaks=0 python3 scripts/audit_routed_unsat.py \
  pilot.json routed_phase_matrix <svcomp25-to-btor2-repo> \
  --out-dir routed_unsat_audit --pono-timeout 70 --cert-timeout-ms 70000

python3 scripts/summarize_representation_phase.py \
  artifacts/representation_phase_v1
```

`ASAN_OPTIONS=detect_leaks=0` is required only for the current local ASan Pono
build because btor2 parser leak reports change process exit status. It does not
change solver/model semantics and is recorded in the matrix provenance.

## Current Stop/Go Decision

Close this gate. Do **not**:

- expand the paired capture to 100 tasks;
- add automatic CFG/phase reconstruction;
- repair the 24 invalid routes and call that a new positive result;
- tune prompts against the three solved tasks;
- claim source representation is superior (raw was stronger here);
- claim candidate reduction is LLM-specific (the structural router dominates
  solved-set coverage without API cost).

The one phase-only task and three structurally routed tasks are valid bounded
case studies, not enough to launch a general phase-local algorithm project.

## Completed Gate 4B0 — Modular Algebraic Certificates

The frozen protocol and full interpretation are in
[`docs/algebraic_certificate_gate.md`](algebraic_certificate_gate.md). The
canonical artifact is:

```text
artifacts/algebraic_certificate_v1/summary.json
```

Implementation commit:
`9e7e677507ad2baf9f357bc4ace52f80a457908d`. Preregistration commit:
`cc7df688b6eb13ef33bab0ff9cdc3badc6b39527`.

### Implemented trusted boundary

- strict `pono-modular-algebraic-certificate-v1` schema;
- sparse-polynomial normalization over exact `Z/(2^w)Z` semantics;
- complete checker-derived ITE branches, guards, and next-state substitutions;
- exact multiplier-identity C2 with no division, cancellation, or solver
  fallback;
- exact original-BTOR2 C1 and C3, including every BAD property;
- immutable query/certificate/model/tool hashes;
- six-arm exact Z3 reconnaissance with a pinned, independently activated
  PolySAT paper build;
- separate plain/seeded Pono-IC3IA original-model matrix;
- structural natural-population selector, expected-stage rejection suite, and
  recursive artifact validator.

### Official outcome

The population selector scanned all 267 frozen official translated tasks:

| Outcome | Count |
|---|---:|
| array-theory exclusion | 39 |
| no v1-supported nonlinear update SCC | 221 |
| nonlinear SCC over the frozen eight-branch cap | 7 |
| v1-eligible natural primary task | **0** |

The final seven tasks contain nine nonlinear SCCs and all nine exceed the cap.
The gate therefore does not have the 12--20 safe tasks, 4--6 unsafe controls,
or three natural recurrence families required to run H5a. The official
decision is:

| Hypothesis | Decision |
|---|---|
| H5a kernel value | **not run — no v1-eligible natural population** |
| H5b LLM value | **not authorized** |
| H5c development soundness | **pass** |
| H5c primary soundness | **not run — no primary population** |
| Gate 4B0 | **stop** |

No paid LLM call was made. The frozen branch cap and language were not changed
after observing the zero population.

### Development controls and solver reconnaissance

Five sequential trials each show that the kernel accepts `fib_23` and `fib_30`
and that complete C1+kernel-C2+C3 certificates take median 0.0116s and 0.0141s.
Pinned Z3 integer blasting proves the exact C2 obligations in median 0.0287s
and 0.0226s; local integer blasting takes 0.0638s and 0.0478s. Plain IC3IA is
UNKNOWN 5/5 on each control, while certified-basis IC3IA proves UNSAT 5/5 in
median 9.95s and 16.12s.

These are development diagnostics only. Kernel timing is in-process while Z3
timing includes process startup, and neither task counts toward H5a. Default
Python/local/pinned Z3 and the explicitly activated pinned PolySAT arm return
UNKNOWN in all ten 20-second control trials.

Both development certificates pass. The negative suite rejects all 20/20
malformed, provenance-tampered, unsupported, false-initial, and unsafe cases at
their preregistered expected stages, with zero accepted false safe.

### Reproduction and integrity

The exact sequential commands, environment, pinned revisions, executable
hashes, and one documented summary-stream assembly correction are recorded in
`artifacts/algebraic_certificate_v1/provenance.json`. The artifact's final
summary and recursive integrity hashes are:

```text
summary:   b0eb02c55af94cab2e232f920446edd4d98462368ee50be5183fcbeef8820ef5
integrity: b0099cf1ea68d2ab92820e914fedf8f97a0a3b01657ac74a5f0f825db7d38056
```

## Active Gate 5 — Known-Map Certified Transport Oracle

The complete frozen protocol is
[`docs/certified_transport_gate.md`](certified_transport_gate.md). Gate 5 is an
upper-bound proof-reuse experiment, not a mapping-inference or coverage gate.

### Gate 5A0 result — STOP

The strict census implementation is now present in
`scripts/build_transport_population.py`, `scripts/transport_schema.py`, and
`scripts/transport_invariant.py`. It revalidates upstream artifact hashes,
normalizes transportable ASTs, independently re-certifies every source
candidate against every BAD, applies exact-content/source-family deduplication,
and records structural T1/T2/T3 applicability. It never calls an LLM/API and
does not generate transformed models.

The canonical source-certificate census was run from the committed
implementation. Before any transformation implementation, it required:

- at least 12 source tasks with machine-readable invariants already certified
  by source-original C1/C2/C3;
- at least eight independent source families and three invariant classes;
- at least eight applicable bases for each primary family;
- T3 coverage of at least three input-driven families;
- four independently selected expected-unsafe controls;
- strict source/certificate/family hashes and no raw-string regex transport.

The result is `population-insufficient`: 11/12 safe bases and 6/8 T1-applicable
bases. Source families (11/8), invariant classes, T2 (11/8), T3 (11/8),
input-driven T3 families (10/3), and unsafe controls (4/4) passed. Eight
`interp --show-invar` recovery attempts were explicitly runtime-incompatible
with the installed ASan Pono and the inherited finite hard address-space limit;
no alternate build was used. Transport stops without synthetic padding or
transformed models.

The canonical command writes a self-hashed population plus source-certificate
evidence; successful `--show-invar` recovery would additionally retain raw
transcripts. It refuses overwrite, records local Pono recovery as no-LLM
provenance, and deletes fresh partial output on failure rather than emitting a
best-effort population. Syntactic multi-predicate sets are not counted as
genuinely conjunctive; v1 uses the stricter phase-guarded disjunct for that
class gate.

### Frozen transformation roles

- **T0 alpha-renaming/node-ID permutation:** mandatory 100% sanity control; it
  never counts toward a primary threshold.
- **T1 modular affine recoding:** non-diagonal invertible same-width state
  mixing with an explicit modular inverse.
- **T2 bit-vector split encoding:** changes state-vector structure through
  exact concat/extract projection.
- **T3 input-latched four-phase refinement:** changes transition granularity;
  every microstep must validate as projection stutter or source commit, every
  raw input is latched once, and BAD is visible only at the observation phase.

T3 is mandatory. T1/T2 success without T3 is infrastructure, not a reason to
continue transport research.

### Trust and comparison boundary

For each concrete variant, independently validate source/target hashes,
projection, inverse or stuttering simulation, constraints, all BAD properties,
and—on T3—bounded source-macro-step completeness. Then substitute the exact map
into the certified source AST and run target C1/C2/C3. Store target-certificate,
map-validation, and transformation-equivalence verdicts separately.

The known-map arm is compared against target engine-only and the strongest
current deterministic regeneration portfolio: engine baseline,
`static-ranked`, affine/static oracle, quadratic oracle, structural grammar,
Houdini, and sound IC3IA predicate replay. The primary 70-second cost includes
map validation, AST transport, and target certification. Five sequential trials
are run for seeds 11/23/47 only after Gate 5A0 passes.

Gate 5A requires >=90% acceptance separately for T1/T2/T3, >=5x overall
unamortized geometric-mean speedup, >=2x per primary family, and non-isomorphic
T3 utility on at least three independent source families. Only all frozen H6
criteria authorize deterministic hidden-map recovery. LLM map proposals remain
last, require a new preregistration, and are forbidden in Gate 5A0/5A.

Generic BVMul CEGAR, Gate 3 route repair, prompt tuning, broad HWMCC mining,
post-hoc Gate 4B0 language expansion, and coverage-paper framing remain
stopped.

## Closure record

No further proof mechanism is authorized. The final closure entry points are:

- [`final_claim_ledger.md`](final_claim_ledger.md), which separates supported,
  rejected, threshold-failed, not-run, and prohibited claims;
- [`final_research_narrative.md`](final_research_narrative.md), which records
  the complete causal research trajectory;
- [`../artifacts/final_research_summary_v1.json`](../artifacts/final_research_summary_v1.json),
  which hash-binds every canonical gate, commit, limitation, and stopping rule.

The frozen evidence boundary is tag `soundness-audit-final-v1` at
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`. The Oracle-First capability
ledger at commit `536a175` is a post-boundary methodology addendum, not an
active mechanism gate; it changes no final claim and authorizes no continuation.
Gate 4B0-v2, Gate 5A, proof graphs, stronger induction, transport mapping,
corpus replacement, and new LLM capture remain forbidden.
