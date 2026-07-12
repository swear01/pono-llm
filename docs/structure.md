# Structure

| Path | Purpose |
|------|---------|
| `engines/` | IC3/IC3IA engine (C++). Current sound injection point: `ic3ia.cpp` `--initial-predicates`; fail-fast knob: `--ic3ia-max-refinements`. |
| `core/` | Transition system types (FTS, RTS), term/sort abstractions |
| `frontends/` | BTOR2 parser, Verilog frontend hooks |
| `llm_worker/` | Python LLM and BTOR2 semantic utilities: `invariant_arith.py`, `invariant_prompt.py`, `btor2_reader.py`, `llm_client.py`, `env_config.py` |
| `options/` | CLI option definitions |
| `modifiers/` | Transition system modifiers (cone of influence, operator abstraction, etc.) |
| `refiners/` | CEGAR refinement components |
| `printers/` | Witness/proof printers |
| `smt/` | SMT utility wrappers |
| `utils/` | Logging, timing, misc utilities |
| `tests/` | C++ tests (googletest) + Python tests (`tests/python/`) |
| `scripts/` | Benchmark harnesses and Phase 1+2/Gate 2 scripts: `preprocess_sw.py`, `predicate_workflow.py`, `experiment_manifest.py`, `capture_candidates.py`, `run_matrix.py`, `summarize_reliability.py`, `summarize_phase1_2.py`, `static_predicate_baseline.py`, `candidate_cert_check.py`, `extract_btor_features.py`, `select_gate2_corpus.py`, `select_gate2_survivors.py`, `select_gate2_llm_targets.py`, `summarize_gate2.py`, `hash_research_artifacts.py` |
| `benchmarks/` | Micro-benchmarks and BTOR2 test cases |
| `bench_results/` | Experiment output (not in git) |
| `artifacts/` | Frozen Phase 1+2 captures and canonical matrices; see `artifacts/README.md` and its SHA-256 manifest. |
| `docs/` | Active docs; historical docs live under `archive/docs/` |
| `diagnosis/` | Per-phase diagnosis notes |
| `prompts/` | LLM prompt templates |
| `samples/` | Example BTOR2 designs |
| `deps/` | Vendored deps: `smt-switch/`, `btor2tools/` |
| `build/` | CMake output (not in git) |
| `contrib/` | Dependency setup scripts |

## Current Module Boundaries

- **Final proof path:** original BTOR2 + predicate JSON → `pono -e ic3ia --initial-predicates <json> <btor2>`. Predicate JSON is untrusted abstraction vocabulary, not a model assumption.
- **Stable experiment identity:** `scripts/experiment_manifest.py` maps
  dataset-relative benchmark IDs to local paths, preserves/validates benchmark
  content SHA-256, derives path-independent candidate slugs, and validates
  frozen capture integrity sidecars.
- **LLM generation:** `llm_worker/` owns API calls and prompt construction.
  `scripts/capture_candidates.py` creates immutable frozen runs with user/system
  prompts, normalized model JSON responses, source/candidate/model hashes, Git
  provenance, tokens, latency metadata, and a completed `integrity.json`; replay
  scripts do not call the LLM.
- **BTOR2 semantic extraction:** `llm_worker/btor2_reader.py` normalizes scalar
  initialization constants to unsigned decimal before prompts/templates consume
  them; array metadata is diagnostic only and array predicates remain unsupported.
- **Experiment replay:** `scripts/run_matrix.py` verifies model and capture bytes
  before execution, then compares baseline, LLM predicate replay, LLM Houdini
  certificates, balanced-static, post-hoc `static-ranked`, static-oracle, and
  portfolio configs. It reports certificate/model-checker time separately, plus
  generation/processing/offline/end-to-end timing, token totals, capture hashes,
  exact error categories, and a benchmark/config/trial coverage contract that
  downstream selectors verify before accepting a matrix.
- **Deterministic baseline:** `scripts/static_predicate_baseline.py` round-robins unary, pairwise, affine-2, and affine-3 templates, derives affine projections, provides a separate generic consecutive-counter quadratic family for `static-quadratic-oracle`, and exposes a post-hoc low-complexity named-variable order/sum ranking baseline.
- **Direct candidate certification:** `scripts/candidate_cert_check.py` checks every BAD property, uses exact C++ AST semantics, and supports sound Houdini subset extraction; only all-UNSAT C1/C2/C3 is a certificate.
- **Gate 2 corpus control:** `scripts/extract_btor_features.py` performs a
  durable full-tree feature scan; `scripts/select_gate2_corpus.py` produces a
  portable, content-deduplicated, fixed-seed stratified manifest; and
  `scripts/select_gate2_survivors.py` freezes the non-decisive baseline subset
  without treating timeout/unknown as evidence;
  `scripts/select_gate2_llm_targets.py` then removes both the prior corpus and
  deterministic decisive results before any paid LLM call.
- **Canonical summaries:** `scripts/summarize_phase1_2.py` and
  `scripts/summarize_gate2.py` validate full capture archives plus exact
  corpus/config/trial/model/source-manifest contracts before deriving
  machine-readable results; `scripts/hash_research_artifacts.py` regenerates
  the separate Phase 1+2 and Gate 2 SHA-256 manifests.
- **Legacy reactive sidecar:** `llm_generalizer.cpp` / JSONL sidecar code still exists, but it is not the active arithmetic-invariant path and should not be restored as the primary workflow.
