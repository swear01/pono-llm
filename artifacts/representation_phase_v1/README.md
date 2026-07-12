# Representation-Aware Phase/Grammar Gate v1

This directory is the canonical 2026-07-12 artifact for the first paired
source/lifted/raw representation and phase-local grammar-routing gate.

## Frozen inputs

- SV-COMP 2025 BTOR2 translation commit:
  `d9838013ea48568a21a106a7fc94f11c13ac5ad6`
- SV-Benchmarks source commit:
  `1e5856db49f3a4766f416cc60382aa92012b2939`
- CPV translation commit:
  `2b20529bf4cd49922a14e0514631a148ce69236f`
- Population: all 267 translated `safety-func` tasks in the selected official
  categories; 164 pass the scalar, single-BAD, functional-PC, and two-source-
  mapped-state contract.
- Pilot: 20 content- and source-family-independent tasks selected before the
  routing capture (12 safe baseline-hard, four safe controls, four unsafe
  controls).

## Contents

- `population.json`: complete paired census, hashes, mappings, phases, and
  explicit exclusion reasons.
- `baseline_screen.csv`: engine-only screen for all 164 eligible tasks.
- `pilot.json`: frozen 20-task pilot and selection provenance.
- `views/`: exact 6,000-lexical-token-cap source, lifted, and raw prompts plus
  untruncated prompts.
- `frozen_route_audit.json`: exact semantic match of the historical full21 LLM
  formulas to the preregistered bounded grammar.
- `exhaustive_phase_matrix/`: matched global/all-phase bounded grammar runs.
- `route_capture/`: 60 immutable OpenRouter responses, strict route validation,
  token/latency metadata, prompt copies, provenance, and integrity sidecar.
- `routed_phase_matrix/`: LLM, deterministic structural, and budget-matched
  random all-phase replay; structural routes also have matched global replay.
- `routed_unsat_audit/`: independent C1/C2/C3 audit of every routed UNSAT row,
  including invariants returned by Pono when the candidate conjunction was not
  itself a direct certificate.
- `summary.json`: validated machine-readable result.
- `integrity.json`: SHA-256 for every artifact file except itself.

## Canonical result

- H1 phase-local threshold: **fail**. The deterministic structural route adds
  one baseline-hard all-phase proof (`loops/count_up_down-1`) over its matched
  global form, below the preregistered threshold of three independent families.
- H2 source representation threshold: **fail**. Source has zero unique solves;
  raw solves two baseline-hard tasks, lifted one, and source one.
- H3 LLM routing threshold: **fail**. LLM routes reduce formal candidate count,
  but no LLM arm beats the deterministic structural router. Structural-all
  solves the union of all three LLM-arm solved sets.
- H4 soundness: **pass**. No unsafe control becomes UNSAT. All 12 routed UNSAT
  rows pass an independent original-model certificate (four direct candidate
  certificates and eight independently checked Pono invariants).
- Strict route validity is itself a negative result: 36/60 captures are valid;
  24/60 violate width, arity, uniqueness, parameter, or candidate-cap rules.

The first exploratory deterministic matrix omitted signed comparison routes.
It is not included here. The canonical exhaustive and routed matrices include
both signed and unsigned bounded comparison routes; the structural router uses
signed C-like comparison templates. No result from the superseded exploratory
matrix is used in `summary.json`.
