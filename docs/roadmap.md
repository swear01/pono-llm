# Roadmap

## Backlog

- **Stage 2 full trigger logic** — T1/T2/T3 monitors in `ic3base.cpp`
- **Stage 3** — cooldown loop after Stage 2 injection
- **X1–X4 lemma expressiveness expansion** — see `docs/plans/lemma_expressiveness_roadmap.md`; gated on Phase Q data
- Python smoke script: `scripts/smoke_semantic_invariant.sh`
- OpenRouter v4-flash provider policy — `docs/plans/openrouter_provider_policy.md`

## Recently Done

- **Exhaustive HWMCC scan**: ~900 BV benchmarks, fib_05 is the only Class-A (2026-06)
- Stage 0 reliability hardening: deterministic sym_pair injection, LLM gated on sym_pairs
- Stage 2 gating: sym_pairs AND cti_count>0 required; skips T2_plateau (0 CTI) case
- `_expr_canonical_hash()`: structural expression matching replaces dep-set matching for sym_pairs
- Secondary BFS bug fix: empty t_visited prevents primary phase blocking secondary exploration
- `property_desc` truncation (200 chars) — prevents HTTP 413 on 2.3MB+ circuit formulas
- `_is_safe_candidate()` safety filter: ref-ref only, rejects const bounds and arithmetic
- Q5 diagnosis: secondary hot vars, symmetry detection, fib_05 Class-A result
- Stage 0 + Stage 2 E2E integration tests (live DeepSeek + request_id parsing)
- HWMCC benchmark runner + predicate coercion for 1-bit BVs
- ProofGoalQueue UAF fix
- JSONL IPC protocol (stable)
- CTI digest (`build_cti_digest`) + frame snapshot serialization
- Symbol registry + `benchmark_context.json` output
- Q2/Q3/Q4 code deleted; sidecar cleaned up as Stage 0/2 shell
