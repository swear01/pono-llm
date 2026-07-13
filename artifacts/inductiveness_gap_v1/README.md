# Gate 5A — Inductiveness-Gap Decomposition

All six frozen Gate 4B0-v2 candidates are `FALSE_CANDIDATE`. Every candidate
already fails C1 at depth 0 and is removed by exact Houdini's initial-state
phase. Consequently k-induction, guard repair, and helper completion are implemented
but not applicable to the official cases: no proof structuring can repair a formula that excludes a reachable
initial state without changing its semantics.

Every one-step C2 predecessor full cube is reachable within the first bounded
check (which includes frame 0); support and BAD/support projections are also
reachable. Thus the C2 counterexamples are not merely unreachable CTIs.

The preregistered `>=4/6 FALSE_CANDIDATE` threshold selects
`GO_CERTIFIED_PROOF_SET_TRANSPORT`. Proof-graph completion and stronger
induction are not authorized. No LLM, new benchmark, new solver, kernel, proof
repair, or Pono C++ change was used.
