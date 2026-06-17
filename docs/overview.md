# Overview

## What This Is

**pono-llm** is a research fork of [Pono](https://github.com/stanford-centaur/pono), an SMT-based hardware model checker from Stanford. The fork adds LLM-guided invariant pre-processing for circuits compiled from C programs: LLM sees circuit semantics (actual transition formulas, variable names) and generates arithmetic loop invariants that are formally verified and injected as BTOR2 `constraint` statements before the model checker runs.

## Key Concepts / Domain

- **IC3/IC3IA**: Property-directed reachability (PDR) model checking algorithm; IC3IA adds predicate abstraction for bit-vector designs.
- **BTOR2**: Binary format for hardware transition systems; Pono's primary input.
- **Software-origin circuit**: A BTOR2 circuit compiled from a C program. Variable names (i, n, x, y, sum) are preserved in state labels. These circuits have loop-like transition structures that LLM can reason about.
- **BTOR2 constraint injection**: Adding `constraint` statements to BTOR2 before IC3IA runs. The constraints restrict the state space; IC3IA solves in <0.3s on pre-constrained circuits.
- **Pre-processing pipeline** (`llm_worker/invariant_arith.py`): Detects software-origin circuits, injects structural invariants, calls LLM for arithmetic invariants, verifies each candidate with IC3IA as oracle, injects sound ones.
- **Sidecar**: Python process for mid-run LLM calls during IC3IA execution (Stage 0/2). Less critical now that pre-processing works; handles non-software-origin circuits.
- **smt-switch**: Solver-agnostic C++ SMT API (Bitwuzla backend used here).

## How It Works

```
software-origin BTOR2
    ↓ detect (C-style var names, output labels)
    ↓ Step 0: Portfolio — try ind/interp in parallel (5s cap)
    ↓    → proved? return immediately (sw_ball2004_2: 1.2s, vcegar: 1.0s)
    ↓ Phase 1: inject sym_pair equalities (eq(x,y) when structurally identical)
    ↓ Phase 2: LLM generates arithmetic invariants using formula-level transition sketch
    ↓ Phase 3: multi-round IC3IA verification (round-1 fast, round-2 with helpers)
    ↓ inject sound invariants as BTOR2 constraint statements
constrained BTOR2
    ↓
pono --engine ic3ia → UNSAT in <0.3s
```

## Results (2026-06-17)

10 software-origin benchmarks covered (portfolio fast-path + LLM + IC3IA):

**LLM + IC3IA path:**
| Circuit | Pattern | Key invariants |
|---------|---------|----------------|
| 93.c | linear counter | x+y==3*i |
| 77.c | two-counter | x>=i, y>=450-i |
| fib_05 | sym loop | eq(x,y) |
| fib_23 | triangular sum | 2*sum<=i*(i-1) |
| fib_30 | triangular sum | 2*c<=i*(i-1) |
| fib_37 | counter bound | x<=n, m<=x |
| paper_v3 | chasing counter | x<=y, y>=x |

**Portfolio fast-path (k-induction):**
| Circuit | Engine | Time |
|---------|--------|------|
| vcegar_QF_BV_ar | ind | 1.0s |
| sw_ball2004_2 | ind | 1.2s |

Preprocessing: 14–36s (LLM path). Portfolio fast-path: <2s. IC3IA on constrained: 0.02–0.3s.

## External Resources

- Architecture alternatives: [`docs/architecture_plan.md`](architecture_plan.md)
- Active plan: [`docs/plan.md`](plan.md)
- Handoff state: [`docs/HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md)
- Upstream Pono: https://github.com/stanford-centaur/pono
