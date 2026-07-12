# Active Plan

**Updated:** 2026-07-12
**Scope:** corrected Phase 1+2 and Gate 2 falsification; no new BVMul algorithm

## Research Status

Soundness is solved by using LLM/static formulas only as IC3IA abstraction
predicates. The current task is to determine whether any measured benefit is
specific to the LLM rather than to semantic predicate seeding in general.

The first deterministic baseline was not a valid affine comparison: `--cap 20`
was exhausted by unary constant predicates before pairwise or affine templates
were emitted. The corrected balanced/static-oracle experiments already solve
the three former linear-tier LLM-only cases (`93.c`, `fib_37`, `fib_05`). Those
three cases must no longer be described as LLM-specific.

The remaining nonlinear cases also fail the uniqueness test. Five independent
captures certify `fib_23`/`fib_30` 10/10 with LLM candidates, but the matched
deterministic quadratic oracle certifies the same circuits in 4.21s and 2.50s
end-to-end. No current solved case is LLM-specific after the deterministic
affine/quadratic portfolio.

Gate 2 also removes the last apparent ranking/compactness signal. LLM-15 proves
`loop-invgen/up.btor2`, but a post-hoc fixed deterministic order/sum ranker
proves it with prefix 16 and is 5/5 at cap 20. Across all 11 new targets, LLM,
cap-200 static seeding, and cap-20 ranked seeding solve the same single circuit.
The ranker is explicitly post-hoc and is used to falsify the current positive
claim, not presented as a pre-registered general method.

## Implemented Phase 1 Infrastructure

### IC3IA fail-fast

```text
--ic3ia-max-refinements N
```

- counts successful abstraction-refinement rounds;
- default is unlimited;
- `0` uses initial predicates only;
- reaching the cap returns `unknown`, never a fabricated `unsat`;
- capped runs may hide SAT and therefore are not final unsafe-result runs.

### Stable immutable candidate capture

`scripts/capture_candidates.py` now:

- uses dataset-relative `benchmark_id` values and stable SHA-256-based slugs;
- accepts `--benchmark-root` (default `$HWMCC_ROOT` or the project HWMCC path);
- refuses a non-empty output directory so a capture cannot be silently mixed or
  overwritten;
- stores exact prompts, normalized per-round model JSON responses, predicate JSONL, hashes,
  provider/model, tokens, API latency, and wall latency;
- stores the exact system prompt, Git HEAD/dirty marker, and SHA-256 hashes of
  every prompt/capture source file in `provenance.json` (capture schema v4);
- writes response, candidate, and `status=in_progress` metadata after every
  completed API round, so an API failure leaves an explicit auditable partial
  capture rather than losing prior rounds;
- recursively validates the exact supported predicate-AST vocabulary/arity;
  invalid model output remains in the frozen response and is counted with
  round/index/error diagnostics, but is not passed to Pono as a candidate;
- performs no proof and makes no correctness claim;
- finalizes `integrity.json` only after the capture manifest is complete. The
  sidecar binds benchmark content, manifest, system prompt, provenance, prompt,
  predicate, metadata, and response bytes by SHA-256. Replay rejects missing,
  incomplete, mismatched, or tampered captures instead of treating them as
  empty candidate bags.

The canonical v2/v3 captures predate native benchmark hashing. Their
`integrity.json` sidecars were recorded after capture and are explicitly marked
as such: they verify the frozen bytes and current benchmark identities, but do
not reconstruct missing historical provider metadata.

### Fair replay

`scripts/run_matrix.py`:

- never calls the LLM;
- terminates the losing fast engine when `ind` or `interp` returns a decisive
  result;
- distinguishes `unsat`, `sat`, `unknown`, timeout, process error, and cancelled
  portfolio workers;
- stops a two-tier replay on either decisive `sat` or `unsat`, and attaches
  capture provenance to a portfolio row only when that row actually invokes
  the LLM tier;
- rejects unsupported or ill-typed frozen ASTs (unknown refs, non-Boolean roots,
  width mismatches) before Pono replay and records exact line indices/errors,
  rather than relying on the C++ skip path;
- reports proof, generation, processing, offline, and end-to-end times;
- separates direct certificate time from Pono model-checker time;
- records stable benchmark/capture IDs, manifest and candidate hashes, requested
  provider/model, LLM call count, and token totals;
- verifies a declared benchmark content hash before proof and records the actual
  model SHA-256 in every new replay row. LLM configurations additionally require
  capture-manifest membership, completed metadata, and a valid integrity
  sidecar before the first benchmark runs;
- records a canonical contract for the actual selected benchmark set, config
  set, trial count, expected row count, and source manifest. Downstream Gate
  selectors/summaries require exact Cartesian coverage, so a partial or
  `--max-benchmarks` smoke matrix is rejected as a complete experiment;
- streams each completed replay row to `*.partial` and atomically promotes the
  matrix only after the full run, so interruption cannot masquerade as a
  complete CSV or erase already completed rows;
- supports baseline, LLM predicate replay, LLM Houdini certification, static,
  and portfolio configurations.

## Implemented Corrected Phase 2 Baselines

### Balanced static templates

`scripts/static_predicate_baseline.py` round-robins across:

1. unary constants/bounds;
2. pairwise equalities/bounds;
3. two-variable small-coefficient affine relations;
4. three-variable small-coefficient affine relations.

Variable selection first keeps clean software variables, then BAD-cone control
state, then remaining scalar state. This ordering is required: the earlier
hot-first cap could spend five slots on unnamed 1-bit control flags and omit a
named loop counter that the LLM prompt was allowed to use.

Thus a small cap cannot be consumed by the first variable. Coefficients are in
`[-4,4]`; operands must have equal bit widths. Unary templates include each
state's exact BTOR2 initialization constant (not only the small constants
0--8), because held parameters such as `n == 150` are necessary for a fair
deterministic comparison.

### Post-hoc ranked relational baseline

The explicit replay config `static-ranked` is a bounded falsification baseline,
not part of the original pre-Gate-2 design. It considers at most the first eight
clean named software variables, groups only equal-width terms, and emits:

1. every directed unsigned order `x <= y`;
2. then every three-variable sum equality `x + y == z`.

Candidates are still untrusted abstraction predicates. The ranker never asserts
them as invariants, and its result is sound for the original model. Because this
family was added after inspecting the apparent `up.btor2` signal, its result can
invalidate an LLM-compactness claim but must not be described as an unbiased
prospective evaluation.

### Static oracle

The `static-oracle` replay configuration:

1. generates a larger balanced deterministic template pool;
2. applies sound Houdini elimination;
3. if C1/C2/C3 certify the surviving conjunction, reports a direct certificate;
4. otherwise adds deterministic affine projection predicates and injects them
   into IC3IA as untrusted abstraction predicates.

Houdini candidates are removed only after a concrete C1 or C2 counterexample.
Any affine projections need not be invariants because they are never asserted;
they remain sound predicate-abstraction vocabulary.

### Quadratic falsification baseline

`static-quadratic-oracle` extends the same trusted oracle with the generic,
deterministic same-width family
`k*accumulator {==,<=,>=} counter*(counter+delta)`, where `k` is 1--4 and
`delta` is -1, 0, or 1. This is not a new BVMul solver. It is the required
non-LLM baseline for deciding whether the remaining triangular-sum signal is
specific to semantic LLM generation rather than obvious quadratic enumeration.
It first extracts an inductive affine base, then tests quadratic templates one
at a time under a single total certificate budget. This avoids making one hard
BVMul query over many mutually irrelevant polynomial candidates and records the
number tested, 5-second per-template timeouts, and the winning deterministic
index. A timed-out template is reported and search continues within the total
budget; it is never accepted without C1/C2/C3.

### Trusted candidate checker

`scripts/candidate_cert_check.py` now:

- matches the C++ predicate AST semantics (logical `and/or/not`, exact BV widths,
  no implicit extension);
- checks every BAD property in a BTOR2 file;
- rejects unsupported forms explicitly;
- supports full-conjunction checking and `--houdini` subset extraction;
- in Houdini mode, rejects unsupported candidates individually and records
  their indices/errors instead of aborting or silently dropping them; exact
  full-conjunction mode remains strict;
- treats `--timeout-ms` as a total Houdini budget (full-conjunction mode applies it per C1/C2/C3 check);
- emits selected candidates only when requested;
- certifies only C1/C2/C3 all `unsat`.

`run_matrix.py` exposes the same trusted path as `llm-houdini-cert`.  Certificate
time is counted as proof time, not hidden as candidate processing time.
`scripts/summarize_reliability.py` merges independent capture matrices, rejects
duplicate replay identities, and reports verdict rates plus min/median/p95/max
timing and token statistics.

`scripts/cert_check.py` also checks the disjunction of all BAD properties rather
than silently retaining only the final BAD node.

## Reproducible Commands

Capture one immutable frozen run:

```bash
python3 scripts/capture_candidates.py \
  --benchmark-root /home/swear01/hwmcc_benchmarks \
  --manifest artifacts/corpus.json \
  --out artifacts/capture-01 \
  --rounds 5 \
  --cap 20
```

Run the corrected matrix:

```bash
python3 scripts/run_matrix.py \
  --benchmark-root /home/swear01/hwmcc_benchmarks \
  --manifest artifacts/capture-01/manifest.json \
  --pred-dir artifacts/capture-01 \
  --configs baseline,static-linear,static-ranked,static-oracle,static-quadratic-oracle,llm-linear,llm-houdini-cert,llm-two-tier,portfolio \
  --timeout 70 \
  --cap 20 \
  --static-oracle-pool-cap 2000 \
  --static-oracle-inject-cap 64 \
  --cert-timeout-ms 70000 \
  --ic3ia-max-refinements 0 \
  --out artifacts/matrix.csv
```

Check a full conjunction:

```bash
python3 scripts/candidate_cert_check.py \
  circuit.btor2 predicates.jsonl --timeout-ms 20000
```

Extract a sound Houdini subset:

```bash
python3 scripts/candidate_cert_check.py \
  circuit.btor2 predicates.jsonl \
  --houdini --emit-selected selected.jsonl --timeout-ms 20000
```

## Current Experiment Queue

Corrected frozen full21 results with a 70-second static-oracle budget:

| Configuration | UNSAT | SAT | Other |
|---|---:|---:|---:|
| baseline | 3 | 2 | 16 |
| static-linear | 3 | 0 | 18 |
| static-oracle | 5 | 0 | 16 |
| static-quadratic-oracle | 7 | 0 | 14 |
| LLM-linear | 5 | 0 | 16 |
| LLM-two-tier | 7 | 0 | 14 |
| portfolio | 8 | 2 | 11 |

`static-oracle` and LLM-linear solve exactly the same five circuits.
`static-quadratic-oracle` adds `fib_23` and `fib_30`, exactly matching the seven
LLM-two-tier UNSAT cases. Combined with the engine baseline, the deterministic
portfolio and the LLM portfolio each cover the same eight safe circuits plus
the same two SAT circuits.

Independent nonlinear reliability (five distinct captures per circuit):

| Circuit | LLM Houdini | Two-tier replay | Median cert time | Median LLM generation |
|---|---:|---:|---:|---:|
| `fib_30` | 5/5 | 3/5 | 0.063s | 125.82s |
| `fib_23` | 5/5 | 4/5 | 0.050s | 48.56s |

These ten bags were produced by capture schema v2 immediately before v3 was
installed. They retain all normalized round responses and metadata; exact
system prompt/source hashes were recorded afterward in `provenance.json` with
`recorded_after_capture=true`. Legacy unsupported `div`/`ite` candidates are
reported and rejected during replay. New captures use v4 natively; v4 retains
v3 durable provenance and adds benchmark/capture integrity binding.

The matched deterministic quadratic oracle then certifies `fib_30` in 2.50s
end-to-end (winner index 0) and `fib_23` in 4.21s (winner index 144). Thus the
nonlinear formulas are valid and reproducibly generated, but are not unique to
the LLM.

This matched oracle is a falsification baseline, not yet an efficient general
portfolio: over all 21 circuits its median end-to-end time is 33.72s and total
time is 804.03s because 14 misses consume the certificate budget. Structural
recurrence targeting is required before scaling it.

Full21 direct LLM Houdini replay certifies exactly the same seven circuits and
returns unknown on 14. Proof-only certificate time is efficient (median 0.083s,
34.32s total), but frozen LLM generation dominates (1103.64s and 318,001 tokens;
1138.15s end-to-end). Static quadratic totals 804.03s with no API calls. Thus
LLM proposals target useful formulas better at proof time, but do not win
end-to-end or in coverage on this set.

Artifacts:

- index and hashes: `artifacts/README.md`,
  `artifacts/phase1_2_artifact_hashes.json`,
  `artifacts/gate2_artifact_hashes.json`;
- pre-quadratic matrix: `artifacts/phase1_2_corrected_full21_matrix_final.csv`;
- refreshed static matrix: `artifacts/phase1_2_corrected_static_full21_v3.csv`;
- nonlinear reliability: `artifacts/phase1_2_nonlinear_reliability.json`.

Canonical summaries are generated by `scripts/summarize_phase1_2.py` and
`scripts/summarize_gate2.py`; `scripts/hash_research_artifacts.py` regenerates
both independent SHA-256 manifests after the summaries and artifact index are
finalized. Historical replay CSVs were metadata-enriched on 2026-07-12 with
post-hoc verified benchmark/source-manifest/capture-integrity hashes; their
verdict, candidate, and timing fields were not altered. New replay rows emit
these hashes natively.

Next queue:

1. **Completed:** refresh the full21 static matrix after adding exact
   initialization constants and `static-quadratic-oracle`.
2. **Completed:** build and run the Gate 2 corpus with
   `scripts/extract_btor_features.py` and `scripts/select_gate2_corpus.py`.
   The extractor records stable IDs, content hashes, name density, arrays,
   arithmetic/operator classes, multiplication operand classes, source family,
   and size strata. The selector removes byte-identical duplicates and uses a
   fixed-seed round-robin over source/arithmetic/size strata rather than taking
   the first filenames. Engine, affine/quadratic certificate, raw static
   predicate, and frozen LLM comparisons are complete.
3. **Completed:** spend LLM calls only on the 11 new small cases surviving the
   deterministic-first selection; corrected matched coverage gain is zero.
4. **Completed:** add the post-hoc fixed low-complexity `static-ranked`
   falsification baseline. It removes the remaining `up.btor2` compactness
   signal at cap 20 and succeeds with a 16-predicate prefix.
5. Next, pivot to paired source/lifted/raw representations. Do not keep mining
   the same HWMCC representation or tune this ranker against the frozen targets.
6. Do not run the BVMul CEGAR spike from `fib_23`/`fib_30`; deterministic direct
   certificates already remove that motivation.

Gate 2 feature extraction and portable selection:

```bash
python3 scripts/extract_btor_features.py \
  --benchmark-root /home/swear01/hwmcc_benchmarks \
  --out artifacts/gate2_features.csv

python3 scripts/select_gate2_corpus.py \
  artifacts/gate2_features.csv \
  --target 500 \
  --out artifacts/gate2_manifest.json

python3 scripts/select_gate2_survivors.py \
  artifacts/gate2_baseline_screen_10s.csv \
  --benchmark-manifest artifacts/gate2_manifest.json \
  --features artifacts/gate2_features.csv \
  --max-nodes 100000 \
  --out artifacts/gate2_baseline_screen_survivors_le100k.json

python3 scripts/select_gate2_llm_targets.py \
  artifacts/gate2_baseline_screen_survivors_le10k.json \
  --prior-matrix artifacts/phase1_2_corrected_full21_matrix_final.csv \
  --prior-capture artifacts/phase1_2_frozen_v2 \
  --deterministic-matrix artifacts/gate2_static_quadratic_le10k_70s.csv \
  --out artifacts/gate2_llm_targets.json
```

Parse failures are written as explicit error rows and cause a non-zero extractor
exit; partial long-running output remains in `*.partial` until a complete scan
is atomically promoted.

The `--max-nodes` analysis bound is explicit in the survivor manifest, including
every excluded benchmark and its node count. It is used before Python/Z3 direct
certification because solver timeouts do not bound BTOR2-to-Z3 construction;
the engine baseline still runs on the full 86-circuit set.

First exhaustive extraction result: all 1,919 BTOR/BTOR2 files parsed without
error in 547.17s. The current preserved-name heuristic identifies 194 likely
software-origin models, of which 89 are scalar/non-array. Exact byte-content
deduplication removes three repeated yearly instances, leaving **86 unique
eligible circuits** (66 exact benchmark IDs are outside the full21 corpus).
Therefore Gate 2 is an exhaustive scan of the actual current-method population,
not a padded 300--500 sample. The 86 unique selected models contain **27 affine,
48 nonlinear, and 11 non-arithmetic** circuits across four size buckets.

Deterministic-first Gate 2 status:

- a sequential screen with parallel `ind`/`interp` at 10s followed by IC3IA at
  10s decides 17 UNSAT and 7 SAT; 54 timeout and 8 unknown remain (62/86), with
  1217.70s aggregate end-to-end time;
- nine survivors exceed 100,000 nodes and are explicitly retained as a scale
  limitation rather than sent through unbounded Python-to-Z3 construction;
- 27 survivors are at most 10,000 nodes. A 70s
  `static-quadratic-oracle` run solves five, all already in full21 (`93.c`,
  `fib_30`, `fib_37`, `fib_05`, `fib_23`), and adds **zero new Gate 2 solves**;
  the matrix has 21 unknown and one timeout, totaling 1519.12s;
- removing the 16 full21 overlaps from those 27 leaves 11 new, small,
  baseline-screen-hard and deterministic-hard circuits. These are the only
  models receiving new LLM calls.

Gate 2 LLM result and matched-baseline correction:

- capture v3 completed 55/55 calls over the 11 targets: 257,647 tokens and
  467.85s generation, with no invalid ASTs;
- direct sound Houdini certification solves 0/11. It keeps inductive subsets on
  several cases, but every C3 check is SAT;
- unrestricted LLM predicate seeding solves exactly one case, natural
  `loop-invgen/up.btor2`, in 8.05s proof time. Its returned Pono invariant passes
  independent C1/C2/C3 checking on the original BTOR2;
- this apparent unique solve exposed a deterministic variable-selection bias:
  five hot 1-bit control states displaced named loop counter `i` from the
  eight-variable static pool. After clean-software-first selection, every LLM
  predicate appears in the deterministic pool by index 329;
- raw deterministic predicate seeding with cap 200 also solves `up.btor2`
  (16.72--18.95s across the recorded runs), and its returned invariant likewise
  passes C1/C2/C3. Across all 11 targets, LLM cap-20 and static cap-200 therefore
  solve the exact same one case. Aggregate end-to-end is 901.52s for LLM versus
  464.80s for static;
- the initial comparison left a **compactness/search-efficiency hypothesis**:
  15 LLM predicates proved `up` in about 8s, while the broad deterministic
  enumeration needed a prefix between 193 and 200 and about 17--19s;
- a post-hoc fixed low-complexity ranker removes that hypothesis. It emits
  pairwise unsigned orders among clean named variables before `x+y==z`
  equalities. Cap 20 solves exactly the same one target, with 377.58s aggregate
  end-to-end versus 901.52s for LLM and 464.80s for cap-200 static;
- on five repeated `up` replays, LLM-15 and ranked-20 are both 5/5. Their median
  proof times are 8.115s and 2.134s. Ranked prefix 15 returns unknown, prefix 16
  proves UNSAT, and the cap-16 returned invariant passes independent C1/C2/C3.
  The family was selected post hoc, so this is claim falsification rather than
  prospective evidence for a new ranking algorithm.

The LLM `up` candidates are not themselves invariants: Houdini removes every
nontrivial LLM formula at C1. Their value is solely as sound abstraction
vocabulary. Deterministic comparisons must therefore inject raw proposals under
the same predicate semantics, not only compare certified invariant conjunctions.

## Claim Boundary

Allowed now:

- predicate injection is sound for arbitrary candidate formulas;
- the original constraint-injection wins were invalid;
- balanced/static-oracle baselines remove the three former linear LLM-only wins;
- independent LLM candidate bags reliably contain certifying nonlinear formulas;
- a small deterministic quadratic oracle removes the remaining two unique wins;
- current full21 LLM-specific solved count is zero under the matched template portfolio;
- Gate 2 contributes zero LLM-specific solves, and a post-hoc 16--20-predicate
  deterministic ranker removes the only observed compactness signal.

Not allowed now:

- “LLM is necessary” for any current full21 case;
- “Phase 2 proves an LLM coverage gain”;
- “LLM provides a surviving compactness/search-efficiency advantage on `up`”;
- publication-readiness claims;
- BMC/SMT `unknown` as evidence;
- final BTOR2 constraint/assume injection.
