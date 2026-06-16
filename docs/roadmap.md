# Roadmap

## Recently Done

- **General method achieved (2026-06-17)**: All 6 HWMCC software-origin benchmarks proved via BTOR2 constraint injection
- **Multi-round verification**: round-1 quick scan + round-2 with helper constraints
- **ule fallback for eq candidates**: when eq(A,B) times out, auto-try ule(A,B)
- **Deduplication**: sound ASTs deduplicated by canonical JSON key before injection
- **Formula-rich transition sketch**: `_decode_expr()` renders actual formulas (c' = (i>=n? c : c+i))
- **Output-label extraction**: unnamed states in fib_30/fib_37 now detected via `output` BTOR2 statements
- **Sym_pair injection before LLM**: fib_05 eq(x,y) injected deterministically without LLM
- **LLM stdout fixed**: `[llm]` and `[preprocess_sw]` messages now go to stderr only
- **Exhaustive HWMCC scan**: ~900 BV benchmarks, 6 software-origin benchmarks found
- Stage 0 reliability hardening: deterministic sym_pair injection, LLM gated on sym_pairs
- Q5 diagnosis: secondary hot vars, symmetry detection, fib_05 Class-A result (reactive approach)

## Backlog

- **Reliability improvement**: retry loop if few sound invariants found
- **Parallel verification**: concurrent `verify_invariant` calls to reduce wall time
- **Broader benchmark scan**: sv-benchmarks, HWMCC 2020 non-BV, custom circuits
- **Paper/report**: method, results, comparison with baseline
- Stage 2 full trigger logic (T1/T2/T3 monitors) — low priority given new pre-processing wins
- OpenRouter provider policy documentation
