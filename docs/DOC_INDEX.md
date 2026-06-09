# Documentation Index

**Canonical integration spec:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)  
**Architecture:** [`ARCHITECTURE.md`](ARCHITECTURE.md)  
**Handoff:** [`HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md)

Last updated: 2026-06-09 (Q2 shipped; Q3 clause quality plan)

> **Note:** `logs/formal_yield/` was removed from the repo (legacy offline artifacts). HISTORICAL docs may still reference that path; see `.gitignore`.

---

## Status legend

| Tag | Meaning |
|-----|---------|
| **CANONICAL** | Current spec or active handoff |
| **ARCHITECTURE** | System design aligned with v1 |
| **HISTORICAL** | Research record; runtime path **deleted** with v1 (not deprecated) |
| **RESULTS** | Experiment logs; offline pipeline only |

---

## Canonical (v1 integration)

| File | Description |
|------|-------------|
| [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) | Request/response schema, batch+digest, JSONL, channel vs quality |
| [`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) | Tier 0–3 SOP；baseline / **baseline-patch** / **--skip-partial** resume |
| [`plans/experiment_parallel_policy.md`](plans/experiment_parallel_policy.md) | 實驗八開預設、伺服器容量、harness 參數 |
| [`plans/experiment_plan_review.md`](plans/experiment_plan_review.md) | **實驗總檢視**、Phase L/E/Q todo、首輪教訓 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | C++/sidecar flow for v1 |
| [`HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md) | Current task and file map |
| [`pono_frame_cti_dump_format.md`](pono_frame_cti_dump_format.md) | Frame/CTI dump (reuse for harness L3) |
| [`ic3ia_predicate_mapping_audit.md`](ic3ia_predicate_mapping_audit.md) | stateNN ↔ BTOR2 |
| [`mapping_spike_solver_shortlist.md`](mapping_spike_solver_shortlist.md) | Symbol shortlist notes |
| [`generalization_operators.md`](generalization_operators.md) | Operator names for `operator` field |
| [`plans/frame_snapshot_quality_plan.md`](plans/frame_snapshot_quality_plan.md) | Frame snapshot 品質（Track A 已實施；Track B 視 Phase Q） |
| [`plans/lemma_expressiveness_roadmap.md`](plans/lemma_expressiveness_roadmap.md) | **未來** — lemma 表達力擴充 X1–X4；Gate 0 待 Phase Q 數據 |
| [`plans/openrouter_provider_policy.md`](plans/openrouter_provider_policy.md) | OpenRouter v4-flash 供應商篩選（fp8、排除 fp4/貴/慢） |
| [`plans/phase_a_postmortem_plan.md`](plans/phase_a_postmortem_plan.md) | **Phase A 事後分析** — batch_timeouts、accept 低、24 案 regression 計劃 |
| [`plans/clause_quality_q2_plan.md`](plans/clause_quality_q2_plan.md) | **Phase Q2**（tag `post-q2-clause-quality`）— init prompt、enriched feedback |
| [`plans/clause_quality_q3_plan.md`](plans/clause_quality_q3_plan.md) | **Phase Q3** — witness 模板、digest 否定、11 案子集 5 輪 gate |
| [`plans/clause_quality_q3_1_q3_2_plan.md`](plans/clause_quality_q3_1_q3_2_plan.md) | **Q3.1+Q3.2 詳規** — FORBIDDEN 規則表、digest negate、A/B 門檻 |
| [`diagnosis/Q2_current_method_summary.md`](../diagnosis/Q2_current_method_summary.md) | Q2 現行方法 p040 smoke 失敗模式（B2 100%、CTI 抄襲 98%） |

---

## Historical — Path 1 / injection (code **to be deleted**)

| File | Notes |
|------|-------|
| [`llm_injection_capability_audit.md`](llm_injection_capability_audit.md) | Task 107A audit; research baseline only |
| [`llm_injection_supported_grammar.md`](llm_injection_supported_grammar.md) | Text grammar for reset_solver; **deleted with Path 1** |
| [`minimal_lifted_lemma_injection_plan.md`](minimal_lifted_lemma_injection_plan.md) | Superseded plan |
| [`concrete_assertion_injection_blocker.md`](concrete_assertion_injection_blocker.md) | SUPERSEDED |
| [`concrete_lemma_term_builder_blocker.md`](concrete_lemma_term_builder_blocker.md) | SUPERSEDED |
| [`concrete_solver_assertion_injection_audit.md`](concrete_solver_assertion_injection_audit.md) | SUPERSEDED |
| [`reset_solver_injection_soundness_note.md`](reset_solver_injection_soundness_note.md) | Path 1 soundness notes |
| [`reset_solver_injection_code_audit.md`](reset_solver_injection_code_audit.md) | Path 1 code audit |
| [`reset_solver_injection_claim_boundary.md`](reset_solver_injection_claim_boundary.md) | Claim boundaries |
| [`cross_variant_injection_blocker.md`](cross_variant_injection_blocker.md) | Injection experiments |
| [`p040_injection_k10_blocker.md`](p040_injection_k10_blocker.md) | Injection experiments |
| [`low_cost_injection_proxy_plan.md`](low_cost_injection_proxy_plan.md) | Impact proxy plan |

---

## Historical — offline lemma mining / closed-loop

| File | Notes |
|------|-------|
| [`research_overview.md`](research_overview.md) | Updated with v1 pivot section |
| [`research_scope.md`](research_scope.md) | Updated scope |
| [`method_evolution.md`](method_evolution.md) | Chronology + v1 pivot |
| [`current_progress_summary.md`](current_progress_summary.md) | Closed-loop result + pivot |
| [`future_work_pono_integration.md`](future_work_pono_integration.md) | Superseded by v1 checklist |
| [`0514_async_ic3ia.md`](0514_async_ic3ia.md) | Original research proposal + v1 alignment |
| [`closed_loop_*.md`](closed_loop_synthesis_results.md) | Offline Bitwuzla results |
| [`formal_yield_table.md`](formal_yield_table.md) | Yield tables |
| [`lemma_mining_method_comparison*.md`](lemma_mining_method_comparison_final.md) | Method comparison |
| [`superpowers/plans/*.md`](superpowers/plans/2026-05-24-offline-llm-repair-replay.md) | **HISTORICAL** — offline replay / MVP plans; `llm_worker/run_*.py` **deleted** |
| [`superpowers/specs/*.md`](superpowers/specs/2026-05-24-offline-llm-repair-replay-design.md) | **HISTORICAL** — offline design specs only |

---

## `llm_worker/` (v1 runtime)

| File | Tag |
|------|-----|
| [`llm_worker/README.md`](../llm_worker/README.md) | **CANONICAL** — sidecar is the only runtime entry |
| [`llm_worker/sidecar.py`](../llm_worker/sidecar.py) | **CANONICAL** |
| [`llm_worker/deepseek_client.py`](../llm_worker/deepseek_client.py) | **CANONICAL** |
| [`llm_worker/jsonl_protocol.py`](../llm_worker/jsonl_protocol.py) | **CANONICAL** |
| [`llm_worker/ic3_frame_schema.py`](../llm_worker/ic3_frame_schema.py) | **CANONICAL** |

Legacy `run_*.py`, `offline_*.py`, and offline helper modules were **removed** (not archived). Research docs under `docs/superpowers/` remain as **HISTORICAL** record only.

---

## Other

| File | Tag |
|------|-----|
| [`BUG_ANALYSIS.md`](BUG_ANALYSIS.md) | ARCHITECTURE — legacy bugs; update as v1 lands |
| [`gotchas.md`](gotchas.md) | General |
| [`baseline_reproducibility.md`](baseline_reproducibility.md) | IC3IA nondeterminism — E2E metrics design |
| [`ic3ia_nondeterminism_audit.md`](ic3ia_nondeterminism_audit.md) | Nondeterminism audit |

When adding new docs, link from this index and tag status explicitly.
