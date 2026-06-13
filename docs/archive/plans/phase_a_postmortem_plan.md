# Phase A 事後分析與改進計劃

**狀態：** Phase A 已完成（`20260609_032251_phase_a`，146/146）  
**日期：** 2026-06-09  
**資料：** `bench_results/hwmcc_baseline_20260607/results_llm_phase_a.csv`

---

## 名詞：`batch_timeouts` 是什麼？

**不是**「整個 benchmark 超時」，而是 **單次 batch 同步等待超時**。

流程（`--llm-sync-after-flush` 預設開）：

1. IC3 `block_all` 結束 → C++ `flush_frame_batch` 寫一條 request 到 JSONL  
2. `wait_for_batch_responses(batch_id, K=parallel_samples, timeout=--llm-batch-wait-sec)`  
3. 在 **300s**（harness 預設）內等 sidecar 寫回 **K 條** response（`sample_id` 0..K-1）  
4. 若逾時 → `num_batch_timeout++`，該 batch **可能只收到部分 response**，IC3 仍繼續跑

Phase A：**全體僅 2 次**（`ILA_Rocket_ANDI_sanity`、`res1f`），兩案最終仍 **sat** → **通道基本健康**，不是主因。

日誌：`LLM_BATCH_WAIT batch_id=… wait_ms=… ok=0/1`

---

## Phase A 數字摘要

| 指標 | 值 |
|------|-----|
| 目標 | 146（145 + p040） |
| vs baseline **match** | **117/146**（80%） |
| baseline 已解 → LLM run **timeout** | **24** |
| 有 LLM request | **104** |
| 無 request（`req_n=0`） | **42** |
| 總 API requests | **1146** |
| 總 **accepted** | **20**（**13** 案 ≥1） |
| **accept / request** | **1.75%** |
| **accept / 有 request 的案** | **12.5%**（13/104） |
| `rejected_initial` | **842**（≈ **0.73 / request**） |
| `induction_fail` | **120**（≈ **0.10 / request**） |
| `batch_timeouts` | **2** |

---

## Q1：解出來的題目變少了嗎？

**是，但主因不是 LLM block 害證明錯掉。**

| 現象 | 解讀 |
|------|------|
| 117 案結果與 baseline 一致 | +LLM **沒有**把 sat/unsat 判錯（在時間內跑完時） |
| 24 案 baseline=sat/unsat → LLM=timeout | **牆鐘 1000s 用盡**，不是證偽 |
| CSV 顯示 **`llm_requests=0`**（24 案） | **量測 bug**：harness kill 時無 `LLM_STATS`；archive `requests.jsonl` 實際有 6–68 req/案 |
| 變慢主因（已確認） | **OpenRouter 未關 reasoning** → ~50s/call；**sync wait 累加**（如 `fib_05` ~936s batch wait） |
| 修復（本 commit 後） | OpenRouter `reasoning.effort=none`；harness **jsonl/stderr fallback** 統計 |

**結論：** Phase A 評的是「+LLM 後還能不能在 **同樣 timeout** 內解出」；24 案主因是 **API 等待累加 + 1000s 預算**，不是「沒呼叫 LLM」。

---

## Q2：為什麼 accept 這麼低？

### 拒絕結構（有 request 的 104 案）

| 原因 | 佔比 | 含義 |
|------|------|------|
| **`rejected_initial`** | ~**87%** 的 reject 次數 | block 在 **initial state 就成立** → 太寬、不像 lemma |
| **`induction_fail`** | ~**12%** | 相對 frame 不 inductive |
| **accept** | **1.75% / request** | 少數 generalization 可用 |

### 假設（依數據排序）

1. **H1 — Block 太寬（init 成立）**  
   LLM 從 CTI digest 高頻 literal OR 在一起，容易變成「init 也滿足」的 clause。  
   佐證：`rejected_initial` 842 vs `induction_fail` 120；p040 17 req / 0 accept / 14 rejected_initial。

2. **H2 — Lemma 語言太窄（次要）**  
   只有 `stateNN=常數`；ILA 35 案有 request 僅 **2 accept**。見 [`lemma_expressiveness_roadmap.md`](lemma_expressiveness_roadmap.md)。

3. **H3 — multi-clause first-wins 未幫上忙**  
   3 條候選仍全在 init 或 induction 失敗；需看 response JSON 是否 3 條都類似。

4. **H4 — Feedback 有送但修不好**  
   `format_feedback_block` 有 Repair 文字；`rejected_json` 在 C++ 仍偏瘦（缺 clause 細節）→ retry 品質有限。

**不是主因：** `batch_timeouts=2`、schema 通道。

---

## 改進計劃（Phase Q → Q′）

### 階段 Q0 — 歸檔分析（1–2 天，**先做**）

| Task | 動作 | 產出 |
|------|------|------|
| Q0.1 | 拉 **24 案 req=0 timeout** 清單 + baseline wall | `phase_a_regression_24.csv` |
| Q0.2 | 對 **13 accept 案** + **p040** 讀 `requests.jsonl` / `responses.jsonl` | 成功 block 長相 |
| Q0.3 | 對 **10 案高 rejected_initial**（req≥10, acc=0）抽樣 witness | init witness ref 分布 |
| Q0.4 | 2 案 `batch_timeout` 對照 `llm_log.jsonl` latency | 確認是否 sidecar 慢 |

**腳本：** `scripts/analyze_accept_diagnosis.py`（D0–D5 報告輸出至 `diagnosis/`）。

```bash
python3 scripts/analyze_accept_diagnosis.py --phase all
```

**成功標準（修訂）：** accept/request **≥ 40%**（p040 子集先行）；全量需 D4 go/no-go 後再評。

### 階段 Q1 — 牆鐘回歸（與 accept 分開）

**問題：** 24 案無 LLM 仍 timeout → 不能拿現有 CSV 評 algorithm validity。

| Task | 動作 |
|------|------|
| Q1.1 | **單開重跑** 24 案（`--parallel 1`，同 timeout）→ 區分 CPU 競爭 vs 本質變慢 |
| Q1.2 | 若單開可解 → Phase A′ 用 **`--parallel 4`** 或 **timeout 1500s** 重測子集 |
| Q1.3 | 若單開仍 timeout → 查 IC3+`async-cti` 無 flush 路徑開銷（profiling） |

**成功標準：** 24 案中 ≥80% 恢復 baseline result → 才解讀 accept 率。

### 階段 Q2 — 拉高 accept（prompt / 協議，不擴 expressiveness）

對齊 [`frame_snapshot_quality_plan.md`](frame_snapshot_quality_plan.md) Track B：

| Task | 動作 | 預期 |
|------|------|------|
| Q2.1 | Prompt：**明確禁止**「在 init 為 true 的 literal」進 block；附 1–2 個 rejected_initial 反例 | ↓ rejected_initial |
| Q2.2 | C++ feedback：`rejected_json` 帶 **失敗 clause 的 disjuncts** + `clause_idx` | retry 更準 |
| Q2.3 | 要求 **更窄** clause：優先 **單 disjunct**、digest top-1 literal 的 **negation** | ↑ accept |
| Q2.4 | `max_block_clauses` 暫改 **1**（A/B 對照）→ 減少 3 條雷同廢案 | 量測 accept/request |
| Q2.5 | p040 **專項** smoke + 10 案高 reject 子集重跑 | 快速迭代 |

**成功標準（子集）：** `accept/request` 從 1.75% → **≥5%**；`rejected_initial/request` 從 0.73 → **≤0.4**。

### 階段 Q3 — Expressiveness（Gate 0 觸發後）

若 Q2 後 `induction_fail` 仍高、witness 需 bitmask：

→ 啟動 [`lemma_expressiveness_roadmap.md`](lemma_expressiveness_roadmap.md) **X1**（`refine_predicate` 接入）。

---

## 建議執行順序

```
Phase A 已完成
  → Q0 歸檔報告（本文件任務）
  → Q1 24 案單開重跑（牆鐘）
  → Q2 prompt/feedback 迭代（p040 + 10 案）
  → 若仍低 accept → Q3 X1
  → 再跑 Phase A′ 或 Phase B
```

**暫不建議：** 直接跑 Phase B（665 timeout 案）— 在 Phase A 牆鐘與 accept 未釐清前，B 的解讀成本高。

---

## 決策點

| 若 Q1 發現… | 則… |
|-------------|-----|
| 單開可解、8 開不行 | 實驗改 `--parallel 4`；報告註明資源模型 |
| 單開仍不行 | 查 `async-cti` 無 API 路徑；可能需修 C++ |
| Q2 rejected_initial 明顯下降 | 全量 Phase A′ |
| induction_fail 仍主導 | 排程 X1 |

---

## 附錄：Phase A 有 accept 的案（13）

`microban_110`(5), `zipcpu-zipmmu-p12`(2), `a10-p06`(2), `qspiflash_divthree-p46`(2), 其餘 9 案各 1。  
多為 **zipcpu / microban / 小型 qspiflash** — 與「control-heavy、cube-like」假設一致。
