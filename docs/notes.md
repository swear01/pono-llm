# Notes

> Tacit knowledge an agent can't infer from reading code.

## Gotchas

- **Never restore per-CTI blocking code.** Q2/Q3/Q4 all reached 0% accept rate: per-CTI reactive LLM querying is a dead abstraction. The replacement is BTOR2 constraint pre-processing.
- **Do not restore deleted files**: `ic3_frame_v1.txt`, `ab_q*` scripts, old harness_preprocess, old per-CTI prompt_format.
- **smt-switch uses shared_ptr everywhere.** Use `->` not `.` for solver/term accesses.
- **Reactive predicate injection does NOT work for arithmetic invariants**: IC3IA accepts arithmetic predicates (x+y==3*i) but still can't close proof — refinement adds bit-extraction predicates. Pre-processing is the only working approach.
- **BTOR2 sort IDs are line numbers, not bit widths.** When building BTOR2, always use `Btor2Builder.get_sort(width)` to get the correct sort line number.
- **pono exit codes**: TRUE=1 (safe, UNSAT), FALSE=0 (unsafe, SAT), UNKNOWN=-1 (shell 255), ERROR=2.
- **LLM [llm] messages go to stderr** (fixed 2026-06-17). Capture stdout only for constrained BTOR2 path: `CONSTRAINED=$(python3 scripts/preprocess_sw.py file.btor2 2>/dev/null)`.
- **Quadratic equality `2*x==i*(i-1)` can never be verified standalone** — IC3IA times out. The inequality `2*x<=i*(i-1)` verifies in <0.1s with `i<=n` as helper. The ule fallback is auto-applied.
- **fib_30/fib_37 state names come from output labels** not state labels — `output 7 c` gives state7 the name 'c'. Now handled by `parse_btor2()`.
- **BTOR2 deps for uext/sext/slice do NOT include sort**: parser saves only `parts[3]` (the data expr). For all other ops, `deps[0]` is the sort. `_decode_expr()` handles this correctly.

## Decisions

- **Pre-processing over reactive injection**: Inject verified BTOR2 constraints BEFORE pono runs. IC3IA on constrained BTOR2 proves in <0.3s.
- **Multi-round parallel verification**: Round-1 (4s timeout, parallel up to 4 workers) finds easy invariants. Round-2 with helpers finds complex ones. ThreadPoolExecutor over `subprocess.run` — each pono process is independent, safe to parallelize. Gives 25-57% speedup.
- **Retry loop with probe gate**: If no arithmetic invariants found AND `_has_accumulator_pattern()` detects a variable accumulating another sw var, retry LLM with explicit triangular-sum hint. Probe gate (`_is_proof_fast`, 3s timeout) skips retry when current constraints already prove the circuit (prevents wasted retry on fib_05 which is solved by sym_pair alone).
- **Python sidecar, not in-process**: LLM calls are async; out-of-process prevents blocking IC3's main loop.
- **Formula-rich transition sketch**: Show `c' = (i>=n ? c : c+i)` not `c' depends on states: i, n` — LLM needs the actual formula to infer triangular number invariants.
