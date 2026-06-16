# Structure

| Path | Purpose |
|------|---------|
| `engines/` | IC3/IC3IA engine (C++): `ic3base.cpp`, `ic3ia.cpp`, `llm_generalizer.cpp` |
| `core/` | Transition system types (FTS, RTS), term/sort abstractions |
| `frontends/` | BTOR2 parser, Verilog frontend hooks |
| `llm_worker/` | Python sidecar + pre-processor: `sidecar.py`, `invariant_sidecar.py`, `invariant_arith.py`, `invariant_prompt.py`, `btor2_reader.py`, `llm_client.py`, `jsonl_protocol.py` |
| `options/` | CLI option definitions |
| `modifiers/` | Transition system modifiers (cone of influence, etc.) |
| `refiners/` | CEGAR refinement components |
| `printers/` | Witness/proof printers |
| `smt/` | SMT utility wrappers |
| `utils/` | Logging, timing, misc utilities |
| `tests/` | C++ tests (googletest) + Python tests (`tests/python/`) |
| `scripts/` | Benchmark harness + `preprocess_sw.py` (software-origin BTOR2 pre-processor CLI) |
| `benchmarks/` | Micro-benchmarks and BTOR2 test cases |
| `bench_results/` | Experiment output (not in git) |
| `docs/` | All docs; `docs/plans/` = active plans; `docs/superpowers/` = HISTORICAL |
| `diagnosis/` | Per-phase diagnosis notes |
| `prompts/` | LLM prompt templates |
| `samples/` | Example BTOR2 designs |
| `deps/` | Vendored deps: `smt-switch/`, `btor2tools/` |
| `build/` | CMake output (not in git) |
| `contrib/` | Dependency setup scripts |

## Module Boundaries

- **C++ ↔ Python**: only via JSONL files at known paths (`--llm-req-path`, `--llm-resp-path`). No sockets, no subprocess calls.
- `llm_generalizer.cpp` owns CTI digest, frame snapshot serialization, and LLM request building on the C++ side.
- `llm_worker/` owns all LLM API calls; `sidecar.py` is the only runtime entry point.
- `jsonl_protocol.py` (transport) + `invariant_sidecar.py`/`invariant_prompt.py` (Stage 0/2 messages) define the shared request/response schema — change both sides together.
- C++ `core/` and `engines/` have no knowledge of Python or LLM; they expose `constrain_frame` / `add_predicate` as injection points only.
