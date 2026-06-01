# Low-Cost Injection Proxy Plan

## Problem

Pono p040 k=5 takes 5-8 minutes per run. Repeated runs for statistical
confidence (5-10 per configuration) would take 1-2 hours. This makes
iterative experimentation impractical.

## Options

| Option | Time per run | Tradeoff |
|---|---|---|
| k=3 instead of k=5 | ~2min | Less IC3IA exploration, fewer CTIs |
| Smaller benchmark (arbitrated_top if available) | ~30s | Different design, may not generalize |
| Disable dump (no JSONL output) | ~10% faster | Can't measure artifacts |
| Count only init predicates | Instant | Only measures initial state, not search |
| Offline replay over dumped traces | Instant | Doesn't measure actual convergence |

## Recommended: k=3 with Dump

Run at k=3:
- Still exercises IC3IA refinement
- 5-10 reps per configuration in <30 minutes
- Can measure CTI/frame trends at lower k

```bash
python3 llm_worker/run_injection_experiment.py --k 3 --seed 42 --reps 5
```

Once a stable effect is established at k=3, validate at k=5 with fewer
repetitions.

## Alternative: Fixed Seed, Multi-Seed

If effect is truly seed-dependent, run 3 seeds × 1 rep instead of 1 seed × 3 reps:
- Covers seed space
- Same total runtime
- More informative about whether effect is seed-stable
