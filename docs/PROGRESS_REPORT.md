# Pono + LLM Lemma Generalization — 開發進度報告

> 2026-05-25 | Branch: `feature/llm-ic3ia-generalization`

## 1. 目標

在 pono 的 IC3IA（word-level CEGAR model checker）中加入 LLM-guided lemma generalization。利用 DeepSeek V4 Pro 從 CTI（counterexample-to-induction）cube 中識別核心 literal，丟棄附帶細節，產生更 general 的 blocking clause。目標是減少 IC3IA 的 refinement/bocking phase 次數，加速收斂。

## 2. 已完成架構

### 整體流程
```
IC3IA 主迴圈
  ├─ reaches_bad() → capture_cti_context()
  │    ├─ simplify_cti_literal()     SMT → 人可讀 infix (Extract→x[3:0], BVUgt→>)
  │    ├─ buffer_cti_context()       同 frame CTI 合併
  │    └─ store_cti_cube_for_frame() per-frame 儲存（無上限）
  │
  ├─ flush_frame_batch()             同 frame CTI 一次送 LLM
  │
  ├─ process_llm_candidates()
  │    ├─ poll_candidates()          JSONL → parse (bracket-counting)
  │    ├─ validate_llm_candidate()   schema/parse/vocab/budget
  │    ├─ find_cti_cube_by_frame()   per-frame lookup (O(1))
  │    ├─ cube_subset_to_blocking()  keep_literals → IC3Formula (rfind extraction)
  │    ├─ check_intersects_initial() 不擋 init state
  │    ├─ rel_ind_check()            驗證 inductive
  │    └─ constrain_frame()          ✅ 插入 frame
  │
  └─ 未匹配 candidate → pending queue → 下次 retry
```

### 關鍵設計決策
- **Multi-CTI batching**：同 frame 多個 CTI 合併送 LLM，讓 LLM 交叉比對找共通 pattern
- **Per-frame storage**：CTI cube 按 frame_idx 索引，candidate 用 frame_hint O(1) 查詢，無 eviction 問題
- **Pending queue**：candidate 來時若對應 cube 未就位，暫存並 retry
- **CTI simplification**：SMT expression tree → 人可讀運算子（Extract→x[3:0], BVUgt→> 等），讓 LLM 理解 literal 語意
- **Precomputed names**：capture 時存 simplified name，candidate matching 時直接用，避免 re-simplify 200+ children 的效能問題

## 3. Bug 修復履歷

| # | 問題 | 修復 |
|---|------|------|
| 1 | `cube_subset_to_blocking`: keep_literals `"varname = value"` vs `ts_.get_name()` 純名不匹配 | extract varname from `"varname = value"` format |
| 2 | `collect_cti_literals`: negated literal value 寫死 `"true"` | detect `get_op() == Not`, set `"false"` |
| 3 | V4 Pro `content` 為空，只讀到空字串 | fallback to `reasoning_content` |
| 4 | `max_tokens=8192` 不夠，JSON 被截斷 | → 32768 |
| 5 | `extract_json` 抓到錯誤的 `{...}` block | search for `"keep_literals"` marker |
| 6 | benchmark runner: LLM stats 只在非 timeout/error 時解析 | always parse |
| 7 | sidecar stderr → DEVNULL，無法診斷 | → file |
| 8 | deque 上限 20，大量 CTI 時舊 cube 被擠出 | → per-frame map（無上限） |
| 9 | FIFO pop 不保證對到 candidate 的 frame | → `find_cti_cube_by_frame(cand.frame_hint)` |
| 10 | `process_llm_candidates` 在 CTI capture 前 poll | → pending queue retry |
| 11 | 沒有 try-catch，crash 殺掉 IC3 loop | → try-catch per candidate |
| 12 | `ic3formula_disjunction`: 空 vector 時 `c.at(0)` crash | guard empty |
| 13 | JSON parser: literal 內的 `[4:4]` 截斷 array parse | bracket-counting with string awareness |
| 14 | `find(" = ")` 抓到 literal 內部的 `=`，varname 提前截斷 | → `rfind(" = ")` |

## 4. 當前狀態

Pipeline 全線貫通，E2E verified：

| 階段 | 狀態 |
|------|------|
| CTI capture → simplify → buffer | ✅ |
| Batch flush → sidecar → V4 Pro → candidate | ✅ |
| JSON parse (bracket-counting) | ✅ |
| varname extraction (rfind) | ✅ |
| Per-frame cube lookup | ✅ |
| Blocking clause construction | ✅ |
| check_intersects_initial | ✅ |
| rel_ind_check (induction) | ❌ 0% pass |

4/4 candidate 通過所有 validation，但全部在 `rel_ind_check` 失敗。

## 5. 瓶頸分析

`rel_ind_check` 驗證：**F[frame-1] ∧ T ∧ (¬blocking)' 是否 UNSAT？** 即 blocking clause 對該 frame 是否為 inductive。

LLM 目前用 multi-CTI batching 找「全部 CTI 共有的 literal」作為 keep。這是 **correlation（找共通點）**，不是 **causality（找 invariant）**。結果：

- LLM keep 的 literal 可以阻擋單一 CTI
- 但從 init state 出發，存在一個 state 讓所有 keep literal 同時成立 → induction 失敗
- 需要更多 literal 來排除這些 reachable state → LLM 選的 keep 不夠充分

## 6. 相關論文

### LLM Lemma / Invariant Generation（最相關）
- **LeGend** (arXiv 2602.24010) — Data-driven lemma generation for hardware model checking
- **CIll** (arXiv 2602.23389) — CTI-guided invariant generation via LLMs for model checking
- **Large Lemma Miners** (arXiv 2511.02521) — Can LLMs do induction proofs for hardware?
- **Not All Invariants Are Equal** (arXiv 2603.15510) — Curating training data for lemma generation with SLMs
- **Quokka** (arXiv 2509.21629) — Accelerating program verification with LLMs via invariant synthesis
- **Neuro-Symbolic Proof Generation** (arXiv 2603.19715) — Scaling systems software verification
- **Loop Invariant Generation** (arXiv 2508.00419) — Hybrid reasoning LLMs + SMT solvers

### LLM Assertion Generation（相關）
- **PALM** (DATE 2026) — LLM methods for SystemVerilog assertions
- **ChatSVA** (arXiv 2604.02811) — SVA generation for hardware verification
- **STELLAR** (arXiv 2601.19903) — Structure-guided LLM assertion retrieval

### LLM + SAT/SMT（相關）
- **Extracting Problem Structure** (arXiv 2501.14630) — LLMs for optimized SAT local search
- **LLM-Guided Quantified SMT** (arXiv 2601.04675) — SMT solving over uninterpreted functions
- **LLM as Combinatorial Solvers** (arXiv 2509.16865) — End-to-end optimization solvers

## 7. 與 offline replay (collaborator's work) 的關係

同一 branch 上有另一個子專案在做 offline LLM replay：CTI 先存檔 → 離線 LLM 處理 → 下次 pono 執行時 replay。我們的 online sidecar 和他們的 offline replay 共享 `LLMGeneralizer` 的 CTI capture/injection 基礎設施（`store_cti_cube_for_frame`, `frame_stored_cubes_`, `cube_subset_to_blocking` 等）。

## 8. 下一步方向

| 方向 | 說明 | 預期效果 |
|------|------|---------|
| **A) Repair loop** | induction SAT witness → LLM「這個 state 漏掉了，加回來」 | 迭代改善 candidate quality |
| **B) 強化 prompt** | 給 LLM transition relation 的部分資訊 | 讓 LLM 推論 causality 而非 correlation |
| **C) Multiple attempts** | 同 batch 多次 LLM call，不同 strategy | 提高命中率 |
| **D) V4 Flash** | 更快的模型（5x tokens/sec），降低 latency | 縮短 feedback loop |
| **E) Bit-level IC3 先行** | boolean variable name → LLM 無理解門檻 | 先證明 pipeline 在簡單場景有效 |
