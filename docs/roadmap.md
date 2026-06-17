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

## Benchmark Exploration (2026-06-17) — Ceiling Confirmed

Exhaustive scan of all HWMCC 2020/2024/2025 benchmarks for extension opportunities:

- **CBMC loops-crafted/eca-rers** (26 circuits): input-driven transitions — approach fundamentally doesn't apply
- **sw_ball2004_2** (Ball/SLAM): Location-bit circuit with computable transitions. 3 location-conditioned invariants (`implies(L2,X<Y)`, `implies(L11,A==Y)`, `implies(L12,A<B)`) verified individually. Key safety invariant `implies(L3,X<Z)` needs multi-step reasoning IC3IA-as-oracle can't provide. **New: `implies` AST form added** to `ast_to_btor2`.
- **Wolf Verilog** (picorv32, zipcpu, dblclockfft, qspiflash, 100+ circuits): Hardware designs, short signal names but protocol-based invariants, LLM can't reason about them
- **HLS bv circuits** (hl_arr_access_128_bv): 256+ array state elements, invariant involves memory contents
- **goel/industry**: All Verilog FSMs, 0 software-origin circuits
- **HWMCC 2020 goel/opensource additional**: miim, vcegar_itc99_b13, vis_arrays_am2910, vis_arrays_bpbs — all FSM/protocol, non-arithmetic

**Result**: 8 proved benchmarks is the natural ceiling within existing HWMCC sets.

## Architecture Extensions (2026-06-17)

### Portfolio Fast-Path Engine (A1) — DONE
- `try_fast_engines()`: ind + interp parallel, 5s cap before LLM
- sw_ball2004_2 (1.2s ind), vcegar_QF_BV_ar (1.0s ind) added to covered set
- `preprocess_software_benchmark()` returns 3-tuple `(path, n_injected, fast_engine)`

### BAD Condition in LLM Prompt (A2/A3) — DONE
- `build_bad_condition_text()`: decodes bad_lineno, strips and(1,.) + not(not(.)) wrappers
- Examples: fib_23 shows `!((i < n) || (sum > 0))`, 93.c shows `((i >= n) && (n*3 != x+y))`
- LLM now knows exactly what condition to disprove

### Simulation Trace in LLM Prompt (A4) — DONE
- `simulate_circuit_trajectory()` + `_eval_node()`: forward-simulate 9 steps, all inputs=0
- fib_23 trace reveals sum=0,0,1,3,6,10,15,21,28 (triangular numbers — invariant obvious)
- 93.c trace reveals x=2i, y=i at each step (x+y=3*i invariant obvious)
- 93.c now generates correct invariant consistently (6/6 LLM samples agree)
- 77.c (constant with selector=0): all_same detection skips trace automatically

## Backlog

- **Paper/report**: write up method, results, comparison with baseline for publication
- **HLS benchmark via toolchain**: Vivado HLS from C source → BTOR2; would require external toolchain
- **Location-conditioned invariant chain**: For sw_ball2004_2-type circuits; requires multi-step verification strategy beyond IC3IA oracle
- **Chain-of-thought prompting** (A5): 3-step CoT prompt: decompose goal → derive conditions → generate invariants
- **IC3 Generalization Hook** (B2): Hook LLM into IC3's generalization step (requires C++ pono changes)
- **SyGuS template synthesis** (B4): LLM suggests invariant shape, CVC5 fills coefficients
