# Quokka Candidate-Purity Audit Plan

**Updated:** 2026-07-14
**Branch:** `quokka-soundness-audit`
**Status:** complete; systematic violation confirmed and frozen mitigation control passed

## Boundary

This is an independent implementation-level soundness audit of
`Anjiang-Wei/Quokka@60301cb...`. It is not Pono Gate 6 and is not Cross-Tool X1.
The old Pono evidence/tag and the Cross-Tool X0 STOP remain unchanged.

## Ordered work

1. **Q0 — Frozen source/input contract:** pin the public commit, driver and
   verifier hashes, three unsafe source templates, seven candidates, and
   decisions before verifier execution.
2. **Q1 — Exact public-path replay:** invoke the pinned Quokka extraction,
   insertion, and aggregation functions, and execute both generated programs
   with the pinned UAutomizer.
3. **Q2 — Independent decision validation:** recompute every parser, verifier,
   aggregate, and threshold decision from retained raw evidence.
4. **Q3 — Fail-closed mitigation control:** test a conservative pure-expression
   recognizer against the same frozen matrix and malformed negative suite.
5. **Q4 — Closure:** document only the verified outcome, limitations, hashes,
   and reproduction command.

No LLM/API call, historical-output reconstruction, benchmark expansion,
prompt experiment, or utility claim is part of this plan.

## Active contract

The complete protocol is
[`quokka_soundness_preregistration.md`](quokka_soundness_preregistration.md),
and the machine-readable input is
[`../scripts/quokka_soundness_inputs_v1.json`](../scripts/quokka_soundness_inputs_v1.json).

## Result

All nine frozen side-effect rows were false-safe under the pinned public path,
covering three mechanisms and three program templates. Independent validation
recomputed every decisive aggregate. The conservative purity recognizer passed
the frozen controls. See
[`quokka_soundness_results.md`](quokka_soundness_results.md) and
`artifacts/quokka_soundness_v1/`. The audit is closed; benchmark expansion,
LLM testing, and utility claims are not authorized by this result.
