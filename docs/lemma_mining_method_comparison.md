# Lemma Mining Method Comparison

## Methods

| # | Method | Verified | Best Impact | LLM Calls | Mechanical | Notes |
|---|---:|---|---:|---|---|---|
| 1 | Original closed-loop | 1 | low | 2+ | No | First useful lemma ever |
| 2 | Impact-guided LLM | 3 | low | 1 | No | 1 round, higher yield |
| 3 | Clause-family lifting | 26 | low | 0 | **Yes** | 87% pass rate, fully mechanical |

## Coverage Detail

| Method | Top Lemma | Family Coverage | Clause Coverage |
|---|---|---|---|
| Closed-loop | `state2002=>state790` | 0 | 0 |
| Impact-guided | `state15=>state886` | 0 | 0 |
| Lifting | `state15∧state469⇒state471` | 2 | 2 |

All three methods produce verified but low-impact lemmas on the qspiflash p040 benchmark.

## Why Low Impact?

1. **Original closed-loop**: produced a genuine design invariant, but the variable pair has almost no frame clause relevance.

2. **Impact-guided LLM**: selected variables with high frame clause co-occurrence, but pairwise implications don't subsume multi-literal OR clauses.

3. **Clause-family lifting**: mechanically converts every OR clause into equivalent implications. Produces 26 verified lemmas (87% pass rate), but each lemma explains only its source clause — no clause-family compression.

## Key Insight

```text
IC3IA frame clauses encode many intermediate proof steps.
Each can be mechanically lifted into a globally inductive lemma.
But these lemmas are proof-local artifacts — they don't generalize
across clause families or compress the proof.
```

The 87% verification rate for lifted lemmas shows that the lifting is **correct but not compressive**. The true lemma that IC3IA is trying to prove (state15 != 1) is guarded by many different antecedent combinations. Each combination produces a valid but narrow lemma.

## Next Direction

Family-level generalization: group the 26 verified lemmas by shared structure and derive broader lemmas that cover multiple clauses. This requires either:
- Script-based grouping by shared antecedent patterns
- LLM-based generalization from example lemmas
- Or both
