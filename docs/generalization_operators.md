> **ACTIVE for v1 (2026-06-03)** — `operator` field values in `ic3_frame_response`.  
> Spec: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

# Generalization Operators

Each operator transforms a proof artifact into a candidate lemma.

| # | Operator | Input | Output | Scriptable? |
|---|---|---|---|---|
| 1 | clause_lifting | Frame OR clause | Implication | **Yes** |
| 2 | literal_deletion | Implication with 2+ antecedents | Weaker implication | **Yes** |
| 3 | guard_strengthening | Failed implication + CE | Guarded implication | Needs CE data |
| 4 | guard_weakening | Overstrong implication | Weaker guard | **Yes** |
| 5 | family_compression | Multiple same-consequent lemmas | Generalized antecedent | Needs LLM |
| 6 | transition_causal | Frame clause + transition cone | Causal guard | Needs transition data |
| 7 | mutex_generalization | Multiple mutex pairs | N-ary mutex | Needs LLM |
| 8 | range_abstraction | Equality exclusions | Allowed-set / range | **Yes** |
| 9 | repair | Failed candidate + CE | Repaired lemma | Needs CE data |

## 1. Clause Lifting

```
(A OR B OR C) → (NOT A AND NOT B) ⇒ C
```
Already proven: 26/30 verified (87%). Fully scriptable.

## 2. Literal Deletion

```
(A AND B AND C) ⇒ D → (A AND B) ⇒ D
```
Weaker form. Must be solver-checked (may break induction).

## 3. Guard Strengthening

```
A ⇒ D fails one-step (CE: A=true, D=false, B=false)
→ (A AND B) ⇒ D
```
Requires counterexample model data. LLM or scripted.

## 4. Guard Weakening

Like #2 but intentional: drop redundant or tautological guards.

## 5. Family Compression

```
(A AND B1) ⇒ D
(A AND B2) ⇒ D
(A AND B3) ⇒ D
→ (A AND group_condition(B*)) ⇒ D
```
Needs LLM to propose a meaningful group condition.

## 6. Transition Causal

```
Frame clause (NOT X) OR (NOT Y) OR Z
Transition: X depends on stateA, inputB
→ (stateA=V AND inputB=W) ⇒ Z
```

## 7-9

Similar — see full definitions in source code.
