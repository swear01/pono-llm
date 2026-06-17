# Roadmap

## Done (2026-06-17)

### Pre-processing Pipeline (Q5)
- **General method achieved**: 8 HWMCC software-origin benchmarks proved UNSAT
- **BTOR2 constraint injection**: IC3IA on constrained circuit proves in <0.3s (vs 78–∞s baseline)
- **Sym_pair injection (Phase 1)**: fib_05 eq(x,y) injected deterministically before LLM
- **Formula-rich transition sketch**: `_decode_expr()` renders `c' = ((i >= n) ? c : (c + i))` — LLM needs actual formulas to infer triangular number invariants
- **Output-label extraction**: unnamed states in fib_30/fib_37 detected via `output` BTOR2 statements
- **Multi-round parallel verification**: round-1 (4 workers, 4s) + round-2 with helpers (4 workers, 10s)
- **ule fallback for eq**: when `eq(A,B)` times out, auto-add `ule(A,B)` to round-2
- **Retry loop with probe gate**: no arithmetic found + accumulator pattern → retry LLM with triangular hint; 3s probe prevents wasted retry
- **Deduplication**: sound ASTs deduplicated by canonical JSON key
- **Anti-division prompt rule**: LLM now outputs `2*sum==i*(i-1)` not `sum==i*(i-1)/2`
- **Const-bound filter**: rejects `n==40`, `i<=40` (adds IC3IA predicate dimensions, slows proof)
- **Benchmark scan**: HWMCC 2024/2025 (6 found), HWMCC 2020 (2 new), sv-benchmarks (0)
- **LLM stdout fix**: all diagnostic prints to stderr so `$(python3 ...)` capture is clean

### Previous (Reactive Sidecar — Dead End)
- Stage 0/2 reactive sidecar: sym_pair injection + LLM ordering hints
- fib_05: only Class-A benchmark (0 CEGAR rounds with deterministic sym_pair)
- Exhaustive HWMCC scan: ~900 BV benchmarks, only fib_05 worked reactively

## Backlog

- **Paper/report**: write up method, results, comparison with baseline for publication
- **More HLS circuits**: Vivado/Intel HLS output likely has C-style variable names; wider benchmark pool
- **Stage 2 full trigger logic**: T1/T2/T3 monitors — low priority given pre-processing wins
