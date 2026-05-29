# Reachability-Guided Failure Analysis

## Core Insight

The reachable-sample filter applied to all 5 candidate sets reveals:

### 1. How many failed candidates excluded known reachable samples?

- **Original 30**: 20/30 (67%)
- **Solver shortlist**: 4/5 (80%)
- **Resynthesis**: 4/4 (100% of non-rejected)
- **Repair v1**: 2/6 (33%)
- **Repair v2**: 0/2 (v2 prompt constraints prevented this)

Repair v2 is the only set where NO candidate excludes known samples — exactly
because the prompt explicitly instructed the LLM not to.

### 2. Were repair/resynthesis failures mostly due to excluding known samples?

**Yes** — for resynthesis, this is the dominant failure mode. All 4 non-rejected
resynthesis candidates directly contradicted counterexample values. The LLM
proposed lemmas that said "state1536 can never be 15" when the CE showed
state1536=15 IS reachable.

For repair v1, 2 violations were from init-state mismatch (reversed implication
fails at init) and parse failure (input variable in lemma).

### 3. Do nontriviality gate and reachable filter complement each other?

**Yes.** They catch different failure classes:

| Gate | Catches | Example |
|---|---|---|
| Nontriviality | Vacuous truths | `(<= state1558 1)` on 1-bit var |
| Reachable filter | False invariants | `(<= state1536 14)` when sample has 15 |
| Solver | Non-inductive lemmas | repair-v2 lemmas: consistent with samples but not inductive |

The two gates together eliminate two major categories of bad candidates BEFORE
the expensive solver check.

### 4. Any candidates consistent with all samples but still fail induction?

**Yes** — both repair v2 candidates:
- `state1536=10 => state790=1` — all samples pass, but one-step SAT
- `state2002=1 => state1536!=0` — all samples pass, but one-step SAT

These are "plausible but not inductive" — the reachable samples aren't
exhaustive, and there exists some transition not covered by the 9 samples
that violates the lemma.

### 5. What does this imply for future LLM prompting?

The three-gate pipeline provides a clear architecture:

```
LLM generates candidates
  ↓
Gate 1: Reachable filter (fast, catches ~80% of bad candidates)
  ↓
Gate 2: Nontriviality filter (fast, catches tautologies)
  ↓
Gate 3: Init check (light SMT, catches init violations)
  ↓
Gate 4: One-step check (full SMT, catches non-inductive)
  ↓
Gate 5: Induction check (full SMT, most expensive)
  ↓
Accept
```

For LLM prompting, the key insight is: **include reachable samples as positive
constraints.** Instead of only showing counterexamples (what fails), also show
reachable samples (what is known to be possible). This prevents the LLM from
"blocking" CE values by asserting they're impossible.

## Three-Layer Defense

| Layer | Type | Cost | Rejects |
|---|---|---|---|
| Reachable filter | Concrete evaluation | Near-zero | False invariants (excludes known reachable) |
| Nontriviality gate | Bitwidth analysis | Near-zero | Tautologies (<= max_val, >= 0) |
| Solver checks | SMT solver | High | Non-inductive candidates |
