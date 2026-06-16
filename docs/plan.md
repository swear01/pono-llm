# Plan

**Status:** Stage 0 + Stage 2 implementation complete. Exhaustive benchmark scan done.

## Completed

- Stage 0: deterministic sym_pair injection + LLM ordering hints (gated on sym_pairs)
- Stage 2: gated on sym_pairs AND cti_count > 0; safety filter; previously_injected populated
- `_expr_canonical_hash()` in `btor2_reader.py`: structural expression matching for precise sym_pair detection
- Secondary BFS bug fixed (empty t_visited in secondary phase)
- `property_desc` truncation to 200 chars (prevents HTTP 413 on large circuits)
- `_is_safe_candidate()` safety filter: ref-ref comparisons only
- **Exhaustive HWMCC 2020/2024/2025 BV scan**: ~900 benchmarks, only fib_05 is Class-A

## Current State: fib_05 Only

fib_05 is the only Class-A benchmark across all HWMCC BV benchmarks. Constraints:
- ≤20 states required (IC3IA frame computation too slow otherwise)
- Structural sym_pair required (deterministic injection source)
- eq(A,B) must be the key missing invariant (current safety filter scope)

## Next Steps (strategic, pending decision)

1. **Name-pattern sym_pairs**: miter circuits have `impl_A.x` / `impl_B.x` — name similarity
   instead of expression hash could unlock 34 miter benchmarks
2. **Relaxed safety filter**: allow arithmetic invariants (`x+y==C`, `x<=C`) for GCD/counter class
3. **Alternative benchmark suites**: cache coherence, concurrent protocol benchmarks
4. **Accept current scope**: fib_05 as proof-of-concept; pivot to paper writing

## Do Not Do

- Restore per-CTI blocking clause code
- Restore `ic3_frame_v1.txt` or `ab_q*` scripts
- Use `rejected_initial` / `accept/API` as primary metrics
- Re-implement anything from Q2/Q3/Q4
