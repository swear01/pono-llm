# Handoff: Current State

## Repository

`pono-llm` — research prototype for LLM-assisted semantic lemma generalization in hardware model checking. Branch: `feature/llm-ic3ia-generalization`.

## Core Research Direction

**Proof-Artifact-Guided Semantic Lemma Generalization.**

We use model-checker proof artifacts (frame clauses, CTIs, predicates) as seeds. Mechanical or LLM-guided generalization transforms these into candidate lemmas. Formal solvers validate soundness. Impact analysis evaluates proof usefulness.

## Quick Reference: Key Files

### Pono C++ modifications

- `engines/ic3ia.cpp` — predicate dump, reset-solver injection, dynamic lemma loader
- `engines/ic3base.cpp` — CTI dump, frame clause dump
- `engines/ic3ia.h` — `lbl2pred_`, `conc_ts_` declarations
- `engines/ic3base.h` — `resolve_frame_literal_for_dump()` virtual method

### Python infrastructure (`llm_worker/`)

- `smt_checker.py` — BTOR2-to-SMT translator, lemma parser
- `lemma_nontriviality.py` — 5 nontriviality checks
- `reachable_filter.py` — solver-free reachable-sample filter
- `generalization_dsl.py` — DSL schema validator + SMT lowerer (v2)
- `run_closed_loop_synthesis.py` — closed-loop propose→validate→feedback→refine
- `lift_clause_families.py` — mechanical OR→implication clause lifting
- `analyze_lemma_impact.py` — impact analyzer (CTI violation, clause coverage)
- `run_injection_experiment.py` — repeated experiment harness with seed control
- `build_sampling_payloads.py` / `build_generalization_payloads.py` — payload builders
- `run_parallel_sampling.py` / `parse_parallel_sampling.py` — QUOKKA-style pipeline

### Prompts (`prompts/`)

- `pono_sampler_primer_v1.md` — free-form sampling primer
- `pono_generalization_primer_v1.md` — generalization harness v1
- `pono_generalization_primer_v2_dsl.md` — DSL-constrained v2
- `pono_generalization_modes.json` — 6 sampling modes
- `pono_sampler_modes.json` — 8 exploration modes

### Key logs (`logs/`)

- `pono_frame_dump/` — IC3IA dumps (predicates, CTIs, frames)
- `formal_yield/state15_*.json` — state15 analysis results
- `formal_yield/closed_loop_synthesis/` — closed-loop experiment results
- `formal_yield/injection_experiments/` — repeated injection experiments
- `formal_yield/parallel_sampling/` — free-form think-none pilot
- `formal_yield/generalization_sampling/` — generalization harness v1
- `formal_yield/generalization_sampling_v2/` — DSL-constrained v2

### Key docs

- `docs/research_overview.md` — canonical research description
- `docs/research_scope.md` — scope and non-claims
- `docs/method_evolution.md` — chronological method history
- `docs/lemma_mining_method_comparison_final.md` — 8-method comparison
- `docs/reset_solver_injection_claim_boundary.md` — injection claim limits
- `docs/baseline_reproducibility.md` — IC3IA nondeterminism evidence

## Current Allowed Claims

1. Formal-gated candidate mining infrastructure works
2. Clause-family lifting: 26/30 verified, 87% pass, mechanical
3. Closed-loop solver feedback found r_pipe_req ⇒ o_wb_stall
4. Reset-solver injection mechanically works (opt-in)
5. IC3IA artifact counts are nondeterministic (single-run comparisons unreliable)
6. Generalization harness v1: 100% metadata compliance achieved
7. DSL-constrained v2: parse rate improved, yield pending high-thinking baseline

## Current Non-Claims

- No runtime speedup, no benchmark unlock, no full Pono integration
- No stable artifact reduction from injection
- No claim that think-none works (yield currently zero)
- No claim that solver-verified lemmas are proof-useful without impact ranking
- No CPAchecker benchmark solved (context-unlocked only)

## Immediate Next Task

**DSL-constrained generalization harness v2 with high-thinking baseline.**
Build prompts, run one high-thinking call with same DSL primer, compare against think-none v2. Determine whether thinking level is the bottleneck for both DSL compliance (17% rate) and formal-gate yield (currently zero).

## Do Not Do

- Do not start new LLM experiments without formal-gate pipeline attached
- Do not modify C++ unless needed for dump correctness
- Do not run uncontrolled benchmark sweeps
- Do not claim think-none works unless formal-gate yield becomes nonzero
- Do not claim injection helps unless controlled repeated experiments support it
