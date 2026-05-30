# Context-Unlock Case Study: Bootstrap Predicates for CPAchecker CEGAR

## Benchmark/Config

- CPAchecker CEGAR with LLM bootstrap predicate injection
- 8 bootstrap predicates provided by LLM

## Before Bootstrap

| Metric | Value |
|---|---|
| Status | ZERO_CONTEXT_TIMEOUT |
| Refinements | 0 |
| Context dumps | 0 |
| Usable CEGAR context | No |

CPAchecker could not produce a single refinement iteration. No spurious traces,
no interpolants, no candidate predicates. The CEGAR loop was dead at entry
due to lack of meaningful abstraction predicates.

## After Bootstrap (8 predicates injected)

| Metric | Value |
|---|---|
| Status | **context_unlocked** |
| Refinements | 39 |
| Context dumps | 3 |
| Usable CEGAR context | **Yes** |

The bootstrap predicates provided enough abstraction structure for CEGAR to
begin producing spurious traces, interpolants, and candidate predicates.
The zero-signal timeout converted to a signal-rich CEGAR run.

## B5-MR (Repair Attempt)

| Metric | Value |
|---|---|
| Attempted | Yes |
| New valid repair predicates | 0 |
| Solved | **No** |

After context was unlocked, B5-MR repair was attempted using the 3 context
dumps (spurious traces, interpolants, candidate fates). However, no new
valid repair predicates were produced. The benchmark remains unsolved.

## Interpretation

- **Bootstrap predicates converted zero-context timeout into a producing CEGAR run.**
- CEGAR now refines, produces traces and interpolants — the mechanism works.
- Repair step (B5-MR) did not yet find new valid predicates.
- The path from zero-context to solved requires more iterations or different
  repair strategies.

## Safe Claim

```text
Bootstrap LLM predicates converted a zero-context timeout into
a context-producing CEGAR run.
```

## Non-Claims

- Not solved (UNKNOWN→TRUE not achieved)
- Not bootstrap_rescue completed
- No runtime speedup claim
