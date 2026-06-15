> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

# Current Progress Summary

> **2026-06-03:** Integration pivot to **IC3 Frame v1** (online, frame-native). Legacy runtime **to be deleted**.  
> **Spec:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

## One-Sentence Summary (historical offline result)

Closed-loop solver-guided synthesis discovered and cross-validated a
nontrivial semantic lemma (`r_pipe_req ⇒ o_wb_stall`) for the qspiflash
controller family — the first solver-verified useful invariant from the
LLM-assisted pipeline.

## Main Result

```
Lemma:  (=> (= state2002 1) (= state790 1))
Meaning: r_pipe_req = 1 ⇒ o_wb_stall = 1
Reading:    Pipeline request implies bus stall
```

| Check | Result |
|---|---|
| Parse | OK |
| Reachable filter | pass (1/1 applicable samples) |
| Nontriviality gate | pass (5/5 checks) |
| Non-vacuity | pass (state2002=1 is one-step reachable) |
| Init | UNSAT |
| One-step | UNSAT |
| Induction | UNSAT |
| Encoding scope | Bitwuzla standalone, 88% transition coverage |

## Evidence

| Property | Result |
|---|---|
| Discovery method | Closed-loop synthesis (2 rounds, CE feedback) |
| Cross-parameter | 6/6 variants (p020, p027, p040, p063, p114, p162) |
| Repeatability | Found in 5/8 trials (63%), verified useful in 4/8 (50%) |
| Novelty | Never proposed in original 30-candidate batch |
| Consistency | 0/17 historical samples violated |
| Prior experiments | 5 single-shot experiments produced 0 useful lemmas |

## What Worked

1. **Closed-loop solver feedback**: single-shot experiments (5 total) produced
   zero useful lemmas. Adding CE feedback → LLM refine → found a genuine
   invariant in 2 rounds.

2. **Gate ladder**: Reachable filter (fast) + Nontriviality (fast) + Init (SMT) +
   One-step (SMT) + Induction (SMT). Each layer rejects candidates cheaply
   before expensive checks.

3. **Variable shift via feedback**: Round 0's state1536-based failures caused
   the LLM to abandon that variable and discover the state2002/790 pair.

4. **Cross-parameter validation**: Same BTOR2 node IDs across all qspiflash
   variants enabled instant validation without remapping.

## What Failed

1. **Single-shot prompting** (5 experiments): always produced candidates that
   were either trivial, excluded reachable values, or failed induction.

2. **Repair-only approach**: original candidates were too far from ground
   truth for repair to produce nontrivial inductive lemmas.

3. **Resynthesis without reachability constraints**: LLM proposed lemmas that
   directly contradicted counterexample values (e.g., `state1536 <= 14`).

4. **State1536-based candidates**: the mode register has 667-char deeply nested
   transition logic; LLM cannot extract causal implications from it.

## Key Insight

```
Single-shot prompting produced correlation-like candidates.
Closed-loop solver feedback shifted the LLM toward a genuine
bus-handshake invariant.
```

The winning lemma was never proposed in any single-shot experiment. It emerged
only through iterative propose → validate → CE feedback → refine.

## Repeatability

| Metric | Value |
|---|---|
| Target lemma found | 5/8 trials (63%) |
| Solver-verified useful | 4/8 trials (50%) |
| Always found in round | 1 (requires CE feedback) |
| Per-trial latency | 155-345s |

Recommend running 3-5 parallel trials and taking union of results.

## Cross-Parameter Validation

The lemma holds across all 6 qspiflash_dualflexpress_divfive parameterizations.
It is a genuine design invariant, independent of the clock divider configuration.

## Remaining Limitations

1. **No IC3IA frame data**: clause subsumption, frame relevance, and CTI
   blocking impact cannot be estimated without Pono frame/CTI dump.
2. **Offline validation**: not integrated with Pono's `rel_ind_check`.
3. **No runtime measurement**: impact on proof convergence unknown.
4. **Single benchmark family**: validated only on qspiflash variants.
5. **Single useful lemma found**: not a batch of verified invariants.

## Next Engineering Step

1. **IC3IA frame/CTI dump** (blocking): add minimal JSONL export from Pono
   for clause subsumption and CTI blocking proxy (see `docs/lemma_impact_proxy_plan.md`).
2. **Lemma impact proxy**: estimate how many clauses the lemma would subsume.
3. **If impact positive**: Pono `rel_ind_check` integration.
4. **If impact negative**: more closed-loop synthesis over broader variable sets.
5. **Controlled benchmark**: design a design where baseline IC3IA times out.
