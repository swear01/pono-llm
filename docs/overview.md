# Overview

## Completed independent Quokka soundness audit

Branch `quokka-soundness-audit` completed an implementation-level audit of
whether the pinned public Quokka two-query decision procedure enforces the
side-effect-free candidate premise required by its proof composition. The exact
public source hashes, unsafe controls, candidate strings, verifier configuration,
and pass/stop rules were frozen before UAutomizer execution. All nine frozen
side-effect candidates were false-safe across three mechanisms and three
program templates; a conservative purity recognizer rejected the frozen class.
This is neither
Pono Gate 6 nor Cross-Tool X1; both prior decision boundaries remain immutable.
See [`quokka_soundness_results.md`](quokka_soundness_results.md),
[`quokka_soundness_plan.md`](quokka_soundness_plan.md), and
[`quokka_soundness_preregistration.md`](quokka_soundness_preregistration.md).
The audit makes no LLM/API call and makes no claim about historical paper outputs.

## Independent follow-on result

Branch `cross-tool-audit` begins a new Cross-Tool Soundness and
Matched-Baseline Audit. It does not reopen the closed Pono hypothesis tree.
The preregistered Gate X0 public-artifact census is complete; see
[`cross_tool_audit_plan.md`](cross_tool_audit_plan.md) and the frozen
[`cross_tool_audit_preregistration.md`](cross_tool_audit_preregistration.md).
None of the five frozen candidates met all fourteen artifact requirements, so
the decision is `STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS` and X1--X3 are not
authorized. No verifier or LLM/provider API call was executed. The complete
result is
[`cross_tool_x0_results.md`](cross_tool_x0_results.md). This is an artifact-
availability result, not evidence that any evaluated system is unsound or
ineffective.

## What This Is

**pono-llm** is a research fork of [Pono](https://github.com/stanford-centaur/pono), an SMT-based hardware model checker from Stanford. The closed `soundness-audit` research program studied how to integrate LLM-generated formulas into IC3IA **soundly** for software-origin BTOR2 circuits and how their apparent utility changes under matched deterministic baselines.

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

The completed representation gate used a separate frozen route flow:

```text
source C / target-derived lifted recurrence / raw BTOR2 cone
    -> strict grammar-route JSON
    -> deterministic predicate expansion
    -> global or all-PC-phase candidates
    -> direct C1/C2/C3, then sound IC3IA replay on original BTOR2
```

That flow remains available as frozen research infrastructure, but its
H1/H2/H3 scaling gates failed and no further experiment is authorized here.

## Final Results (closed 2026-07-14)

Soundness is fixed; every tested LLM-specific utility claim in the completed
program fails its matched deterministic baseline.

- Old constraint-injected mutex proofs are invalid: 32/32 checkable proofs fail
  independent C1/C2/C3, and 30/32 tested hints are reachable false invariants.
- Corrected full21 deterministic affine/quadratic templates solve exactly the
  seven LLM-two-tier cases. Engine+deterministic and engine+LLM portfolios both
  reach eight UNSAT and two SAT. Current matched LLM-specific solve count: zero.
- Gate 2's only new LLM-seeded proof (`up.btor2`) is reproduced by cap-200
  static seeding and a smaller/faster fixed relational ranker. Current matched
  LLM-specific compactness/ranking count: zero.
- The completed official paired representation gate contains 267 SV-COMP 2025
  translated tasks, 164 eligible source/BTOR pairs, and a pre-LLM frozen
  20-family pilot.
- A single source/lifted/raw capture uses 60 OpenRouter calls, 142,814 tokens,
  and 229.16s. Strict route checking accepts 36 and rejects 24; malformed routes
  are evidence, not repaired inputs.
- On 12 safe baseline-hard tasks, LLM source/lifted/raw routing solves 1/1/2.
  A no-LLM structural router solves their three-task union. Source has zero
  unique task; no LLM arm adds over structural routing.
- Structural all-phase routing adds only `count_up_down-1` over matched
  structural-global routing. The preregistered phase-local threshold is three,
  so H1 fails 1/3.
- No unsafe control becomes UNSAT. All 12 routed UNSAT rows independently pass
  original-model C1/C2/C3: four direct candidate certificates and eight
  certificates for Pono-returned invariants.
- Gate 4B0 implements a strict equal-width modular-polynomial certificate
  kernel and validates it on `fib_23`/`fib_30`: both development certificates
  pass, while a 20-case negative suite rejects 20/20 at the expected stage.
- The frozen Gate 3 corpus nevertheless contains **zero** v1-eligible natural
  primary task: 39/267 require arrays, 221/267 have no supported nonlinear
  update SCC, and the remaining seven all exceed the preregistered eight-branch
  cap. H5a is therefore not run, H5b is not authorized, and no LLM call was
  made for Gate 4B0.
- Six frozen nonlinear candidates all fail C1 in an initial state; none is a
  valid invariant blocked only by helpers, induction depth, or proof-graph
  organization.
- Gate 5A0 finds 11 certified bases and six T1-applicable bases, below its
  frozen 12/8 population requirements. It stops before transformed variants,
  map validation, utility measurement, or LLM/API calls.

The final scoped result is zero demonstrated LLM-specific solved-set or
search-efficiency advantage on the evaluated populations. The project retains
a reusable sound experimental kernel and a sequence of strong falsification
results, but it does not support a coverage-improvement paper claim.

## Closed Research Program

The representation/phase/grammar gate and Gate 4B0 are closed. Do not scale
their corpora, repair LLM routes, tune prompts on observed successes, widen the
algebraic branch cap post-hoc, or replace the absent natural Gate 4B0 population
with synthetic tasks.

Gate 5 was preregistered as a **known-map certified-transport oracle** under
[`certified_transport_gate.md`](certified_transport_gate.md). Gate 5A0
censused already certified source invariants and tested whether three
non-trivial target families are feasible: modular affine recoding, bit-vector
split encoding, and input-latched stuttering refinement. Alpha-renaming is only
a sanity control and cannot count toward success.

The strict Gate 5A0 census is complete and stopped `population-insufficient`.
It found 11 certified bases (12 required) and six T1-applicable bases (eight
required); every other frozen population condition passed. Eight source-
recovery rows were excluded because the installed ASan Pono cannot start under
the inherited finite hard address-space limit. No fallback binary was used,
no transformed variant was generated, and no LLM/API call occurred.

No transformation implementation or utility run is authorized because the
population **does not reach** 12 certified tasks or eight T1-applicable bases.
Generic BVMul CEGAR, broad HWMCC mining, source decompilation, paid capture,
candidate repair, threshold changes, and Gate 6 remain stopped.

The frozen research boundary is `soundness-audit-final-v1` at
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`. Commit `536a175` is a
post-boundary Oracle-First methodology addendum; it adds no new Pono or LLM
experiment, changes no final claim, and authorizes no follow-on work here.

Use the final [claim ledger](final_claim_ledger.md),
[research narrative](final_research_narrative.md), and
[machine-readable summary](../artifacts/final_research_summary_v1.json) as the
closure entry points. Any cross-tool audit, translation-validated proof reuse,
or source-level repair study must begin as an independent project with a new
population and preregistration.

## External Resources

- Upstream Pono: https://github.com/stanford-centaur/pono
- Closed plan: [`docs/plan.md`](plan.md)
- Notes / gotchas: [`docs/notes.md`](notes.md)
- Roadmap: [`docs/roadmap.md`](roadmap.md)
