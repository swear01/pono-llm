# Semantic Invariant Injection — 新主計劃 v1

**狀態：** 🟢 Active — 取代 Q2/Q3/Q4 blocking clause 路線  
**日期：** 2026-06-14  
**前置診斷：** Q2–Q4 達 0% accept；根因在策略，不在 prompt — 見 `docs/archive/plans/README.md`

---

## 一句話策略轉向

> **從「LLM 擋子彈」（per-CTI reactive blocking）→「LLM 預測子彈方向」（proactive semantic invariant generation）**

IC3 的真正瓶頸不是 SAT 驗算，而是**設計語意的盲目**：solver 對電路行為一無所知，只能暴力搜索。LLM 讀過大量 RTL，有隱含的 hardware domain knowledge。把 LLM 放在語意層，讓 C++ 繼續做它最擅長的驗算。

---

## 為什麼之前的方向沒有爆發力

| 舊架構 | 問題 |
|--------|------|
| 每個 CTI 問一次 LLM | 4–6s/call × 數千 CTI = 不可行 |
| 輸入：`stateNN` 統計數字 | LLM 對 `state512` 沒有任何 domain knowledge |
| 輸出：bit-level literal | 必須猜對具體值才能通過 SAT；LLM 做不到 |
| 驗算：per-CTI reject | 一次 block 一個 CTI，槓桿為 1 |
| 語意反轉 bug | prompt 說 clause FALSE at init；C++ 要 TRUE at init |

---

## 新架構

```
Phase 0  設計語意萃取（一次性，每個 benchmark）
  BTOR2 + symbol_registry + property
    → 關鍵 state variable Verilog 名稱
    → 轉移函數 pseudo-code（next(X) = ite(...)）
    → bad property 的自然語言描述

Phase 1  LLM 語意不變量生成（一次 or 少數幾次 API call）
  輸入：設計語意 bundle（RTL level，有意義的名稱）
  問：「這個電路應該滿足哪些 invariants？」
  輸出：10–20 個候選不變量（predicate AST，有直覺說明）

Phase 2  C++ 批次驗算（不需 LLM）
  對每個候選 P：
    ① init_safe：init ⊨ P ？（C++ SAT query）
    ② rel_ind_check(frame_0, P)：P ∧ T ⊨ P' ？
    ③ CTI-blocking power：現有 CTI pool 中有幾個被 P 消除？

Phase 3  注入 + 量測
  constrain_frame(0..K, surviving_invariants)
  對比：有注入 vs 無注入 → CTI 數、frame 數、wall clock
```

**關鍵槓桿：** 一個好的 invariant 可以消滅幾百個 CTI。LLM 只需要一次 API call。

---

## 為什麼這個方向有爆發力

1. **槓桿比：** 現在 accept rate = 0，即使修到 10% 也是每個 CTI blocking 1 個。新方向：1 個 invariant 可能消滅 50–500 個 CTI。

2. **LLM 的真實 alpha：** LLM 知道 FIFO 有 `rd_ptr ≤ wr_ptr`，知道 FSM 有互斥狀態，知道 counter 有 boundary。這些知識 SAT solver 完全沒有。這才是 LLM 應該貢獻的東西。

3. **介面匹配：** 給 LLM `imgfifo_wr_ptr`, `imgfifo_depth`, `wr_en`（有語意的 Verilog 名稱）讓它推理。不要給它 `state512`, `state798`（沒有任何意義）。

4. **失敗代價低：** 一次 LLM call 花 10 秒，驗算 20 個候選花 1 秒，全部 fail 也只損失 11 秒。現在每個 CTI 都等 4–6 秒還是全失敗。

---

## 已有的建構積木（不用從頭蓋）

| 模組 | 位置 | 狀態 |
|------|------|------|
| Invariant schema 定義（8 種） | `llm_worker/lemma_schema.py` | ✅ 完整 |
| Template prompt builder | `llm_worker/template_prompt.py` | ✅ 完整 |
| CTI cluster 分析 | `llm_worker/clause_cluster.py` | ✅ 完整 |
| Transition pseudo-code 萃取 | `llm_worker/transition_slice.py` | ✅ 骨架（需 BTOR2 → readable 補強） |
| MVP E2E driver | `llm_worker/run_mvp.py` | ✅ 可執行（需針對 p040 調整） |
| `is_init_safe_block_disjuncts` | `engines/ic3base.cpp:1062` | ✅ C++ SAT check 就緒 |
| `rel_ind_check` | `engines/ic3base.cpp:577` | ✅ |
| `constrain_frame` | `engines/ic3base.cpp` | ✅ |
| `refine_predicate` AST | `engines/ic3_frame_ast.cpp` | ✅ parse 就緒，inject 還是 stub |
| symbol_registry（Verilog 名稱） | C++ + `benchmark_context.json` | ✅ |

**缺的是「策略層」，不是「工具層」。**

---

## 2 週執行計劃

### Week 1 — Minimum Viable Experiment（最小可驗實驗）

#### Task S1：設計語意 bundle for p040（Day 1–2）

**目標：** 讓 LLM 讀到有意義的電路描述，不是 `stateNN` 數字。

1. 從 `symbol_registry` 提取 `vgasim_imgfifo-p040` 的 Verilog 名稱
2. 補強 `transition_slice.py`：從 C++ dump 的 BTOR2 next-state 方程式，轉成可讀的 pseudo-code（`if (wr_en && !full) imgfifo_wr_ptr' = imgfifo_wr_ptr + 1`）
3. 從 `bad_property` 提取性質自然語言描述
4. 輸出：`/tmp/p040_semantic_bundle.json`

**驗收：** 人工閱讀 bundle，確認 LLM 看到的是有語意的電路描述，不是匿名 stateNN。

---

#### Task S2：LLM invariant 生成（Day 2–3）

**目標：** 得到 10–20 個候選 invariants。

1. 用現有 `template_prompt.py` + `lemma_schema.py` 構建 prompt
2. 讓 LLM 生成候選 invariants（用 Verilog 名稱，不是 stateNN）
3. Parse 輸出為 `refine_predicate` AST 或 `block_clause` 形式

**Prompt 核心問題：**
```
你是硬體驗證專家。以下是 vgasim_imgfifo 電路和待驗 property。
列出 10–20 個你認為應該成立的不變量，用於協助 IC3 模型檢查。
格式要求：
- 只用電路本身的狀態變數（不含輸入）
- 用 guarded_implication 或 mutual_exclusion 格式
- 每個附上直覺說明

Property: imgfifo 的輸出應永遠不超過 N 個 pixel
Circuit: [semantic bundle]
```

**驗收：** LLM 輸出包含有語意的候選（如 `wr_ptr ≤ depth`），不是隨機 literal。

---

#### Task S3：C++ 批次驗算腳本（Day 3–4）

**目標：** 量出每個候選的存活率和 CTI-blocking power。

```python
# scripts/validate_invariant_candidates.py
# 輸入：candidates.json（LLM 輸出）+ IC3 run 的 CTI log
# 對每個 candidate：
#   1. init_safe check（呼叫 pono SMT context）
#   2. rel_ind_check(frame_0)
#   3. 計算：這個 invariant 能消滅 CTI pool 中幾個 CTI？
# 輸出：candidate_fate.json（每個候選的 pass/fail + CTI elimination count）
```

**驗收指標（go/no-go）：**

| 結果 | 解讀 |
|------|------|
| ≥1 個候選通過 init + rel_ind | ✅ 架構可行，繼續 |
| 通過的候選消滅 ≥10% CTI | 🚀 有爆發力，full integration |
| 0 個通過但失敗原因是 init（不是 induction） | LLM 生成了 unsafe predicate；調整 prompt 加 init 指引 |
| 0 個通過且失敗原因是 induction | Predicate 太弱；換成更強的 schema 或加條件 |
| 全部 schema_fail / parse_fail | Interface 問題，修 schema + parse |

---

#### Task S4：手動 A/B 量測（Day 4–5）

對 p040：
1. Run baseline：`pono -e ic3ia -k 5 vgasim_imgfifo-p040.btor2`，記錄 CTI 數、frame 數
2. 把通過驗算的 invariants 手動 `constrain_frame(0, ...)` 注入
3. Re-run，記錄 CTI 數、frame 數
4. 計算：CTI 減少 %、frame 減少 %、wall clock 改善

---

### Week 2 — Integration + Scaling

#### Task S5：C++ Batch Injection API（Day 6–7）

把 Phase 1 手動注入自動化：
- `--llm-gen-mode invariant-inject`：在 IC3 啟動前，調用一次 LLM → 批次驗算 → 自動注入
- 不需要 per-CTI API call

#### Task S6：2–3 個其他 benchmark（Day 7–9）

測試 generalizability：
- 選 SAME 率低的 benchmark（讓 CTI pool 的 diversity 更高）
- 用相同 LLM invariant pipeline
- 測：是否在不同 benchmark 都有 CTI reduction？

#### Task S7：量化爆發力（Day 10）

整理實驗結果：
- 最佳 invariant 的 CTI elimination 率
- IC3 frame count reduction
- 總 LLM API calls vs 舊路（現在：千次 per-CTI calls；新路：1–3 次 per-circuit calls）
- 如果有 HWMCC benchmark 在注入後首次 solve → 這就是爆發力

---

## 關鍵設計決策

### LLM 的角色定位

| 做 | 不做 |
|----|------|
| 從 RTL 語意推理不變量 | 猜 bit-level literal 值 |
| 批次生成 10–20 個候選 | per-CTI 反應式生成 |
| 提供直覺說明（可 debug） | 假裝能驗算 SAT |
| 使用 Verilog 名稱 | 操作 stateNN 匿名 ref |

### C++ 的角色定位

- 所有 formal 驗算（init, induction, CTI blocking）：C++ 做
- LLM 不做任何 verify，只做 generate + explain
- 兩者清楚分工，不混淆

### 成功的定義

**最小成功：** ≥1 個 LLM 生成的 invariant 通過 C++ 驗算，並消滅 ≥5% 的 CTI pool  
**中等成功：** IC3 在有注入的情況下 frame count 減少 ≥20%  
**爆發性成功：** 有 benchmark 因注入而首次在時限內 solve

---

## 停損條件

**停止並考慮其他方向，如果：**

- 10 個以上 benchmark 試下來，LLM 候選的 init_safe 率 < 10%（LLM 生成的 invariant 連初始狀態都過不了 → LLM 對 init semantics 理解不足）
- CTI elimination rate 在所有 benchmark 都 < 2%（invariant 太弱，對 IC3 沒有實質幫助）
- 以上發生時：考慮 offline mining（從已 solved 的 proof artifact 中 lift invariants）或 LLM-guided predicate selection（給 LLM 預選好的 predicate pool，讓它排序而非生成）

---

## 與現有基礎設施的關係

| 現有 | 新方向是否需要 |
|------|--------------|
| JSONL IPC（C++ ↔ sidecar） | ✅ 保留，改為 batch request mode |
| `rel_ind_check`, `constrain_frame` | ✅ 核心路徑不變 |
| `refine_predicate` AST | ✅ 主要輸出格式之一 |
| `ic3_frame_v1.txt` prompt | ❌ 不再使用；改用 `template_prompt.py` |
| `harness_preprocess.py` | ❌ per-CTI task card；不再需要 |
| `candidate_hints`, `init_raw` C++ fields | ⚠️ 可用於 Phase 2 驗算加速，但不是 LLM 輸入 |
| `lemma_schema.py`, `template_prompt.py` | ✅ **核心，這是新方向的基礎** |

---

## Agent 須知

1. **新 smoke 基準：** `scripts/smoke_semantic_invariant.sh`（待建）— 不再跑 `ab_q3_p040_multiround.sh`
2. **Commit 後 push**：每次 commit 後 `git push origin main`
3. **不要**再動 `ic3_frame_v1.txt` 的 clause blocking prompt；那個路線已封存
4. **不要**跑 per-CTI accept rate 作為主要指標；新指標是 CTI elimination rate + frame reduction
