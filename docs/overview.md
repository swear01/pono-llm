# Overview

## What This Is

**pono-llm** is a research fork of [Pono](https://github.com/stanford-centaur/pono), an SMT-based hardware model checker from Stanford.  The current research branch (`soundness-audit`) studies how to integrate LLM-generated formulas into IC3IA **soundly** for software-origin BTOR2 circuits.

The current sound integration point is **IC3IA initial predicate injection**:

```bash
pono -e ic3ia --initial-predicates <predicate_json> <original.btor2>
```

LLM formulas are treated as untrusted abstraction predicates, not as assumptions.  Predicate injection refines the IC3IA abstraction vocabulary/abstract transition relation while preserving an over-approximation of the original transition system.  A false LLM formula can waste time, but it cannot create a fake UNSAT proof of the original circuit.

## Key Concepts / Domain

- **IC3/IC3IA**: Property-directed reachability (PDR) model checking; IC3IA adds implicit predicate abstraction and refinement for bit-vector transition systems.
- **BTOR2**: Word-level hardware transition-system format used by Pono and HWMCC.
- **Software-origin BTOR2**: BTOR2 generated from C-like programs where state names such as `i`, `n`, `x`, `sum` often survive compilation.
- **Sound predicate injection**: LLM/static candidates are added as abstraction predicates via `--initial-predicates`; they are not asserted as invariants.
- **Rejected old path**: injecting candidates as BTOR2 `constraint` / `assume` statements is under-approximation and is not a sound safety-proof method.
- **Certificate checks**: `scripts/cert_check.py` audits an invariant on the original BTOR2 via C1/C2/C3 and checks every BAD property. `scripts/candidate_cert_check.py` checks predicate-JSON conjunctions directly and can extract a sound Houdini subset.

## Current Pipeline Shape

```
BTOR2 benchmark
    ↓
try fast engine portfolio (ind/interp/plain ic3ia baseline)
    ↓ miss
LLM or deterministic generator proposes predicate-AST candidates
    ↓
rewrite refs to Pono internal state<lineno> names
    ↓
optional filtering: linear-only / two-tier / full
    ↓
pono -e ic3ia --initial-predicates <json> <original.btor2>
    ↓
UNSAT/SAT/UNKNOWN for the original unconstrained circuit
```

`predicate_workflow.py` currently supports `full`, `linear`, and `two-tier` modes.  `two-tier` tries linear predicates first and only falls back to full candidates on miss.  `--rounds=K` accumulates candidates across K LLM calls to improve reliability.

## Current Results (as of 2026-07-12)

Soundness is fixed; coverage/research value is not yet settled.

- Old boolean-pair mutex hints injected as constraints: **not sound proofs**.  Audit: 32/32 checkable instances rejected; 30/32 tested mutex hints are reachable false invariants at BTOR2 level.
- Sound predicate injection works for arithmetic predicates and fails soundly on bad hints.
- `--two-tier --rounds=5` makes the five known linear-solvable circuits stable: `paper_v3`, `93.c`, `fib_37`, `77.c`, `fib_05` → 15/15 UNSAT across three trials.
- The first static comparison was biased by candidate ordering: its cap was exhausted by unary predicates before affine templates. After balancing the generator, `static-linear` solves `fib_37`; the stronger deterministic static oracle solves `93.c`, `fib_37`, and `fib_05`.
- Therefore the three former linear-tier “LLM-only” wins are predicate-seeding wins, not evidence that an LLM is necessary.
- Corrected full21 frozen replay (`static-oracle` total budget 70s): baseline 3 UNSAT + 2 SAT; static-linear 3 UNSAT; static-oracle 5 UNSAT; LLM-linear 5 UNSAT with the **same solved set** as static-oracle; LLM two-tier 7 UNSAT; portfolio 8 UNSAT + 2 SAT.
- Five independent round-5 captures for nonlinear `fib_23` and `fib_30` produce
  ten distinct candidate hashes. Direct sound Houdini certification succeeds
  10/10; median certificate time is 0.050s (`fib_23`) and 0.063s (`fib_30`).
  Predicate replay is less reliable/slower: 4/5 and 3/5 respectively under the
  recorded two-tier budgets.
- A matched deterministic `static-quadratic-oracle` then certifies both cases
  without an LLM: `fib_30` in 2.50s end-to-end and `fib_23` in 4.21s. It uses
  exact initialization constants plus the generic template
  `k*accumulator {==,<=,>=} counter*(counter±1)`.
- Refreshed clean-software-first full21: static-linear solves 3, affine static-oracle 5, and
  static-quadratic-oracle 7--exactly the LLM two-tier solved set. The engine +
  deterministic portfolio reaches the same eight UNSAT and two SAT cases as
  engine + LLM. The quadratic oracle is expensive on misses (median 33.72s), so
  this is a uniqueness falsification result, not yet a scalable replacement.
- Therefore **no LLM-specific solved case currently survives the deterministic
  affine/quadratic portfolio**. The direct-certificate result validates a sound,
  reliable mechanism, but not unique LLM value on this corpus.
- Direct LLM Houdini over all 21 cases solves exactly those seven with only
  34.32s total certificate time, but candidate generation costs 1103.64s and
  318,001 tokens (1138.15s end-to-end). The deterministic quadratic oracle takes
  804.03s total and no API calls. LLM targeting helps offline checker effort,
  not full-pipeline coverage or total cost here.
- Expanding to 20 additional non-array software/sosylab circuits found 4 more LLM solves, but all 4 were also solved by baseline ind/interp → 0 new LLM-only.
- Main ceiling: genuine nonlinear `var*var` / `bvmul` invariants, input-driven transitions, arrays, and representation loss.

## Current Research Plan

The project is **not ready** to be positioned as a strong
coverage-improvement paper. Corrected Phase 1 + Phase 2 infrastructure, Gate 2,
the full21 replay, and the independent nonlinear captures are complete:

1. **Phase 1:** sound fail-fast, immutable portable captures, exact portfolio
   timing, frozen replay hashes, and separate
   generation/processing/proof/end-to-end timing. New capture schema v4 binds
   benchmark/manifest/prompt/predicate/metadata/response bytes in
   `integrity.json`; replay rejects incomplete or mismatched bundles. Historical
   v2/v3 sidecars are explicitly marked as post-capture integrity records.
   Replay matrices also bind the exact benchmark/config/trial Cartesian
   contract, and Gate selectors reject partial coverage or stale feature/model
   hashes.
2. **Phase 2:** balanced deterministic templates plus a static oracle using sound Houdini and affine projection predicates.
3. The three former linear LLM-only wins disappear under the corrected deterministic baseline.
4. The nonlinear candidates are independently reproducible, but the matched
   quadratic baseline removes their uniqueness. Do not start BVMul CEGAR from
   these two cases.
5. Gate 2 uses explicit structural features and content deduplication; the
   selected count is capped by the actual non-array, software-name-preserving
   HWMCC population rather than forced to reach a nominal sample size.
   The census parsed 1,919/1,919 files, found 89 eligible scalar models, and
   retained 86 unique contents after removing three repeated yearly instances.
6. A 10s `ind`/`interp` + 10s IC3IA screen decides 24/86. On the 27 unresolved
   models of at most 10,000 nodes, the 70s deterministic quadratic oracle adds
   only the five already-known full21 solves and zero new ones. Excluding all
   prior full21 models leaves 11 new deterministic-hard targets for LLM capture.
7. Frozen LLM capture on those 11 uses 55 calls, 257,647 tokens, and 467.85s.
   Direct candidate certification solves none. Raw LLM predicate seeding solves
   only `loop-invgen/up.btor2`; after correcting static variable ordering, raw
   deterministic cap-200 seeding solves the same case. Both Pono invariants pass
   C1/C2/C3 on the original model. Thus Gate 2 adds **zero LLM-specific wins**.
8. A post-hoc fixed relational ranker then emits pairwise unsigned orders among
   clean named variables before three-variable sum equalities. At cap 20 it
   solves exactly the same one target as LLM and cap-200 static seeding, but in
   377.58s aggregate versus 901.52s and 464.80s. On `up`, LLM-15 and ranked-20
   are both 5/5; median proof time is 8.115s versus 2.134s. Ranked cap 15 fails,
   cap 16 succeeds, and the cap-16 returned invariant passes independent
   C1/C2/C3. The former compactness/search-efficiency signal therefore does not
   survive this post-hoc falsification baseline.
9. Broad HWMCC mining and further prompt tuning stop here. The next substantive
   study should compare source C, a bounded lifted recurrence summary, and the
   raw BTOR2 view while checking every final result on the same original BTOR2.

See [`docs/plan.md`](plan.md) for the active implementation plan and [`docs/roadmap.md`](roadmap.md) for the broader roadmap.

## External Resources

- Upstream Pono: https://github.com/stanford-centaur/pono
- Active plan: [`docs/plan.md`](plan.md)
- Notes / gotchas: [`docs/notes.md`](notes.md)
- Roadmap: [`docs/roadmap.md`](roadmap.md)
