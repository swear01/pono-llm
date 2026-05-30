# Current Research Narrative

## Problem

Can LLMs assist model checking by proposing semantic lemmas from traces,
with formal methods as the gatekeeper?

## Initial Hypothesis

LLMs are not reliable provers but may be useful semantic hypothesis generators.
If their outputs are filtered by formal checks and guided by counterexample
feedback, they can produce nontrivial inductive lemma candidates.

## What Failed

1. **Single-shot LLM prompting** produces correlation-like candidates, not
   inductive invariants. 5 distinct experiments with single-shot prompts
   produced zero solver-verified useful lemmas.

2. **Repair-only approach** cannot fix candidates that are fundamentally
   wrong. The original LLM proposals were too far from ground truth for
   repair to find nontrivial reformulations.

3. **Pairwise implication synthesis** misses the structure of IC3IA frame
   clauses (multi-literal OR forms). Valid lemmas are produced but don't
   subsume any clauses — zero proof impact.

4. **Direct invariant synthesis on proof-target variables** (state15, the
   variable IC3IA is trying to prove unreachable) fails because the target
   IS reachable — the invariant the solver is searching for doesn't exist
   as a simple property.

## What Worked

1. **Closed-loop solver feedback** found the first solver-verified useful
   lemma (`r_pipe_req ⇒ o_wb_stall`). The key ingredient was iterative
   counterexample-driven refinement — the lemma was never proposed in any
   single-shot experiment.

2. **IC3IA trace dump infrastructure** enabled analysis of what the prover
   is actually doing. Without this, we could not distinguish valid-but-irrelevant
   lemmas from proof-critical ones.

3. **Impact-guided synthesis** improved verified lemma yield from 1 lemma
   in 2 rounds to 3 lemmas in 1 round.

4. **Clause-family lifting** achieved 87% pass rate (26/30 solver-verified)
   with zero LLM calls — fully mechanical. All 15 tested lemmas pass across
   4 qspiflash variants.

5. **Cross-variant validation** confirms lifted lemmas generalize across the
   design family, not specific to one parameterization.

6. **Context-unlock** (CPAchecker): 8 bootstrap predicates converted a
   zero-context timeout into 39-refinement CEGAR run.

## Key Finding 1: Solver Feedback Enables Discovery

Closed-loop solver-guided synthesis found the first useful lemma only after
5 single-shot experiments failed. The LLM needs to see counterexample
feedback to converge toward genuine invariants.

## Key Finding 2: Validity ≠ Proof Impact

The validated lemma `r_pipe_req ⇒ o_wb_stall` is verified, nontrivial,
cross-parameter validated, and repeatedly discoverable — yet has zero
proof-trace impact. A valid invariant may not be a proof-accelerating one.

## Key Finding 3: Frame Clauses Can Be Mechanically Lifted

IC3IA frame clauses (multi-literal OR forms) can be mechanically converted
to equivalent implication lemmas with 87% verification rate. This is
superior to LLM-based synthesis for both yield and cost.

## Key Finding 4: Context Bootstrap Unlocks CEGAR

Zero-information CEGAR loops can be unlocked with a small number of
LLM-generated bootstrap predicates. The mechanism works even if subsequent
repair doesn't yet succeed.

## Current Limitations

- No lemma has been injected into Pono and measured for convergence impact.
- All discovered lemmas are low proof-impact on the tested benchmark.
- CEGAR repair (B5-MR) has not yet produced valid new predicates.
- CPAchecker artifacts are in a separate repo — cross-thread analysis is blocked.

## Next Experiments

1. **Pono injection**: implement concrete assertion injection and measure
   convergence impact of lifted lemmas.
2. **CPAchecker logging**: add per-candidate fate logging and classify B5-MR failures.
3. **Controlled benchmark**: design a lemma-critical design where baseline
   timeout and oracle lemma unlocks the proof.
4. **Bootstrap ablation**: determine which subset of bootstrap predicates
   is sufficient for context-unlock.
