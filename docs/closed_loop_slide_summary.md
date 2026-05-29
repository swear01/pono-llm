# Slide-Ready Summary: Closed-Loop Synthesis

> Speaker notes version. For slides, use key phrases only.
> Each `##` section = one slide idea.

---

## Main message

**Solver-in-the-loop feedback** changed the search direction and produced
the first solver-verified useful semantic lemma in this prototype.

Speaker notes:
- 5 prior single-shot experiments produced zero useful lemmas.
- Closed loop (2 rounds) found one: `r_pipe_req ⇒ o_wb_stall`.
- The winning lemma was NOT proposed in any single-shot experiment.
- Key ingredient: solver counterexamples fed back to LLM.

---

## Pipeline (flowchart)

```
Pono/IC3IA traces + CTI clusters
  ↓
LLM proposes semantic lemma candidates
  ↓
Reachable filter (fast) → Nontriviality gate (fast) → Init check
  ↓
One-step check (SMT) → Induction check (SMT)
  ↓
If fail: extract counterexample → feed back to LLM → refine
  ↓
If pass: accept as solver-verified useful lemma
```

Speaker notes:
- Three pre-gates (reachable, nontrivial, init) filter ~80% of bad candidates
  before expensive SMT checks.
- Counterexample feedback is the critical loop that enables convergence.

---

## Round 0 → Round 1

```text
Round 0: 3 candidates, all state1536-based
  (o_dspi_mod: mode register, 667-char transition logic)

  cls_r0_001: state1536=0 => state790=1   → one-step fail
  cls_r0_002: state1536=0 => state79=0    → one-step fail
  cls_r0_003: state1536=15 => state790=0  → one-step fail

    3 counterexample blocks fed back to LLM

Round 1: LLM shifts variables → new pair

  cls_r1_001: state2002=1 => state790=1
    → SOLVER VERIFIED USEFUL ✓
```

Speaker notes:
- State1536 transition is too complex for LLM to reason about causally.
- CE feedback showed ALL state1536-based implications were unreliable.
- LLM learned to avoid state1536 and found state2002/state790 pair.

---

## Winning Lemma

```text
Lemma:  (=> (= state2002 1) (= state790 1))

Meaning: r_pipe_req = 1 ⇒ o_wb_stall = 1
         Pipeline request implies bus stall

Init:        UNSAT ✓
One-step:    UNSAT ✓
Induction:   UNSAT ✓
Reachable:   pass ✓
Nontrivial:  pass ✓ (both 1-bit, not tautology)
Non-vacuity: pass ✓ (state2002=1 is one-step reachable)
```

Speaker notes:
- Standard bus-handshake constraint: pending request requires bus exclusivity.
- Verified under standalone Bitwuzla pipeline with 88% transition coverage.
- NOT a Pono rel_ind_check result.

---

## Ablation (6-experiment comparison)

| Experiment | Calls | Solver-Useful |
|---|---|---|
| Repair v1/v2 | 1 each | 0 |
| Resynthesis | 1 | 0 |
| Reachability-aware | 1 | 0 |
| Transition-aware | 1 | 0 |
| **Closed-loop** | **2** | **1** |

Speaker notes:
- Single-shot prompts consistently fail at induction.
- Only iterative solver feedback produces a genuine invariant.
- The winning lemma was never proposed in any single-shot experiment.

---

## Claim and Non-Claim

**Safe claim**:
> Closed-loop solver-guided synthesis produced one solver-verified, nontrivial
> semantic lemma under the offline Bitwuzla validation pipeline.

**Do NOT claim**:
- runtime speedup
- benchmark unlock
- full Pono integration
- frame injection
- rel_ind_check
- LLM replaces Pono clause generalization

Speaker notes:
- This is a prototype result. One lemma, one benchmark, offline validation.
- The contribution is the **mechanism** (closed-loop with solver feedback),
  not the impact on this specific benchmark.

---

## Next Steps

```text
1. Repeatability test (re-run loop on fresh session)
2. Multi-benchmark test (qspiflash variants)
3. Controlled benchmark (lemma-critical design)
4. Pono rel_ind_check proxy (clause impact estimate)
```

Speaker notes:
- Repeatability is the most important next step — does the loop reliably find
  this same lemma?
- Multi-benchmark: qspiflash has 10+ parameterizations with similar structure.
- Controlled benchmark: design a Verilog module where baseline IC3IA times out
  and an oracle semantic lemma unlocks the proof.
