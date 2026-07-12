# Phase 1+2, Gate 2, and Representation/Phase Research Artifacts

**Canonical bundle finalized:** 2026-07-12

**Phase 1+2 experiment date:** 2026-07-11
**Benchmark root:** HWMCC (paths are stored as dataset-relative benchmark IDs)

## Canonical result

[`phase1_2_summary_v1.json`](phase1_2_summary_v1.json) is the machine-readable
entry point. Its source tables are:

- [`phase1_2_corrected_full21_matrix_final.csv`](phase1_2_corrected_full21_matrix_final.csv) — engine and frozen LLM predicate replay before the matched quadratic baseline;
- [`phase1_2_corrected_static_full21_v3.csv`](phase1_2_corrected_static_full21_v3.csv) — clean-software-first balanced affine and quadratic static baselines;
- [`phase1_2_llm_houdini_full21.csv`](phase1_2_llm_houdini_full21.csv) — direct trusted LLM-candidate certification on all 21 models;
- [`phase1_2_nonlinear_reliability.json`](phase1_2_nonlinear_reliability.json) and [`phase1_2_nonlinear_reliability.csv`](phase1_2_nonlinear_reliability.csv) — five independent captures each for `fib_30` and `fib_23`.

The corrected result is:

- LLM Houdini and deterministic quadratic Houdini solve the same seven
  circuits;
- engine + deterministic and engine + LLM portfolios each cover eight UNSAT
  and two SAT circuits;
- current LLM-specific UNSAT count is zero;
- direct LLM certification has low proof-only cost, but generation dominates
  end-to-end time and token use.

## Candidate captures

- [`phase1_2_frozen_v2/`](phase1_2_frozen_v2/) is the portable migrated full21
  capture used for the full-corpus replay. It is legacy schema v2; some original
  raw-response/provider metadata is incomplete and is marked in its metadata.
- `phase1_2_nonlinear_capture_01/` through `_05/` are complete independent v2
  captures with raw normalized round responses. `system_prompt.txt` and source
  hashes were recorded immediately after capture in `provenance.json`, which
  explicitly sets `recorded_after_capture=true`.
- The Gate 2 capture uses schema v3, which writes provenance and partial round
  state natively. New captures use schema v4 and additionally bind benchmark
  bytes through `integrity.json`.

Every canonical capture directory now contains `integrity.json`. The v2/v3
sidecars are explicitly marked `recorded_after_capture=true`: they verify the
current frozen manifest/model/prompt/predicate/metadata/response bytes and bind
the archived system-prompt/provenance files when those files exist, but do not
retroactively recover provider data that was never captured. Schema v4 writes
the same contract natively and replay refuses an absent, incomplete, or
mismatched sidecar.

Canonical replay CSVs were metadata-enriched on 2026-07-12 with the verified
benchmark SHA-256, source-manifest SHA-256, and (where applicable) capture
integrity SHA-256. They were subsequently enriched with a deterministic
benchmark-set/config/trial contract and expected row count; the contract was
recomputed from the frozen rows and referenced manifests, without changing any
verdict, candidate, or timing field. Those rows use
`benchmark_hash_status=posthoc-verified-2026-07-12`; verdicts, candidates, and
timings were not changed. New `run_matrix.py` output records the same provenance
natively with `benchmark_hash_status=verified`.

Replay never calls the LLM. Unsupported or ill-typed legacy candidates are
reported by line/index and removed before Pono; direct certificates require
C1/C2/C3 all UNSAT on the original BTOR2.

## Reproduction

Commands and timing definitions are maintained in
[`../docs/plan.md`](../docs/plan.md). Set `HWMCC_ROOT` or pass
`--benchmark-root` to map the stable benchmark IDs onto a local dataset copy.

[`phase1_2_artifact_hashes.json`](phase1_2_artifact_hashes.json) records SHA-256
hashes for the canonical tables, capture manifests, candidate JSONL files,
responses, prompts, and provenance files.

Canonical manifests, matrices, and candidate captures use dataset-relative
benchmark identities. The three hashed human-readable `gate2_up_*cert_check.txt`
transcripts retain the original local path in their display header; they are
evidence logs, not replay inputs. Some additional unhashed smoke diagnostics
also retain local absolute paths and are excluded from the canonical result.

Other `phase1_2_*` files in this directory are earlier smoke runs or
pre-quadratic diagnostics. They are historical inputs, not the canonical final
comparison.

## Gate 2 (complete)

[`gate2_summary_v1.json`](gate2_summary_v1.json) is the machine-readable entry
point. The complete Gate 2 result is zero LLM-specific coverage on the 11 new
deterministic-hard targets. A post-hoc fixed low-complexity ranked baseline also
removes the apparent `up.btor2` compactness advantage: 15 LLM predicates and 20
ranked predicates both solve 5/5 replays, with median proof times 8.115s and
2.134s respectively. A ranked prefix of 15 fails while 16 succeeds; the
cap-16 returned invariant independently passes C1/C2/C3.

- `gate2_features.csv` is the complete 1,919-file structural census;
- `gate2_manifest.json` is the portable content-deduplicated manifest of all 86
  currently eligible non-array, preserved-software-name models;
- Gate 2 baseline/static matrices use atomic `*.partial` output while running.
- `gate2_baseline_screen_10s.csv` records the full 86-model engine screen;
- `gate2_static_quadratic_le10k_70s.csv` records the matched deterministic
  oracle on the 27 small survivors;
- `gate2_llm_targets.json` freezes the 11 new deterministic-hard targets.
- `gate2_llm_capture_v3/`, `gate2_llm_houdini_70s.csv`, and
  `gate2_llm_linear_refine_70s.csv` contain the frozen LLM experiment;
- `gate2_static_linear_cap200_refine_70s.csv` is the corrected raw deterministic
  predicate comparison;
- `gate2_static_ranked_cap20_refine_70s.csv` is the post-hoc low-complexity
  named-variable order/sum baseline over all 11 targets;
- `gate2_up_llm_vs_ranked_5trials.csv` and
  `gate2_up_static_ranked_cap{15,16}.csv` record the reliability and prefix
  boundary checks;
- `gate2_up_static_linear_cap192_v2.csv` is the canonical evidence for the
  largest recorded failing broad-static prefix; cap 200 is the recorded success;
- `gate2_up_*cert_check.txt` records independent certificates for the apparent
  LLM win and both corrected static counterparts.

Gate 2 has a separate immutable hash manifest,
[`gate2_artifact_hashes.json`](gate2_artifact_hashes.json). Regenerate both
canonical summaries and both hash manifests with:

```bash
python3 scripts/summarize_phase1_2.py > artifacts/phase1_2_summary_v1.json
python3 scripts/summarize_gate2.py > artifacts/gate2_summary_v1.json
python3 scripts/hash_research_artifacts.py
```

## Representation/phase/grammar Gate v1 (complete)

[`representation_phase_v1/summary.json`](representation_phase_v1/summary.json)
is the machine-readable entry point. The canonical bundle contains:

- all 267 official paired census rows and 164-task eligible engine screen;
- the pre-LLM 20-family pilot;
- source/lifted/raw capped and full prompts;
- 60 frozen OpenRouter route responses with strict validation and provider
  token/latency data;
- global/all-phase exhaustive controls plus structural, random, and LLM routed
  matrices;
- an independent certificate for all 12 routed UNSAT rows;
- a recursive artifact integrity manifest.

Decisions: H1 phase-local **fail (1/3)**, H2 source representation **fail**,
H3 LLM routing **fail**, H4 soundness **pass**. Deterministic structural routing
solves the three-task union reached across all LLM representation arms. See
[`representation_phase_v1/README.md`](representation_phase_v1/README.md) and
[`../docs/representation_phase_gate.md`](../docs/representation_phase_gate.md).

Regenerate the validated summary and recursive integrity file only in a fresh
artifact directory:

```bash
python3 scripts/summarize_representation_phase.py \
  artifacts/representation_phase_v1
```
