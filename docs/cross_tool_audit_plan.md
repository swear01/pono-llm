# Cross-Tool Audit Plan

**Updated:** 2026-07-14
**Branch:** `cross-tool-audit`
**Status:** independent Gate X0 preregistered; artifact census not yet executed

## Boundary

This branch begins from the archival packaging commit `8e5e050`, but it does
not extend the closed `soundness-audit` hypothesis tree. The prior frozen tag
continues to point to `6fdb7cf`. No result on this branch may be used to amend
that release.

## Ordered gates

1. **X0 — Public artifact availability:** determine whether at least two
   systems across two verification settings are fully replayable from frozen
   public bytes.
2. **X1 — Soundness-boundary replay:** independently execute frozen outputs
   through the original verifier and classify the trust boundary.
3. **X2 — Matched deterministic baseline:** give non-LLM methods the same
   output language, verifier feedback, and budget.
4. **X3 — End-to-end marginal value:** compare solved sets, error rates,
   retries, wall time, tokens, and cost.

Only a preceding GO authorizes the next gate. No gate may change the systems,
population, field contract, or threshold after observing its result.

## Current work

- freeze the five-candidate catalog;
- implement strict retrieval/census schemas and validators;
- inspect public releases without executing models or proof systems;
- commit the X0 decision before any verifier build or replay.

## Explicit non-goals

- reopening Pono Gate 6;
- using old Pono successes or failures as the new population;
- reproducing a paper by generating fresh LLM outputs;
- contacting authors and then backfilling the frozen X0 artifact;
- replacing a system whose public artifact is incomplete;
- making soundness or utility claims from artifact absence.
