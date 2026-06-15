# Plan

**Active plan:** [`docs/plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md)  
**Handoff:** [`docs/HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md)

## In Progress

Stage 0 + Stage 2 skeleton is built and tested. Now filling in content:

1. **`llm_worker/invariant_prompt.py`** — Stage 0 + Stage 2 prompt builders (convert `benchmark_context.json` → prompt)
2. **`llm_worker/invariant_sidecar.py`** — `handle_stage0_request`, `handle_stage2_request` handlers

## Next Up

3. C++: `build_stage0_request_json` + `sync_wait_and_apply_invariants` in `llm_generalizer.cpp`
4. C++: Stage 2 trigger conditions (T1/T2/T3) in `ic3base.cpp`
5. C++: `parse_predicate_ast` from JSON (`engines/ic3_frame_ast.cpp`)
6. **A/B gate**: CTI elimination rate with vs. without Stage 0 injection → go/no-go for Stage 2

## Do Not Do

- Restore per-CTI blocking clause code
- Restore `ic3_frame_v1.txt` or `ab_q*` scripts
- Use `rejected_initial` / `accept/API` as primary metrics
- Re-implement anything from Q2/Q3/Q4
