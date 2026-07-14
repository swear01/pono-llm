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
| `scripts/` | Benchmark harnesses, gate tools, and strict closure-summary validation for the completed research program. |
| `benchmarks/` | Micro-benchmarks and BTOR2 test cases |
| `bench_results/` | Experiment output (not in git) |
| `artifacts/` | Frozen gate evidence plus `final_research_summary_v1.json`, the hash-bound machine-readable closure index. |
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
- **Phase-local grammar kernel:** `scripts/grammar_routes.py` validates
  `pono-llm-grammar-route-v1`, resolves unambiguous scalar state symbols,
  expands bounded signed/unsigned deterministic grammar families, implements a
  fixed transition-structure router, extracts strict functional CPV `!pc`
  phases, and wraps candidates as `phase => predicate`.
  `scripts/run_phase_grammar.py` sends the guarded conjunction to the existing
  Houdini/C1-C2-C3 checker and, if it is not a direct certificate, supplies the
  same untrusted candidates to IC3IA on the original model.
- **Paired population and views:** `scripts/build_paired_corpus.py` binds the
  official translation/source/CPV revisions, source/BTOR hashes, source-family
  identity, unique source-state mapping, and explicit exclusions.
  `scripts/screen_paired_baseline.py` runs the full eligible engine screen and
  `scripts/select_paired_pilot.py` freezes the family/content-independent pilot
  before LLM results. `scripts/representation_views.py` emits matched source,
  target-derived lifted, and raw-property-cone prompts under a documented
  lexical cap plus full prompts.
- **Grammar route capture/replay:** `scripts/capture_grammar_routes.py` freezes
  one strict JSON route per paired view with prompt/response/model/token/latency
  hashes; invalid routes remain explicit data. `scripts/run_paired_phase_matrix.py`
  executes global/all-phase bounded grammar controls.
  `scripts/run_routed_phase_matrix.py` compares frozen LLM, candidate-budget-
  matched random, and deterministic structural routes without API calls.
- **Representation-gate audits:** `scripts/audit_frozen_routes.py` classifies
  historical full21 formulas against the bounded grammar.
  `scripts/audit_routed_unsat.py` regenerates every non-direct routed UNSAT,
  requests Pono's invariant, and independently checks C1/C2/C3.
  `scripts/summarize_representation_phase.py` validates the complete recursive
  artifact and derives the H1--H4 decision.
- **Modular algebraic certificate kernel:** `scripts/bv_poly_kernel.py`
  canonicalizes sparse polynomials over `Z/(2^w)Z`, expands every syntactic
  `ite` branch, and checks supplied multiplier identities without division or
  cancellation. `scripts/check_algebraic_certificate.py` combines this strict
  C2 kernel with exact original-BTOR2 C1/C3. Candidate, branch, guard, and
  substitution provenance is hash-bound and independently reconstructed.
- **Completed Gate 4B0 experiment boundary:** `scripts/build_algebraic_controls.py` and
  `scripts/build_algebraic_query_corpus.py` freeze the non-primary controls and
  exact C2 queries. `scripts/run_algebraic_baselines.py` compares current Z3,
  explicit integer blasting, and the pinned PolySAT paper commit; PolySAT must
  come from a clean exact-revision checkout and pass a statistics-bearing
  activation probe. `scripts/run_algebraic_pono_baseline.py`
  separately measures plain and certified-basis IC3IA with explicit Bitwuzla.
  `scripts/build_algebraic_population.py`, `scripts/run_algebraic_gate.py`,
  `scripts/run_algebraic_negative_suite.py`, and
  `scripts/summarize_algebraic_gate.py` enforce selection, soundness, decision,
  and recursive-integrity contracts. No component repairs a certificate or
  silently falls back to generic C2 solving. The canonical result is
  `artifacts/algebraic_certificate_v1/`: the frozen official population contains
  zero v1-eligible natural task, so H5a was not run and no LLM capture occurred.
- **Gate 5 certified-transport boundary:**
  `docs/certified_transport_gate.md` is the frozen preregistration for a known-
  map upper-bound oracle. `scripts/transport_schema.py` implements strict map,
  invariant, and population identities; `scripts/transport_invariant.py`
  implements canonical Pono-invariant conversion, structural substitution, and
  exact every-BAD source certification; and
  `scripts/build_transport_population.py` implements the no-LLM Gate 5A0 census
  with artifact validation, deterministic source-invariant recovery,
  source-family deduplication, and transform applicability. The canonical
  `artifacts/certified_transport_v1/` census is `population-insufficient`, so
  no transformed variant exists. T0 renaming is only a sanity control, while
  T1 affine recoding, T2 split encoding, and input-latched T3 stuttering are the
  three primary families. Map validation, target C1/C2/C3, and transformation-
  equivalence verdicts remain separate, and no LLM is authorized in 5A0/5A.
- **Gate 5A inductiveness-gap diagnostics:**
  `scripts/diagnose_inductiveness_gap.py` implements bounded correctness,
  individual/conjunction C2, exact Houdini, k-induction, CTI reachability, and
  the fixed at-most-two-helper/one-guard repair oracle.
  `scripts/run_inductiveness_gap_gate.py` binds those checks to the six frozen
  Gate 4B0-v2 hashes and writes `artifacts/inductiveness_gap_v1/`.
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
- **Final closure index:** `artifacts/final_research_summary_v1.json` binds the
  frozen boundary, gate decisions, canonical evidence hashes, environment
  limitations, and no-follow-on rules. `scripts/validate_final_research_summary.py`
  strictly validates fields, commits, file hashes, decisive source-artifact
  semantics, self-hash, zero closure API calls, and the closed Gate-6 boundary.
- **Oracle-First capability ledger (post-boundary addendum):**
  `scripts/capability_gate_catalog_v1.json` freezes the cross-system studies;
  `scripts/build_capability_gate_ledger.py` verifies referenced bytes and
  builds the ledger; `scripts/validate_capability_gate_ledger.py` checks its
  schema, provenance classes, decisions, and self-hash. Canonical output and
  the external replication census live in
  `artifacts/capability_gate_ledger_v1/`. It changes no final claim and is not
  an active next project.
- **External Oracle Replication R1:**
  `scripts/build_quokka_oracle_r1.py` freezes upstream bytes and the smoke set;
  `scripts/run_quokka_oracle_replication.py` runs raw Q0/Q1/Q2 UAutomizer arms;
  `scripts/summarize_quokka_oracle_r1.py` applies fail-closed stage classes;
  `scripts/validate_quokka_oracle_r1.py` checks the recursive artifact. The
  transition, preregistration, raw logs, and STOP decision live in
  `artifacts/external_quokka_oracle_r1/`.
