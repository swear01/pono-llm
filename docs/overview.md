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

The completed representation gate used a separate frozen route flow:

```text
source C / target-derived lifted recurrence / raw BTOR2 cone
    -> strict grammar-route JSON
    -> deterministic predicate expansion
    -> global or all-PC-phase candidates
    -> direct C1/C2/C3, then sound IC3IA replay on original BTOR2
```

That flow remains available as research infrastructure, but its H1/H2/H3
scaling gates failed and it is not the active production pipeline.

## Current Results (as of 2026-07-12)

Soundness is fixed; every tested LLM-specific utility claim has failed a
matched deterministic baseline so far.

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

The project therefore has a reusable sound experimental kernel and a sequence
of strong negative results, but not yet a positive algorithmic contribution of
the scale needed for a coverage paper.

## Current Research Plan

The representation/phase/grammar gate is closed. Do not scale its corpus,
repair its LLM routes, tune prompts on its three successes, or build a general
recurrence lifter after H1/H2/H3 failed their frozen thresholds.

Gate 4B0 is now active under the frozen
[`algebraic_certificate_gate.md`](algebraic_certificate_gate.md) protocol. It
tests a deterministic, proof-carrying modular polynomial identity kernel for
nonlinear C2 obligations while retaining exact original-BTOR2 C1 and C3 checks.
No LLM capture is allowed until the kernel demonstrates value on at least three
independent natural recurrence families. `fib_23` and `fib_30` are development
controls only. Generic BVMul CEGAR, broad HWMCC mining, source decompilation,
Gate 3 route repair, and paper mode remain stopped.

See [`docs/plan.md`](plan.md) for exact results/reproduction and
[`docs/roadmap.md`](roadmap.md) for the next decision gate.

## External Resources

- Upstream Pono: https://github.com/stanford-centaur/pono
- Active plan: [`docs/plan.md`](plan.md)
- Notes / gotchas: [`docs/notes.md`](notes.md)
- Roadmap: [`docs/roadmap.md`](roadmap.md)
