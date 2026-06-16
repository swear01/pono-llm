# Plan

**Status:** General method for software-origin benchmarks achieved (2026-06-17).

## Completed

### Phase Q5: Pre-processing Pipeline (new approach)
- `llm_worker/invariant_arith.py`: complete pre-processing pipeline
  - `detect_software_origin()`: C-style variable name detection + output-label extraction
  - `build_software_prompt()`: formula-rich prompt with actual transition expressions
  - `detect_symmetric_pairs()` + sym_pair injection (phase 1, no LLM needed)
  - LLM call with anti-division prompt rules
  - Multi-round verification: round-1 (fast scan), round-2 (helpers + ule fallback)
  - Retry loop (up to 2 LLM calls) when no arithmetic found and accumulator pattern detected
  - Probe gate: skip retry if current constraints already prove fast (prevents wasted retry on fib_05)
  - Deduplication of sound ASTs before injection
  - `inject_as_constraints()`: correct BTOR2 with sort-ID tracking (`Btor2Builder`)
  - `verify_invariant()`: IC3IA as oracle for soundness checking
- `llm_worker/btor2_reader.py`:
  - `_decode_expr()`: recursive BTOR2 → human-readable formula decoder
  - Output-label extraction for unnamed states (fib_30/fib_37 pattern)
  - Improved `build_transition_sketch()` showing actual formulas
- `scripts/preprocess_sw.py`: standalone CLI pre-processor

### Phase Q5: Earlier (reactive sidecar)
- Stage 0: deterministic sym_pair injection + LLM ordering hints (gated on sym_pairs)
- Stage 2: gated on sym_pairs AND cti_count > 0; safety filter
- `_expr_canonical_hash()`: structural expression matching for sym_pairs
- Exhaustive HWMCC 2020/2024/2025 BV scan: ~900 benchmarks
- Secondary BFS bug fix; `property_desc` truncation; safety filter

## Current Results: All 6 Software-Origin Benchmarks

All 6 HWMCC software-origin benchmarks proved UNSAT:

| Benchmark | Total time | Key invariants injected |
|-----------|-----------|------------------------|
| 93.c      | ~16s      | `x+y==3*i`, `i<=n` |
| 77.c      | ~9s       | `x>=i`, `y>=450-i` |
| fib_05    | ~12s      | `eq(x,y)` (sym_pair) |
| fib_23    | ~28s      | `i<=n`, `2*sum<=i*(i-1)` |
| fib_30    | ~29s      | `i<=n`, `2*c<=i*(i-1)` |
| fib_37    | ~8s       | `x<=n`, `m<=x` |

pono IC3IA on constrained BTOR2: 0.02–0.2s (down from 78–∞s baseline).

## Next Steps

1. **Scan for more benchmarks**: sv-benchmarks, HWMCC 2020, custom circuits
2. **Parallel verification**: run multiple `verify_invariant` calls concurrently to reduce wall time
3. **Paper/report**: document the method, results, and comparison with baseline

## Do Not Do

- Restore per-CTI blocking clause code (Q2/Q3/Q4)
- Restore `ic3_frame_v1.txt` or `ab_q*` scripts
- Use rejected_initial / accept/API as primary metrics
- Re-implement anything from Q2/Q3/Q4
- Use reactive sidecar predicate injection for arithmetic invariants (proven not to work)
