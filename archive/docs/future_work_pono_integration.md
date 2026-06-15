> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

# Pono Integration: Future Work

> **SUPERSEDED by v1 spec (2026-06-03).** Active checklist: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) § Implementation checklist.  
> Content below is **historical** (pre-v1 offline pipeline).

## Current Status (2026-05-29)

### Main Result

Closed-loop solver-guided synthesis discovered a cross-parameter qspiflash
invariant:

```
r_pipe_req ⇒ o_wb_stall
```

This lemma:
- Is audited (init UNSAT, one-step UNSAT, induction UNSAT)
- Is nontrivial, non-vacuous
- Passes on all 6 qspiflash variants (p020–p162)
- Is repeatably discoverable (5/8 closed-loop trials, 63%)
- Was never proposed in the original 30-candidate batch

Validation scope: standalone Bitwuzla pipeline, 88% transition coverage.
NOT Pono `rel_ind_check`.

### What Works
- Variable identification: stateNN → BTOR2 node → Verilog symbol
- Init values: 216/249 states
- Init/one-step/induction checks: all queries generate and run
- Transition translation: 218/247 (88%)
- Counterexample extraction: SAT models with PRODUCE_MODELS
- Reachable-sample filter: fast solver-free pre-check
- Nontriviality gate: 5 checks prevent trivial/vacuous lemmas
- Closed-loop synthesis: propose → validate → CE feedback → refine
- Repeatability: lemma found in 63% of trials, useful in 50%

### What Doesn't Work (Blockers)

1. **IC3IA frame/CTI data unavailable**: cannot estimate clause subsumption,
   CTI blocking, or proof impact.
2. **No Pono `rel_ind_check` integration**: lemma not tested inside Pono.
3. **No runtime measurement**: impact on IC3IA convergence unknown.

## Priority

1. **High**: Pono IC3IA frame/CTI dump (see `docs/lemma_impact_proxy_plan.md`)
2. **High**: Lemma impact proxy — clause subsumption estimate
3. **Medium**: Pono `rel_ind_check` integration (if impact proxy positive)
4. **Medium**: Controlled benchmark with lemma-critical invariant
5. **Deferred**: Multi-benchmark closed-loop synthesis
