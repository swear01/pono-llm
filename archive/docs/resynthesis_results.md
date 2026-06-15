> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Resynthesis Results — Counterexample-Aware Lemma Synthesis

## Motivation

Repair v1 trivialized (bitwidth tautology), repair v2 avoided trivialization
but produced no solver-verified lemmas. Root cause: original candidates were
too far from ground truth for repair to bridge the gap.

This experiment tries **resynthesis** instead: ask LLM to propose entirely new
lemma candidates using all available context (CE models, Verilog symbols,
bitwidths, transition structure). No editing of the old formulas.

## Prompt Design

| Element | Purpose |
|---|---|
| CE next-state values per cluster | LLM knows what violates old lemmas |
| Verilog symbol names | Ground lemmas in design meaning |
| Bitwidth per variable | Prevents bitwidth tautologies |
| Transition dependency cones | Hints at causal structure |
| Banned patterns per cluster | Prevents known trivial formulations |
| "reject" as valid strategy | OK to say unsalvageable |

3 failure clusters:
1. CLUSTER_MODE_STALL: o_dspi_mod ↔ o_wb_stall, o_dspi_mod ↔ cfg_mode
2. CLUSTER_REQUEST_MODE: r_pipe_req ↔ o_dspi_mod
3. CLUSTER_MODE_CFG: o_dspi_mod ↔ cfg_speed (marked unsalvageable)

## Results

| Candidate | Lemma | Schema | Init | One-Step | Induction | Gate Verdict |
|---|---|---|---|---|---|---|
| resyn_001 | `!(state1536=10 && state790=1)` | mutual_exclusion | UNSAT | SAT | SAT | init_pass_one_step_fail |
| resyn_002 | `(<= state1536 14)` | range_bound | UNSAT | SAT | SAT | init_pass_one_step_fail |
| resyn_003 | `!(state2002=1 && state1536=15)` | mutual_exclusion | UNSAT | SAT | SAT | init_pass_one_step_fail |
| resyn_004 | `(not (= state1536 15))` | disequality | UNSAT | SAT | SAT | init_pass_one_step_fail |
| resyn_005 | — | reject | — | — | — | rejected_by_llm |

**Summary**: 0 solver_verified_useful, 0 solver_verified_trivial, 4 init_pass_one_step_fail, 1 rejected.

## Analysis Per Candidate

### resyn_001: `!(state1536=10 && state790=1)`

- **Logic**: mode=10 and stall=1 cannot co-occur
- **Init**: OK (both 0 at init)
- **One-step**: SAT — state1536=10 AND state790=1 IS reachable
- **Why it fails**: The CE from cand_007 proves exactly this: mode=10 and
  stall=1 co-occur in a write transaction. The LLM proposed a mutex that is
  the DIRECT OPPOSITE of the evidence — the CE shows these states DO co-occur.

### resyn_002: `(<= state1536 14)`

- **Logic**: mode never reaches value 15
- **Init**: OK (init=0)
- **One-step**: SAT — state1536=15 IS reachable (CE from cand_004)
- **Why it fails**: The mode register has 16 states (0-15), and 15 is a valid
  operational mode (request-active). The lemma that forbids mode=15 is overstrong.

### resyn_003: `!(state2002=1 && state1536=15)`

- **Logic**: request-active and mode=15 cannot co-occur
- Same failure as resyn_001 — the CE proves these DO co-occur.

### resyn_004: `(not (= state1536 15))`

- **Logic**: mode is never 15
- Same as resyn_002 — mode=15 is reachable and meaningful.

### resyn_005: CLUSTER_MODE_CFG

- LLM correctly rejected this cluster as unsalvageable.

## Interpretation

The resynthesis candidates show a pattern: **LLM proposes lemmas that directly
contradict the counterexamples**, as if trying to "block" them by assertion.
This produces lemmas that are guaranteed to be false because the CE values ARE
reachable states.

The underlying issue is that the LLM lacks a way to test reachability. The
pipeline asks it to "block the CE", but blocking should come from a causal
understanding of the transition, not from asserting the opposite of observed
behavior.

This is a fundamental limitation of the synthesis-only approach: counterexamples
show reachable states, and the LLM cannot distinguish which states are
unavoidable vs. which are accidental in the CE.

## Parser Extension

Added 3 patterns to `lemma_to_smt` in `smt_checker.py`:
- `(<= stateX V)` — standalone upper bound
- `(>= stateX V)` — standalone lower bound
- `(not (= stateX V))` — standalone disequality

## Recommended Next Step

**BMC-guided synthesis.** Before proposing lemmas, run 2-3 step bounded model
checking to identify states that are DEFINITELY unreachable (BMC depth)
vs. merely not yet seen. Then ask the LLM to propose lemmas over known
unreachable states, reducing the risk of asserting the opposite of observed
behavior.
