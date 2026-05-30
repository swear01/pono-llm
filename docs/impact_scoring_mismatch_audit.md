# Impact Scoring Mismatch Audit

## Confirmed

Task 86 used same-clause co-occurrence correctly — the selected pairs
(state15+state886, etc.) DO co-occur in individual frame clauses.

**The mismatch is NOT in the selection metric.** It's in the synthesis
strategy: a pairwise implication between co-occurring variables does
not automatically subsume the clause containing them.

## Evidence

- 1103 same-clause pairs vs 19,483 same-frame pairs
- Top 20 pairs from same-clause are the exact clusters Task 84 selected
- Same-frame pairs inflated by 18× — all clauses in same frame share variables
- The selector already uses same-clause, not same-frame, co-occurrence ✓

## Root Cause

Frame clauses are multi-literal OR structures:
```
(or (not (= state15 #b0)) (not (= state17 #b0)) (= state886 #b0))
```

A lemma `state15=0 => state886=0` doesn't subsume this clause because:
- The lemma says: IF state15=0 THEN state886=0
- The clause says: (state15≠0) OR (state17≠0) OR (state886=0)
- These are logically different — they don't imply each other

## Clause Structure Discovery

| Template | Count | Key Variables |
|---|---|---|
| 3-literal OR | 603 | state15 (230×), state17 (188×) |
| 2-literal OR (2 vars) | 283 | state17 (26×), state552 (24×) |
| 4-literal OR | 88 | state15, state17 |
| 5-literal OR | 54 | state15, state17 |
| Single-literal | 19 | various |

state15 and state17 appear in 230+188 clauses as **negated** literals
(`(not (= state15 #b0))`). They are the foundational constraints, with
additional literals added to strengthen clauses.

## Recommendation

Target single-variable synthesis around state15 and state17:
- What constraint does `state15!=0` represent?
- Can a lemma about state15 explain why it's the most used variable?
- Multi-literal clause families may be compressible by finding a general
  relation between the "core" variables (state15, state17) and the
  "satellite" variables added in multi-literal clauses.
