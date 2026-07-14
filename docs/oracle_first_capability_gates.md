# Oracle-First Capability Gates

## Status and scope

This document is a **frozen post-boundary methodology addendum**, not the next
research project on `soundness-audit`. It does not alter the final claim ledger
or the `soundness-audit-final-v1` boundary and authorizes no further execution.

It freezes the Oracle-First Capability Auditing study. It does not
authorize a new verifier mechanism, candidate grammar, repair loop, transport
mapper, benchmark hunt, or LLM call. Gate 3, Gate 4B0-v2, Gate 5A, and the
certified-transport population decision remain closed.

The unit under audit is the tuple `(population, representation, artifact,
consumer, backstop, resource model)`, not an LLM output in isolation. A stage
may pass only from exact, fail-closed evidence with its threshold frozen before
the measured result. UNKNOWN, timeout, unsupported input, missing provenance,
and unavailable evidence are not proofs.

## Ordered stages

| Stage | Question |
|---|---|
| G0 Population sufficiency | Is there a natural, independent, controlled population large enough for the claim? |
| G1 Representation capacity | Can the frozen grammar and binding preserve the required locations, phases, widths, and variables? |
| G2 Semantic candidate validity | Does `Init => H` hold, and are bounded reachable-state checks consistent with it? |
| G3 Consumer capacity | Does a correct reference artifact create the preregistered target delta in the consumer? |
| G4 Proof sufficiency | Does the accepted artifact imply the target property? |
| G5 Runtime utility | Under matched resources, does the integration improve solves or cost without losses or wrong answers? |
| G6 LLM marginality | After G0--G5 pass, does the LLM beat budget-matched deterministic alternatives? |

The exclusive primary failure classes are `NO_POPULATION`,
`UNSUPPORTED_REPRESENTATION`, `PARSE_OR_BINDING_FAILURE`, `INITIAL_FALSE`,
`REACHABLE_COUNTEREXAMPLE`, `NON_INDUCTIVE`, `CONSUMER_NO_CAPACITY`,
`PROPERTY_INSUFFICIENT`, `NEGATIVE_RUNTIME_UTILITY`,
`NO_LLM_MARGINAL_VALUE`, and `PASS`. Classification stops at the earliest
demonstrated stage; it must not infer a later cause from an earlier failure.

## Immutable ledger contract

`scripts/capability_gate_catalog_v1.json` is the frozen input. The builder
checks every evidence byte against its declared SHA-256 and emits
`artifacts/capability_gate_ledger_v1/ledger.json`. Each study records its frozen
hypothesis and threshold, population and result hashes, code commit, controls,
soundness boundary, decision, exclusive failure class, chronology status, and
forbidden next actions. Evidence is either `tracked-clean` or explicitly
`working-tree-only`; the latter cannot support a clean-checkout reproduction
claim. The validator rejects duplicate keys, unknown schemas/classes/stages,
bad hashes, inconsistent decisions, and ledger self-hash mismatches.

The ledger is an audit index, not a substitute for the referenced reports.
Positive controls prevent an always-STOP methodology: CPAchecker ReachSafety
predicate and termination-ranking paths are retained alongside negative
consumer, semantic, population, representation, marginality, and runtime
results. Conclusive verification evidence must retain zero wrong answers.

## Prospective external replication freeze

The external target is Quokka/InvBench, selected before artifact inspection
because its published protocol separates verifier-backed invariant correctness
from acceleration. The prospective question is whether the stage ordering can
locate G2, G3, G4, or G5 failures before observing final utility. Eligibility
requires, from one public immutable release: programs, exact candidate
predicates, insertion locations, expected verifier outcomes, verifier/version
configuration, per-instance timing data, stable identifiers, and content
hashes. No replacement corpus may be selected after inspecting outcomes.

The artifact-availability census is limited to public release metadata and
bytes; it does not execute candidates. The preregistered decision is GO only if
all eligibility fields are public and independently reconstructible. Otherwise
it is `STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE`, with the exact missing fields and
retrieval failures recorded. A STOP is an external-replication blocker, not a
claim about Quokka correctness or utility.

## Explicit exclusions

- no CPAchecker or Pono proof-engine changes;
- no new LLM capture or repair;
- no reopening invalid routes, Gate 3.1, algebraic-kernel expansion, proof
  graphs, stronger induction, or transport mapping;
- no post-hoc benchmark replacement;
- no claim beyond the frozen producer, representation, consumer, and
  population represented by each row.
