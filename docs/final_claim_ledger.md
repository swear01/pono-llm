# Final Claim Ledger — `soundness-audit`

**Closed:** 2026-07-14
**Frozen research boundary:** `soundness-audit-final-v1` →
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`
**Scope:** software-origin BTOR2 populations and Pono/IC3IA configurations
evaluated by this repository

This ledger is the authoritative human-readable boundary between claims that
survived the study, claims that were rejected, hypotheses that were never run,
and interpretations that the evidence does not support. It introduces no new
experiment and does not revise any frozen threshold.

## Status vocabulary

- **Supported:** the scoped claim is backed by the referenced formal or
  empirical evidence.
- **Rejected:** decisive evidence contradicts the claim on the evaluated
  population.
- **Threshold failed:** a measured effect exists, but it does not meet the
  preregistered success criterion.
- **Not run:** a prerequisite population gate failed; no utility conclusion is
  allowed.
- **Prohibited generalization:** the statement is broader than the evidence.

## Claims

| ID | Original claim or hypothesis | Final status | Decisive evidence | May it still be claimed? |
|---|---|---|---|---|
| C01 | Injecting LLM mutex hints as BTOR2 constraints produces valid safety proofs. | **Rejected** | Original-model C1/C2/C3 audit rejects all 32 independently checkable old proofs. | **No.** Those results are under-approximated assumption proofs, not proofs of the original models. |
| C02 | Signal-name boolean pairs describe true mutex invariants after BTOR2 compilation. | **Rejected** | `scan_hint_truth.py` finds a reachable `X && Y` state for 30/32 checked pairs; none of the 32 is established as a true invariant. | **No.** Source/RTL naming plausibility cannot be promoted to a bit-level invariant. |
| C03 | Arbitrary LLM formulas can be integrated soundly as IC3IA initial predicates. | **Supported** | `--initial-predicates` adds abstraction vocabulary/refinement without changing the concrete BTOR2 init, transition, constraints, or BAD properties; accepted safety results remain results on the original model. | **Yes, scoped to this implementation and its original-model proof path.** A false candidate may still increase runtime or memory. |
| C04 | The three apparent affine cases (`93.c`, `fib_37`, `fib_05`) demonstrate LLM-only proof capacity. | **Rejected** | The matched affine deterministic portfolio covers them. | **No.** They may be described only as predicate-seeding examples, not LLM-specific wins. |
| C05 | The nonlinear `fib_23` and `fib_30` proofs demonstrate LLM-only expressiveness. | **Rejected** | The deterministic quadratic oracle certifies the same cases; the final full21 LLM and deterministic solved sets are equal. | **No.** It remains valid that five independent captures generated certifiable candidates for both tasks. |
| C06 | LLM generation is reliable on the two frozen nonlinear development cases. | **Supported, but not unique** | Five independent captures per task yield 10/10 Houdini-certified candidate sets. Generation latency dominates proof-only certification cost. | **Yes, only as a reliability observation; not as marginal proof capacity or end-to-end advantage.** |
| C07 | Gate 2 adds a new LLM-only proof or a defensible compactness advantage on `up.btor2`. | **Rejected** | Cap-200 static seeding and the fixed low-complexity ranked baseline reproduce the proof; the ranked baseline is also faster in the recorded matched replay. | **No.** Gate 2's LLM-specific solved count is zero. |
| C08 | Source C representation produces unique certified solves over lifted and raw target views. | **Rejected on the Gate 3 population** | The paired source/lifted/raw gate records zero source-unique baseline-hard solve. | **No for the evaluated pilot.** This does not prove that source information is never useful in another independently designed study. |
| C09 | Phase conditioning generalizes to a meaningful natural proof niche. | **Threshold failed** | All-phase structural routing adds one independent baseline-hard proof; the preregistered threshold is three. | **Only the observed 1-case result may be reported.** It cannot be described as generalization. |
| C10 | LLM grammar routing beats a deterministic structural router. | **Rejected** | Structural routing covers the three-task union reached by all LLM representation arms; only 36/60 LLM routes are valid, and API latency removes a practical search-efficiency claim. | **No on the evaluated gate.** Candidate-count reduction alone is not proof utility. |
| C11 | The modular algebraic certificate kernel improves natural nonlinear cases. | **Not run** | The frozen 267-task population has zero v1-eligible natural primary task. Development controls and the 20-case rejection suite validate the kernel, not natural utility. | **Unknown.** Claim only development soundness and the population mismatch. |
| C12 | The six frozen nonlinear candidates are valid invariants that merely need helpers, deeper induction, or a proof graph. | **Rejected** | All six violate C1 in an initial state and exact Houdini removes each during initial filtering. | **No.** Repairing or replacing them after inspection would answer a different question. |
| C13 | Known-map certified invariant transport has useful proof-reuse utility on the current population. | **Not run** | Gate 5A0 finds 11 certified bases and six T1-applicable bases, below the frozen 12/8 requirements, and stops before generating transformed variants. | **Unknown.** No transport correctness, speedup, or LLM-mapping claim is permitted. |
| C14 | The evaluated program retains an LLM-specific solved-set or search-efficiency advantage after soundness repair and matched baselines. | **Rejected on the evaluated populations** | Full21, Gate 2, and Gate 3 all have zero defensible LLM-specific addition after matched deterministic comparison; later gates do not authorize a utility run. | **No.** The final scoped conclusion is zero demonstrated marginal advantage. |
| C15 | LLMs are never useful for formal verification or invariant generation. | **Prohibited generalization** | The study evaluates particular Pono pipelines, candidate languages, models, and populations; several later hypotheses are not run rather than falsified. | **No.** The evidence supports an evaluation-methodology conclusion, not a universal impossibility claim. |

## Claims that survive

The final program supports four positive, tightly scoped statements:

1. Predicate injection is a sound trust boundary for untrusted semantic
   proposals because it preserves proof on the original transition system.
2. Independent C1/C2/C3 certification, every-BAD handling, frozen replay, and
   explicit UNKNOWN semantics prevent plausible candidates from becoming
   unearned proof claims.
3. Matched deterministic expressiveness and end-to-end accounting materially
   change the empirical interpretation of LLM guidance.
4. Preregistered population and capability gates can stop an unproductive
   mechanism before post-hoc benchmark or threshold repair.

## Interpretations permanently disallowed for v1

- Reclassifying old constraint-injected UNSAT results as sound proofs.
- Calling any current full21 or Gate 2 solve LLM-only.
- Treating a BMC timeout, UNKNOWN, bounded-valid result, or malformed route as
  proof evidence.
- Counting development controls, synthetic transforms, repeated widths, or
  same-family variants as missing natural population.
- Rebuilding or changing the Gate 5 execution environment and retroactively
  replacing the frozen `population-insufficient` decision.
- Opening a `Gate 6` on `soundness-audit` to rescue LLM marginality.
- Presenting this project as a coverage-improvement result.

The machine-readable counterpart is
[`../artifacts/final_research_summary_v1.json`](../artifacts/final_research_summary_v1.json).
The full narrative is
[`final_research_narrative.md`](final_research_narrative.md).

## Post-boundary methodology addendum

Commit `536a1753f5bb8c0be475dd5f7700045f11ab9f14` records an Oracle-First
capability ledger and an external-artifact availability census. It is a
non-mechanism methodology addendum created after the frozen research boundary:
it adds no Pono experiment, transformed model, proof repair, or LLM/API call,
does not revise any claim above, and authorizes no continuation on this branch.
