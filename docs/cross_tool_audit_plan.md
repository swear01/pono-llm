# Cross-Tool Audit Plan

**Updated:** 2026-07-14
**Branch:** `cross-tool-audit`
**Status:** stopped at Gate X0; X1--X3 unauthorized

## Boundary

This branch begins from the archival packaging commit `8e5e050`, but it does
not extend the closed `soundness-audit` hypothesis tree. The prior frozen tag
continues to point to `6fdb7cf`. No result on this branch may be used to amend
that release.

## Ordered gates

1. **X0 — Public artifact availability: STOP.** No frozen candidate satisfied
   all fourteen required fields, so the required two-candidate/two-setting
   population does not exist under the preregistered contract.
2. **X1 — Soundness-boundary replay: not authorized.** No verifier was built or
   executed.
3. **X2 — Matched deterministic baseline: not authorized.** No baseline or
   model call was executed.
4. **X3 — End-to-end marginal value: not authorized.** No utility claim was
   tested.

Only a preceding GO authorizes the next gate. No gate may change the systems,
population, field contract, or threshold after observing its result.

## Completed evidence

- The five-candidate catalog and repository retrieval boundary were frozen
  before repository-file inspection.
- Six external repositories were resolved to immutable commits and inventoried.
- Every candidate was classified against all fourteen required fields.
- The canonical decision is `STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS` with zero
  fully eligible candidate, zero verifier execution, and zero new LLM/provider
  API call.
- The strict, recursively hash-bound artifact is
  [`../artifacts/cross_tool_x0_v1/`](../artifacts/cross_tool_x0_v1/).
- The complete interpretation and reproduction contract is
  [`cross_tool_x0_results.md`](cross_tool_x0_results.md).

## Decision boundary

The X0 STOP is an artifact-sufficiency result only. It does not establish that
any candidate system is unsound or ineffective. Later releases, author-provided
files, fresh generation, or a weaker field contract may be studied only under
a new preregistration; they cannot retroactively authorize X1 here.

## Explicit non-goals

- reopening Pono Gate 6;
- using old Pono successes or failures as the new population;
- reproducing a paper by generating fresh LLM outputs;
- contacting authors and then backfilling the frozen X0 artifact;
- replacing a system whose public artifact is incomplete;
- making soundness or utility claims from artifact absence.
