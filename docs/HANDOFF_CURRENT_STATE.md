# Handoff: Current State

**Last updated:** 2026-06-14 — v2 plan: two-phase LLM guidance (Stage 0 pre-flight + Stage 2 mid-run)  
**Branch:** `main` (pono-llm research fork)

---

## 策略方向（一句話）

LLM 看電路語意、生成 invariants，C++ 做所有 formal 驗算。  
一個好的 invariant 消滅幾百個 CTI；不再 per-CTI 問 LLM。

---

## Q2/Q3/Q4 已死

三個階段均達到 0% accept rate，根因是策略問題：
- LLM 被放在 per-CTI reactive blocking 的位置（錯誤抽象層）
- 輸入是 `stateNN` 匿名 ref（無 domain knowledge）
- SAME-column impossibility（p040 93% 的 ref 在 init = CTI）
- Prompt 語意反轉

所有相關代碼（harness_preprocess, ic3_frame_schema, prompt_format, 舊 AB scripts）已刪除。  
**不要復原這些文件。**

---

## Active Plan

**主計劃：** [`docs/plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md)

架構：

```
Stage 0  Pre-flight
  RTL 語意 bundle → LLM → candidates → C++ 驗算 → 注入 F0

Stage 1  IC3 執行（含監控）
  監控 T1（CTI cluster density）/ T2（frame plateau）/ T3（clause budget）

Stage 2  Mid-run 同步引導（條件觸發）
  現場証據 → LLM → Type1/2/3 → C++ 驗算 → 注入

Stage 3  迴圈（cooldown 後繼續）
```

三種 LLM 輸出：
- **Type 1**：新 invariant → `constrain_frame(0, ...)`
- **Type 2**：clause lifting → 替換現有 frame clauses
- **Type 3**：IC3IA predicate → `add_predicate(...)`

---

## 現有可用建構積木

| 模組 | 路徑 | 狀態 |
|------|------|------|
| Sidecar shell | `llm_worker/sidecar.py` | ✅ 已清理；加 handler 即可 |
| JSONL IPC | `llm_worker/jsonl_protocol.py` | ✅ 完整，不動 |
| LLM API client | `llm_worker/llm_client.py` | ✅ 完整，不動 |
| `constrain_frame` | `engines/ic3base.cpp` | ✅ 注入核心 |
| `is_init_safe_block_disjuncts` | `engines/ic3base.cpp:1062` | ✅ Init check |
| `rel_ind_check` | `engines/ic3base.cpp:577` | ✅ Induction check |
| `symbol_registry` / `benchmark_context.json` | C++ + JSON output | ✅ Verilog 名稱來源 |
| `serialize_frame_snapshot_json` | `engines/ic3base.cpp:2020` | ✅ Frame clause 序列化 |
| `build_cti_digest` | `engines/llm_generalizer.cpp` | ✅ CTI cluster 統計 |

---

## 還沒建的（按順序）

1. `llm_worker/invariant_prompt.py` — Stage 0 + Stage 2 prompt builders
2. `llm_worker/invariant_sidecar.py` — `handle_stage0_request`, `handle_stage2_request`
3. C++: `build_stage0_request_json` + `sync_wait_and_apply_invariants`（`llm_generalizer.cpp`）
4. C++: Stage 2 trigger conditions（`ic3base.cpp`）
5. C++: `parse_predicate_ast` from JSON（`engines/ic3_frame_ast.cpp`，可能已有基礎）

---

## 本週最高優先

1. **Day 1-2**：Python 先行 — 把 `benchmark_context.json` 轉成 Stage 0 prompt，確認 LLM 輸出有語意
2. **Day 3**：C++ `build_stage0_request_json` + smoke test（request JSONL 出現）
3. **Day 4**：Response parsing + `constrain_frame` injection
4. **Day 5**：A/B：有/無 Stage 0 injection 的 CTI 數對比 → go/no-go

---

## 基礎設施狀態

| 項目 | 狀態 |
|------|------|
| HWMCC baseline | `bench_results/hwmcc_baseline_20260607`；首輪 ~168 案 suspend |
| JSONL IPC | ✅ 保留，sidecar 已清理為新架構的 shell |
| ProofGoalQueue UAF | ✅ 已修（`c478d89`）|
| 舊 per-CTI 代碼 | ❌ 已刪除 |

---

## Agent 須知

1. **Commit 後 push**：`git push origin main`
2. **Stage 0 先做**：驗證 LLM invariant 品質再做 Stage 2
3. **新 smoke 基準**：`scripts/smoke_semantic_invariant.sh`（待建）
4. **主要指標**：CTI elimination rate，不是 per-CTI accept rate
5. **不要**復原任何 per-CTI blocking clause 代碼

## Do not do

- 修或恢復 `ic3_frame_v1.txt`（已刪）
- 跑 `ab_q*` 腳本（已刪）
- 用 `rejected_initial` / `accept/API` 作主要指標
- 再做 per-CTI reactive blocking 相關的任何事
