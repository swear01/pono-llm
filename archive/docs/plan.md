> Archived: 2026-07-11
> Reason: Superseded by the corrected Phase 1+2 hardening plan after the static-baseline audit.
> Replacement: docs/plan.md
> Status: historical only; do not use as active truth.

# Plan

**Current status (2026-07-11):** sound predicate injection is implemented and pushed on `soundness-audit` (`f87d12e`).  Phase 1 + 2 validation infrastructure is implemented and has been run once on the 21-circuit arithmetic/nla corpus: fail-fast IC3IA refinement cap, frozen candidate capture, fair replay matrix, deterministic affine/static predicate baseline, and direct candidate-conjunction C1/C2/C3 checker.  Reliability for the known linear-solvable set is fixed (`--two-tier --rounds=5` gives 15/15 stable UNSAT), but the project is still **not paper-ready as a coverage/improvement paper** until repeated frozen trials and a larger/stratified corpus are run.

## Current Research Decision

Do **not** switch to open-ended generic BVMul / nonlinear SMT research yet, and do **not** declare the work publication-ready yet.  The completed Phase 1 + Phase 2 validation infrastructure now gives the next decision point:

1. repeat the frozen-candidate replay to measure stochastic reliability;
2. scale the static baseline / replay matrix to a larger stratified corpus;
3. add subset/minimization if direct candidate certification becomes central;
4. only then decide whether nonlinear BVMul work is justified.

## Phase 1 — Fair Replay + Fail-Fast Infrastructure (implemented)

### P1.1 IC3IA fail-fast / refinement cap

**Status:** implemented and smoke-tested (2026-07-11).

**Goal:** make misses cheap without changing proof soundness.

Implemented option:

- `--ic3ia-max-refinements N`

Semantics:

- counts successful IC3IA abstraction-refinement rounds;
- default is unlimited;
- `N=0` disables abstraction refinement after the initial predicate set;
- when the cap is reached and another abstract/spurious counterexample needs refinement, IC3IA returns `unknown`, never `unsat`;
- a cap can hide a concrete SAT counterexample behind `unknown`, but cannot create a false UNSAT.

Likely follow-up option:

- `--ic3ia-max-predicates N` if refinement count alone is too coarse.

Touched files:

- `options/options.h`
- `options/options.cpp`
- `engines/ic3ia.h`
- `engines/ic3ia.cpp`

Experiment rule:

- use `0`, `1`, `2`, `4`, and unlimited in replay matrices;
- if known linear hits require many refinement rounds, do not use a hard zero-refinement mode as the default experiment mode; use a small cap or time budget instead.

### P1.2 Frozen LLM candidate capture

**Status:** implemented (2026-07-11): `scripts/capture_candidates.py`.

**Goal:** separate LLM stochasticity from proof replay.

Outputs:

- one predicate JSONL file per benchmark/config/trial;
- metadata containing model name, rounds, prompt hash or prompt text path, wall-clock LLM latency, candidate count, and any available token/cost fields;
- no proof claim made during capture.

### P1.3 Fair replay matrix

**Status:** implemented (2026-07-11): `scripts/run_matrix.py`.

**Goal:** compare baseline, static predicates, LLM predicates, and portfolio under the same manifest.

Report dimensions:

- offline proof time (candidate already generated);
- candidate-generation time and end-to-end time (LLM/static generation + proof);
- solved set, unique solved set, cactus data;
- per-trial stability via `--trials N`;
- clear separation of `unsat`, `sat`, `unknown`, `error`, and timeout.

Minimum configs:

- `baseline`: `try_fast_engines` + plain `ic3ia`, no LLM/predicates;
- `llm-linear`: frozen linear predicates only;
- `llm-two-tier`: frozen linear tier then full fallback;
- `portfolio`: baseline first, LLM fallback only on miss;
- `static-linear`: deterministic affine/template predicates.

Known timing issue to fix:

- `scripts/baseline_compare.py` currently records fast-engine wins as fixed `10.0s`;
- `scripts/predicate_workflow.py` currently times only `run_pono()`, not LLM generation.

## Phase 2 — Validate the LLM-Only Claim (implemented)

### P2.1 Deterministic affine/template predicate baseline

**Status:** implemented (2026-07-11): `scripts/static_predicate_baseline.py`.

**Goal:** check whether the current linear-tier LLM-only wins are actually LLM-specific or merely predicate-seeding wins.

Initial conservative template language:

- same-width small-coefficient affine equalities/inequalities over BAD-cone and transition-nearby scalar state vars;
- coefficients in `{-4,-3,-2,-1,0,1,2,3,4}`;
- examples: `x == y + c`, `x <= y + c`, `a*x + b*y + c*z == k`, `x' - x == c`;
- emit the same predicate-AST JSON format used by `--initial-predicates`.

Decision rule:

- if static-linear solves `93.c`, `fib_37`, and `fib_05`, stop calling them LLM-specific; reframe as semantic/predicate seeding value;
- if static-linear fails while frozen LLM predicates solve them reproducibly, the LLM-only claim becomes much stronger.

### P2.2 Candidate conjunction certificate checker

**Status:** implemented (2026-07-11): `scripts/candidate_cert_check.py`.

**Goal:** determine whether LLM already proposes a sufficient invariant conjunction, and whether IC3IA proof search is the bottleneck.

Checks on the **original unconstrained BTOR2**:

- `C1: Init ∧ ¬H` is UNSAT;
- `C2: H ∧ Trans ∧ ¬H'` is UNSAT;
- `C3: H ∧ BAD` is UNSAT;
- where `H = h1 ∧ h2 ∧ ... ∧ hn` from a predicate JSON list.

Soundness rule:

- only `C1/C2/C3 = UNSAT/UNSAT/UNSAT` is a certified invariant;
- BMC-k unknown or SMT unknown is not a proof;
- no candidate may be used as a final model constraint unless it has been certified this way, and final model-checking proofs should still target the original BTOR2.

Priority cases:

- `fib_23`, `fib_30` (triangular-sum / BVMul-heavy);
- the five stable linear-solvable cases as sanity checks.

Decision rule:

- if conjunction certification is fast for nonlinear fib cases, prioritize trusted candidate certificates over generic BVMul CEGAR work;
- if certification still times out on BVMul, only then run the existing `--ceg-bv-arith` matrix and consider a tightly bounded BVMul spike.


## Phase 1 + 2 Commands

Capture frozen candidates (LLM; use `--rounds 0` only for no-API smoke tests):

```bash
python3 scripts/capture_candidates.py --manifest artifacts/corpus.csv --out artifacts/candidates --rounds 5 --cap 20
```

Run fair replay matrix:

```bash
python3 scripts/run_matrix.py \
  --manifest artifacts/corpus.csv \
  --pred-dir artifacts/candidates \
  --configs baseline,llm-linear,llm-two-tier,static-linear,portfolio \
  --timeout 70 \
  --cap 20 \
  --trials 5 \
  --out artifacts/matrix.csv
```

Generate static affine/template predicates for one circuit:

```bash
python3 scripts/static_predicate_baseline.py circuit.btor2 --cap 200 --out static.jsonl
```

Directly certify a predicate conjunction on the original BTOR2:

```bash
python3 scripts/candidate_cert_check.py circuit.btor2 predicates.jsonl --timeout-ms 20000
```

Interpretation:

- replay `unsat` remains a Pono proof of the original model because predicates are abstraction predicates;
- candidate certification is stricter: only C1/C2/C3 all UNSAT certifies the candidate conjunction itself as an inductive safety invariant;
- `unknown`, timeout, and BMC-like absence of short counterexamples prove nothing.


## Phase 1 + 2 Smoke / Linear5 Replay Status

A small end-to-end smoke/replay run was completed on `paper_v3`, `93.c`, `fib_37`, `77.c`, `fib_05`:

- `scripts/capture_candidates.py --rounds 5 --cap 20` successfully froze LLM candidates for all 5.
- `scripts/run_matrix.py` produced `artifacts/phase1_2_full_matrix.csv` with baseline/static/LLM/portfolio configs.
- The matrix records `offline_time_sec`, `candidate_generation_sec`, `llm_generation_sec`, and `end_to_end_sec`; for frozen LLM rows, `end_to_end_sec` is replay proof time plus the captured LLM latency.
- `scripts/static_predicate_baseline.py` solved `77.c` but did not solve `93.c`, `fib_37`, or `fib_05` in this run.
- Frozen LLM-linear and LLM-two-tier solved all 5.
- `scripts/candidate_cert_check.py` certified the full frozen-candidate conjunction only for `fib_37`; other full conjunctions failed C1/C2, showing that candidate certification will need subset selection/minimization before it can replace predicate replay.

Next experiment step: rerun this matrix on the broader software-origin manifest and repeat trials before making any paper-level claim.

## Phase 1 + 2 Full21 Replay Status

A full `collect_circuits()` replay was also completed with frozen `--rounds 5 --cap 20` candidates and fail-fast predicate configs (`--ic3ia-max-refinements 0`):

- Manifest: `artifacts/phase1_2_full21_manifest.txt`.
- Frozen candidates: `artifacts/phase1_2_llm_candidates/` and merged metadata `full21_manifest.json`.
- Matrix: `artifacts/phase1_2_full21_cap0_matrix.csv`.
- Direct certificate results: `artifacts/phase1_2_full21_candidate_cert_results.json`.

Summary:

- baseline: 3 UNSAT, 1 SAT, 17 other;
- static-linear: 1 UNSAT (`77.c`);
- LLM two-tier: 7 UNSAT (`paper_v3`, `93.c`, `fib_30`, `fib_37`, `77.c`, `fib_05`, `fib_23`);
- portfolio: 8 UNSAT + 1 SAT.

This upgrades the single-run two-tier signal: `fib_23` and `fib_30` are now solved in tier 2 by nonlinear predicates, but they are not affine/linear wins and still take roughly a minute of proof time.  The original three linear-tier LLM-only cases (`93.c`, `fib_37`, `fib_05`) still survive the implemented static-linear baseline in this run.

## Deferred Until After Phase 1 + 2

### D1 Existing Pono BVMul abstraction matrix

Before implementing any new nonlinear algorithm, test existing Pono options:

- `--ceg-bv-arith`
- `--ceg-bv-arith-as-free-symbol`
- `--ceg-bv-arith-min-bw <N>`

Kill criterion:

- no new proof and no meaningful runtime improvement (roughly 2x) on the nonlinear set.

### D2 New predicate-aware staged BVMul abstraction

Only start this if Phase 2 shows:

- the candidate invariant is semantically right;
- direct certification or IC3IA is blocked specifically by multiplication;
- existing Pono BVMul abstraction exposes a concrete refinement bottleneck.

Otherwise this is likely an SMT-engineering sinkhole.

### D3 Paper/report

The project is **not yet ready** to be written as a strong improvement paper.  Paper framing should wait until repeated Phase 1 + 2 runs answer whether the current wins survive stochastic replay, deterministic baselines, and larger/stratified manifests.  A future paper may still be a methodology/negative-result paper, but the next work item is experiment validation, not manuscript writing.

## Current Ground Truth Results

- Final proof mechanism: IC3IA initial predicate injection (`--initial-predicates`) on the original BTOR2; no final constraint injection.
- Old boolean-pair constraint “proofs”: unsound acceleration map only; not proofs.
- Known reliable config: `scripts/predicate_workflow.py --two-tier --rounds=5`.
- Stable linear-solvable set: `paper_v3`, `93.c`, `fib_37`, `77.c`, `fib_05` (15/15 stable UNSAT in three trials).
- Current linear-tier LLM-only increment relative to tested engine/static portfolio: `93.c`, `fib_37`, `fib_05`.
- First full21 fail-fast two-tier replay also solved nonlinear tier-2 `fib_23` and `fib_30`; treat this as a single-run signal until repeated captures confirm reliability.
- Expanded sosylab/non-array corpus: 4 additional LLM solves, all also solved by baseline ind/interp; 0 new LLM-only.
- Main unsolved ceiling: genuine `var*var` / `bvmul`, input-driven loops, arrays, or representation loss.

## Do Not Do

- Do not restore final BTOR2 constraint/assume injection as a proof method.
- Do not use BMC-k unknown as proof or as “tentatively sound”.
- Do not claim signal-name mutex hints are BTOR2 invariants.
- Do not spend another cycle on prompt-only improvements unless Phase 2 identifies prompt failure as the bottleneck.
- Do not present the LLM-only cases as “LLM-necessary”; the current evidence is relative to the tested engine/static-predicate portfolio and one frozen LLM capture.
- Do not start open-ended BVMul solver work before repeated Phase 1 + 2 runs justify it.
