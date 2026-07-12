# Roadmap

**Updated:** 2026-07-12

**Branch:** `soundness-audit`

## Current Decision

The project has a sound integration architecture, but it does not yet have a
defensible LLM-specific coverage claim. LLM formulas remain untrusted IC3IA
abstraction predicates; final proofs target the original BTOR2 model.

The corrected deterministic baselines changed the Phase 2 conclusion:

- the old `static-linear` run was invalid as an affine comparison because its
  cap was exhausted by unary predicates before pairwise/affine templates;
- balanced static predicates now solve `fib_37` directly;
- the deterministic static oracle (balanced templates + sound Houdini +
  affine projection predicates) solves `93.c`, `fib_37`, and `fib_05`;
- therefore these three cases are no longer evidence of LLM-specific value.
- five independent nonlinear captures certify `fib_23`/`fib_30` 10/10 through
  direct Houdini, but a generic deterministic quadratic oracle also certifies
  both in 2.50s/4.21s end-to-end;
- no current full21 solve remains unique to the LLM after matched affine and
  quadratic templates.

The gates below are complete and do not support a coverage-improvement paper.
Do not start open-ended BVMul work or paper writing merely to preserve the old
claim; the next research gate changes the representation.

## Gate 1 — Corrected Phase 1+2 Validation (Complete)

1. **Completed:** corrected 21-circuit frozen replay with:
   - engine baseline;
   - balanced `static-linear`;
   - `static-oracle`;
   - frozen LLM linear/two-tier;
   - baseline+LLM portfolio.
   Pre-quadratic result: static-oracle and LLM-linear solve the same five
   circuits; nonlinear `fib_23`/`fib_30` were the only two-tier additions.
2. **Completed:** five independent captures for nonlinear `fib_23` and
   `fib_30`. Direct Houdini is 10/10; two-tier predicate replay is 3/5 and 4/5.
3. **Completed:** report separate:
   - proof time;
   - candidate generation time;
   - candidate processing/certification time;
   - offline time;
   - end-to-end time;
   - tokens and candidate hashes.
4. **Completed:** `static-quadratic-oracle` certifies both cases, removing the
   remaining LLM-specific signal.
5. **Completed:** refreshed full21 static replay. Static quadratic solves the
   exact seven LLM-two-tier cases; engine + deterministic and engine + LLM
   portfolios both cover eight UNSAT plus two SAT. Generic quadratic misses are
   expensive, so Gate 2 must add structural targeting before a 300--500 scan.

**Decision:** Gate 1 currently leaves zero LLM-specific wins. Direct certificate
time and Pono model-checker time remain separate mechanism measurements.

## Gate 2 — Measure the Dataset Ceiling

Gate 1 leaves no current LLM-specific signal. The next empirical gate is:

1. extract structural features for a stratified target of up to 500 circuits;
   deduplicate exact file content and report the actual eligible population
   rather than padding the sample when fewer models preserve usable software
   names;
2. run engine and deterministic/static baselines first;
3. call the LLM only on baseline-hard, software-origin targets;
4. report natural and synthetic benchmarks separately.

Stop HWMCC mining if fewer than five natural baseline-hard targets remain after
the deterministic affine/quadratic oracle.

The completed feature census found 1,919 parsable files but only 89 non-array
models accepted by the current preserved-software-name heuristic; exact content
deduplication leaves 86. Gate 2 therefore evaluates all 86 rather than claiming
a 300--500 sample that the current method cannot actually consume.

The first deterministic screen decides 24/86 (17 UNSAT, 7 SAT) under a
10s+10s engine budget. Of the 27 non-decisive models at or below 10,000 nodes,
the 70s affine/quadratic oracle solves only the five already-known full21 cases
and no new model. After excluding all 16 full21 overlaps, Gate 2 has 11 new
small deterministic-hard targets for frozen LLM capture.

The frozen capture yields one LLM-seeded proof (`loop-invgen/up.btor2`) but no
surviving LLM-specific coverage. The first deterministic run had omitted named
counter `i` because hot control bits consumed `max_vars`. With clean software
variables prioritized, static raw-predicate seeding at cap 200 also proves `up`;
both returned invariants pass independent C1/C2/C3. LLM cap 20 is more compact
than the broad cap-200 enumeration, but that observation does not survive a
post-hoc fixed relational ranker. Directed same-width named-variable orders
followed by `x+y==z` equalities prove `up` with prefix 16 and are 5/5 at cap 20;
median proof time is 2.134s versus 8.115s for LLM-15. Over all 11 targets,
ranked cap 20 reaches the same one-model solved set in 377.58s aggregate,
compared with 464.80s for cap-200 static and 901.52s for LLM.

**Gate 2 decision:** stop broad HWMCC mining for a coverage claim. The positive
coverage and compactness signals are both falsified under the tested baselines.
Because the final ranker is post-hoc, it is not a new prospective generalization
claim. Any substantive continuation should pivot to the paired
source/lifted/raw representation study rather than tune against these targets.

## Gate 3 — Bounded Nonlinear Investigation

Only if a future natural case survives the corrected affine/quadratic static
portfolio:

1. evaluate existing Pono options:
   - `--ceg-bv-arith`;
   - `--ceg-bv-arith-as-free-symbol`;
   - `--ceg-bv-arith-min-bw`;
2. instrument which BVMul applications are abstracted and concretized;
3. stop if there is no new proof and no meaningful runtime improvement.

New predicate-aware staged BVMul abstraction remains a separate, bounded spike,
not the default continuation of this project.

## Gate 4 — Research Pivot

Corrected deterministic baselines remove all current LLM-only wins and the
remaining compactness observation. The next large project should therefore be
a paired representation study:

1. original C source;
2. lifted BTOR2 recurrence summary;
3. raw BTOR2 transition sketch;
4. all final certificates checked on the same original BTOR2 model.

This tests representation loss directly without claiming that an LLM is needed
where deterministic templates suffice.

## Implemented and Retained

- sound `--initial-predicates` injection in IC3IA;
- independent C1/C2/C3 certificate checking;
- boolean-pair hint reachability audit;
- `--rounds` accumulation and linear/two-tier routing;
- `--ic3ia-max-refinements` sound fail-fast behavior;
- stable benchmark IDs and immutable candidate capture metadata;
- balanced deterministic template generation;
- sound Houdini subset extraction over all BAD properties;
- fair replay timing with exact verdict/error separation.

## Explicit Non-Goals

- restoring BTOR2 constraint/assume injection as a proof method;
- treating BMC or SMT `unknown` as evidence;
- generic BTOR2 decompilation;
- open-ended nonlinear SMT solver development;
- claiming publication readiness from the current 21-circuit corpus.

Historical roadmaps and constraint-era plans live under `archive/docs/` and are
not active project truth.
