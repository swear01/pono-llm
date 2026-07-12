# Active Plan

**Updated:** 2026-07-12
**Branch:** `soundness-audit`
**Status:** Representation-Aware Phase/Grammar Gate v1 complete

## Current Research Position

The project has a sound trust boundary but still has no defensible
LLM-specific solve or search-efficiency claim.

Completed evidence now has three layers:

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

This is not a coverage-improvement paper result, and the project must not enter
paper mode by weakening the baseline or moving a failed threshold.

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

## Next Research Decision (Not Started)

Any next implementation must start with a new preregistered hypothesis that
does not depend on rescuing H1/H2/H3. The strongest remaining candidates are:

1. **Certified invariant transport and metamorphic robustness:** preserve the
   same target proof obligation under variable renaming, phase splitting, and
   invertible modular state transforms; compare regeneration with formally
   checked transport.
2. **Proof-carrying algebraic certificates:** require a small modular-arithmetic
   derivation checked by a tiny kernel, across multiple recurrence families.
3. **New natural corpus with a known local-certificate gap:** only if selected
   independently of current failures and matched against deterministic
   synthesis before LLM calls.

Generic BVMul CEGAR, prompt tuning, raw HWMCC mining, and source decompilation
remain stopped. The user should choose the next hypothesis before code work
continues.
