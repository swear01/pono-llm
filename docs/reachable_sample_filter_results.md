> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Reachable Sample Filter Results

## Summary

9 reachable samples collected from existing SAT models + BTOR2 init.
Applied to 5 candidate sets.

| Candidate Set | Total | Consistent | Violates Sample | No Samples | N/A |
|---|---:|---|---|---|---|
| Original 30 (yield) | 30 | 5 | 20 | 5 | 0 |
| Solver shortlist | 5 | 0 | 4 | 1 | 0 |
| Repair v1 | 6 | 4 | 2 | 0 | 0 |
| Repair v2 | 3 | 2 | 0 | 0 | 1 |
| Resynthesis | 5 | 0 | 4 | 0 | 1 |

## Key Violations

| Candidate Set | Candidate | Lemma | Violating Sample | Why |
|---|---|---|---|---|
| Resynthesis | resyn_001 | `!(state1536=10 && state790=1)` | cand_007 CE | Sample has both true |
| Resynthesis | resyn_002 | `(<= state1536 14)` | cand_004 CE | Sample has state1536=15 |
| Resynthesis | resyn_003 | `!(state2002=1 && state1536=15)` | cand_004 CE | Sample has both true |
| Resynthesis | resyn_004 | `(not (= state1536 15))` | cand_004 CE | Sample has state1536=15 |
| Solver shortlist | C1 | `state1536=10 => state790=0` | cand_007 CE | state1536=10, stall=1 |
| Solver shortlist | C2 | `state1536=0 => state1558=0` | cand_008 CE | state1558=1 |
| Solver shortlist | C3 | `state2002=1 => state1536=0` | cand_004 CE | state1536=15 |
| Solver shortlist | C4 | `!(state1536=10 && state79=1)` | cand_005 CE | Both true |
| Repair v1 | cand_007_repair_1 | `(=> (= state790 1) (= state1536 10))` | init_state | init has state790=1 but state1536=0 |

## Interpretation

The reachable-sample filter catches EXACTLY the candidates that fail solver
checks. The filter is a fast, solver-free pre-check that rejects 80-100% of
doomed candidates without expensive SMT calls.

### Resynthesis failures explained

All 4 resynthesis candidates excluded known reachable samples. The LLM proposed
lemmas that directly contradicted counterexample values (e.g., `state1536 <= 14`
when sample has 15). The reachable filter would have caught these BEFORE the
solver validation step, saving time and providing clear diagnostic feedback.

### Consistent but still failing

Both repair v2 candidates are consistent with ALL reachable samples but still
fail one-step checks. This means:

1. They survive the reachable filter (first gate)
2. They pass init check (second gate)
3. They fail one-step induction (third gate)

These are "plausible but not inductive" — they hold on ALL known samples
but fail on some unknown transition path not covered by samples.

### Three-gate pipeline emerges

```
Candidate
  → Reachable-sample filter (fast, solver-free)
  → Nontriviality gate (fast, bitwidth analysis)
  → Init check (light SMT)
  → One-step induction (full SMT)
  → Accept
```

At each gate, most doomed candidates are rejected. This layered approach
minimizes expensive SMT calls.
