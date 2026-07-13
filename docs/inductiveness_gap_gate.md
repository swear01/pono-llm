# Gate 5A — Inductiveness-Gap Decomposition

**Frozen:** 2026-07-13
**Status:** complete — **GO certified proof-set transport**

## Official Result

All six cases are `FALSE_CANDIDATE`. Each selected equality is false in an
initial state (`first_reachable_violation_depth = 0`), C1 is SAT, and exact
Houdini removes the sole selected candidate during initial-state filtering.
Thus none is eligible for k-induction or the micro-repair oracle. The result is
stronger and more precise than the earlier C2 observation: these formulas are
not reachable invariants, regardless of induction depth or missing support.

Every C2 CTI full-state cube is reachable within the first bounded check, which
includes frame 0; candidate-support and BAD/support projections are reachable
as well. The C2 counterexamples are therefore not merely unreachable CTIs.

Classification counts are `FALSE_CANDIDATE: 6`. The preregistered threshold of
at least 4/6 therefore selects **GO_CERTIFIED_PROOF_SET_TRANSPORT**. Proof-graph
completion and stronger-induction integration are not authorized. Canonical
evidence is `artifacts/inductiveness_gap_v1/`; summary SHA-256 is
`a7f7b45d3709e3911dd0f031ef4d21dcf9d435fee13b5bb4452f4bb921f76319`
and recursive integrity SHA-256 is
`33047ef33c92d367b841975ecc5d103a0f964707d55203d7b9b877361be01732`.

## Question and Scope

Gate 4B0-v2 established only that six frozen conjunctions are not 1-inductive.
Gate 5A classifies why, before proof-graph completion, stronger induction, or
transport. It uses exactly the six hash-bound v2 cases. No LLM, new benchmark,
new solver, PolySAT rebuild, kernel work, prompt repair, or Pono C++ change is
allowed.

## Exact Semantics

All queries reuse `candidate_cert_check.py` and `cert_check.py`. Transition
unrolling creates fresh state and input variables at every frame and asserts
original constraints at every frame. UNKNOWN, timeout, malformed input, or
unsupported is never evidence.

For every conjunct `h_i`, bounded correctness is checked at exact depths
`1,2,4,8,16`:

```text
Init(X0) && T(X0,X1) && ... && T(X[d-1],Xd) && !h_i(Xd).
```

Record the first SAT depth, maximum UNSAT depth, violated candidate IDs, and a
SHA-256 of a canonical projected model. UNSAT through 16 means only
`bounded-valid-16`, never invariant.

At depth one check both:

```text
H(X)   && T && !h_i(X')
h_i(X) && T && !h_i(X')
```

Run exact Houdini to a fixpoint and record initial count, C1 removals, C2
removals, survivors, survivor C2, and survivor C3.

For bounded-valid candidate sets, test k-induction for `k=2,3,4`. Base cases
are all frames `<k`; the step assumes `H` for `k` consecutive frames and checks
`!H` at the successor. Property implication is checked separately. A case is
`K_INDUCTIVE` only when base, step, and property are all UNSAT.

For every one-step CTI predecessor, test exact full-state reachability and two
explicit projections at depths `1,2,4,8,16`: candidate-support variables and
the syntactic BAD/violated-candidate cone. Full and projected verdicts remain
separate; projected SAT never proves the full CTI reachable.

## Fixed Micro-Repair Oracle

Only bounded-valid cases whose full CTI is not reached by depth 16 are eligible.
The immutable grammar is:

1. existing candidate literals and their negations;
2. one existing one-bit control-state equality to 0 or 1;
3. one implication `guard => h_i`;
4. already emitted, independently verified Pono/IC3 clauses if present in the
   frozen inputs;
5. at most two added helper conjuncts.

Search is deterministic lexical order, at most 30 seconds per case. It cannot
inspect a model and manufacture a new polynomial, extend degree, call an LLM,
or repair syntax. Every accepted repair must pass exact original-model C1/C2/C3.

## Exclusive Primary Taxonomy

Apply this precedence so each case has exactly one primary class:

1. `FALSE_CANDIDATE`: a bounded reachable trace violates a candidate;
2. `SELECTION`: the exact Houdini subset proves C1/C2/C3;
3. `K_INDUCTIVE`: some `k<=4` passes base, step, and property;
4. `GUARD_STRUCTURE`: one fixed-grammar guard implication yields C1/C2/C3;
5. `MISSING_HELPER`: at most two allowed helpers yield C1/C2/C3;
6. `PROPERTY_INSUFFICIENT`: an inductive nonempty set fails C3;
7. `UNRESOLVED`.

Secondary diagnostics may be reported but cannot change the exclusive class.

## Decisions

**GO proof-graph completion** only if at least 3/6 cases, from at least two
family labels, are `GUARD_STRUCTURE` or `MISSING_HELPER`, each uses at most two
helpers, search is at most 30 seconds, exact C1/C2/C3 pass, and false-safe is
zero.

**GO stronger-induction consumer** instead if at least 3/6 are `K_INDUCTIVE`.

**GO certified proof-set transport** if at least 4/6 are
`FALSE_CANDIDATE`, or at least 5/6 are `UNRESOLVED`. The separately frozen
transport protocol and its 90%/three-transform/5x thresholds remain unchanged.

Otherwise **STOP algorithm expansion**. Do not open another mechanism gate.

Any false-safe, malformed accepted artifact, hash mismatch, or UNKNOWN treated
as proof stops Gate 5A for soundness audit. The canonical output directory is
`artifacts/inductiveness_gap_v1/` with recursive integrity hashes.
