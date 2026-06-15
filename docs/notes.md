# Notes

> Tacit knowledge an agent can't infer from reading code.

## Gotchas

- **Never restore per-CTI blocking code.** Q2/Q3/Q4 all reached 0% accept rate: per-CTI reactive LLM querying is a dead abstraction. The replacement is Stage 0/2 semantic invariant injection.
- **Do not restore deleted files**: `ic3_frame_v1.txt`, `ab_q*` scripts, old harness_preprocess, old per-CTI prompt_format.
- **IC3IA is nondeterministic** in clause ordering. E2E A/B metrics must run multiple seeds; see `docs/baseline_reproducibility.md`.
- **smt-switch uses shared_ptr everywhere.** Use `->` not `.` for solver/term accesses.
- **`benchmark_context.json`** is produced at startup from `symbol_registry`; it's the only semantic bridge to give LLM Verilog-level names instead of anonymous `stateNN`.
- **HWMCC baseline** (`bench_results/hwmcc_baseline_20260607`) is not in git — ~168 cases suspended in first round.

## Decisions

- **Stage 0 before Stage 2**: Must validate LLM invariant quality at Stage 0 (pre-flight) before building Stage 2 (mid-run) complexity.
- **Primary metric = CTI elimination rate**, not per-CTI accept rate. A single invariant should block a cluster.
- **Python sidecar, not in-process**: LLM calls are async and potentially slow; keeping them out-of-process prevents blocking IC3's main loop.
- **Commit then push**: Always `git push origin main` after committing (per handoff).
