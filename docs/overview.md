# Overview

## What This Is

**pono-llm** is a research fork of [Pono](https://github.com/stanford-centaur/pono), an SMT-based hardware model checker from Stanford. The fork adds online LLM-guided invariant generation for the IC3/IC3IA verification engine. LLM sees circuit semantics and generates invariants that C++ formally validates before injecting into IC3 frames — one good invariant eliminates hundreds of CTIs instead of querying the LLM per-CTI.

## Key Concepts / Domain

- **IC3/IC3IA**: Property-directed reachability (PDR) model checking algorithm; IC3IA adds predicate abstraction for bit-vector designs.
- **Frame (Fᵢ)**: A set of clauses over-approximating states reachable in ≤i steps. The core invariant data structure.
- **CTI (Counterexample To Induction)**: A state that violates the property in induction; must be blocked by generalizing a new clause into the frame.
- **constrain_frame(k, clause)**: C++ API to inject a new clause into frame k.
- **BTOR2**: Binary format for hardware transition systems; Pono's primary input.
- **smt-switch**: Solver-agnostic C++ SMT API (Bitwuzla backend used here).
- **Sidecar**: Python process that owns all LLM API calls; communicates with C++ via JSONL files (IPC).
- **Stage 0**: Pre-flight LLM query — sends circuit semantic context, gets invariant candidates before IC3 starts.
- **Stage 2**: Mid-run LLM query — triggered by CTI cluster density (T1), frame plateau (T2), or clause budget (T3).

## External Resources

- IPC protocol / schema: [`llm_worker/jsonl_protocol.py`](../llm_worker/jsonl_protocol.py) — stable JSONL request/response protocol (the old `ic3_frame_v1_integration.md` spec doc was deleted in the v2 cleanup; the schema now lives in code)
- Architecture: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- Doc index: [`docs/DOC_INDEX.md`](DOC_INDEX.md)
- Active plan: [`docs/plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md)
- Handoff: [`docs/HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md)
- LLM sidecar: [`llm_worker/README.md`](../llm_worker/README.md)
- Upstream Pono: https://github.com/stanford-centaur/pono
