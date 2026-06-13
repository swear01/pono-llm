# Handoff: Current State

**Last updated:** 2026-06-14 — 策略轉向：reactive blocking → proactive invariant injection  
**Branch:** `main` (pono-llm research fork)

---

## ⚠️ 重大策略轉向（2026-06-14）

**Q2/Q3/Q4 方向已封存。** 三個階段均達到 0% accept rate。根因是策略問題，不是 prompt 問題：

- LLM 被放在錯誤的位置（per-CTI reactive blocking，bit-level literal 猜測）
- LLM 對 `state512`, `state798` 這些匿名 ref 沒有任何 domain knowledge
- SAME-column impossibility：p040 frame-1 的 93% digest ref 在 init 和 CTI 有相同值，無法單 disjunct blocking
- Prompt 語意反轉：`ic3_frame_v1.txt` 說 clause FALSE at init；C++ 要 TRUE at init（根本原因之一）

→ 詳見 `docs/archive/plans/README.md`

---

## Active Direction

**新方向：Proactive Semantic Invariant Injection**  
**主計劃：** [`docs/plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md)

核心邏輯：

```
給 LLM：RTL 語意（Verilog 名稱 + transition pseudo-code + property）
問 LLM：「這個電路應該有哪些不變量？」
C++ 批次驗算：init_safe + rel_ind_check + CTI blocking power
注入存活的 invariants → IC3 從更強的起點跑
```

**一個好的 invariant 可以消滅幾百個 CTI。** 這才是 LLM 的槓桿點。

---

## Agent 須知

1. **Commit 後自動 push** — 每次 commit 後直接 `git push origin main`
2. **不要**再動 `llm_worker/prompts/ic3_frame_v1.txt` 的 blocking clause prompt — 舊路線
3. **不要**再跑 `ab_q3_p040_multiround.sh` / `ab_q4_p040_multiround.sh` — 舊基準
4. **新 smoke 基準**（待建）：`scripts/smoke_semantic_invariant.sh` — 量 CTI elimination rate

---

## 現有可用建構積木

| 模組 | 路徑 | 作用 |
|------|------|------|
| Invariant schema | `llm_worker/lemma_schema.py` | 8 種不變量模板 |
| Template prompt | `llm_worker/template_prompt.py` | 語意 bundle → LLM prompt |
| CTI cluster 分析 | `llm_worker/clause_cluster.py` | CTI batch 結構分析 |
| Transition 萃取 | `llm_worker/transition_slice.py` | 轉移函數 pseudo-code |
| MVP E2E driver | `llm_worker/run_mvp.py` | 端到端 pilot 測試用 |
| `rel_ind_check`, `constrain_frame` | `engines/ic3base.cpp` | C++ formal 驗算 |
| `refine_predicate` AST | `engines/ic3_frame_ast.cpp` | Predicate 格式 |
| `is_init_safe_block_disjuncts` | `engines/ic3base.cpp:1062` | Init check |

---

## 本週最高優先事項

1. **S1**：生成 p040 的設計語意 bundle（讓 LLM 讀到 Verilog 名稱，不是 stateNN）
2. **S2**：LLM 生成 10–20 個候選 invariants for p040
3. **S3**：C++ 批次驗算腳本（init_safe + rel_ind + CTI blocking power）
4. **S4**：手動 A/B — 有無 invariant injection 的 CTI 數對比

詳見 `docs/plans/semantic_invariant_injection_v1_plan.md`。

---

## 其他基礎設施狀態

| 項目 | 狀態 |
|------|------|
| HWMCC baseline | `bench_results/hwmcc_baseline_20260607`；首輪 ~168 案 suspend |
| JSONL IPC（C++ ↔ sidecar） | 保留；改為 batch invariant request mode |
| BUG: ProofGoalQueue UAF | ✅ 已修（`c478d89`），smoke 開頭 `make pono-bin` |
| Legacy paths（cube_subset, qf_smt） | 待刪除（不急） |

---

## Do not do

- 繼續投資 per-CTI blocking clause prompt 優化
- 修 `ic3_frame_v1.txt` 的語意反轉（對新方向無意義）
- 用 `rejected_initial` / `accept/API` 作為主要研究指標
- 把 `harness_preprocess.py` 的 task card 再加功能
