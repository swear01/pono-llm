# IC3IA Nondeterminism Audit

## Random Seed Control

**Flag**: `--random-seed <N>` (default: 0 = no shuffle)

**Usage**: Shuffles fresh predicates during IC3IA refinement at
`engines/ic3ia.cpp:356-360`. Only applied when `random_seed_ > 0`.

**Limitation**: Does not control ALL sources of nondeterminism:

1. `std::unordered_map`/`std::unordered_set` iteration order — used for
   `lbl2pred_`, `predlbls_`, `predset_`, `labels_`, `frame_labels_`.
   Iteration order is nondeterministic and varies between runs even
   with the same seed.

2. SMT solver nondeterminism: The solver's internal decision heuristics
   may produce different search paths between runs.

3. Frame clause generation: `constrain_frame()` uses subsumption checks
   that iterate over unordered collections.

4. `process_llm_candidates()` is nondeterministic in timing (poll-based),
   but this is irrelevant when LLM is not active.

## Verdict

**seed_control_available** — the `--random-seed` flag controls predicate
shuffle order, which is ONE source of nondeterminism. But unordered
data structures and solver nondeterminism remain uncontrolled.

## Practical Consequence

Even with `--random-seed=42`, artifact counts will vary between runs.
The seed reduces but does not eliminate variance. Repeated runs are
still necessary for reliable comparisons.
