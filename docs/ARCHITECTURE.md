# Pono + LLM 架構說明

## 整體流程

```
pono (C++)                                    sidecar (Python)                    LLM API
─────────                                    ────────────────                    ───────
IC3/IC3IA 執行中
  │
  ├─ reaches_bad() 找到 bad reachable
  │   └─ capture_cti_context()
  │       └─ collect_cti_literals()    提取 cube 中每個 literal 的 varname + value
  │       └─ write_cti_context()  ────JSONL────→  sidecar.py poll
  │                                                     │
  │                                              DeepSeekClient.call(model=...)
  │                                                     │
  │                                              ────HTTP POST───→  deepseek-v4-pro
  │                                              ←── JSON resp ────
  │                                                     │
  │                                              write_response()  ──JSONL──→  resp.jsonl
  │                                                                          (candidate)
  ├─ process_llm_candidates()
  │   ├─ poll_candidates()    ←──JSONL── 讀 resp.jsonl, parse candidate
  │   ├─ validate_llm_candidate()
  │   │   ├─ schema_ok?  必備欄位存在
  │   │   ├─ parse_ok?   (cube-subset 總是 true)
  │   │   ├─ vocab_ok?   符號存在於 transition system
  │   │   └─ budget_ok?  未超過 accepted_budget
  │   ├─ cube_subset_to_blocking()  將 LLM keep/drop list 轉成 IC3Formula
  │   ├─ rel_ind_check()            驗證 inductive relative to frame
  │   └─ constrain_frame()          ✅ 插入 frame
  │
  └─ 繼續 IC3 主迴圈
```

## 檔案架構

```
pono-llm/
├── engines/
│   ├── llm_generalizer.cpp/h   ← C++ LLM 通訊層 (JSONL 讀寫、candidate parse、統計)
│   ├── ic3base.cpp/h           ← IC3 主迴圈 + LLM hook (CTI 捕獲、candidate 驗證、插入)
│   ├── ic3.cpp                 ← bit-level IC3 的 CTI 捕獲
│   └── ic3ia.cpp               ← IC3IA 的 CTI 捕獲 (refinement hook)
├── llm_worker/
│   ├── sidecar.py              ← 主程式：poll JSONL requests, 呼叫 LLM, 寫 JSONL responses
│   ├── deepseek_client.py      ← DeepSeek API client (OpenAI-compatible)
│   ├── jsonl_protocol.py       ← JSONL 讀寫輔助
│   └── prompts/
│       ├── cube_subset.txt     ← cube-subset 模式的 prompt template
│       └── qf_smt.txt          ← qf-smt 模式的 prompt template
├── scripts/
│   └── run_benchmarks.py       ← 統一 benchmark runner (test/download/baseline/llm/report)
├── options/
│   ├── options.h               ← CLI 參數定義 (engine, llm-gen-mode, llm-model, ...)
│   └── options.cpp             ← CLI 參數解析
├── pono.cpp                    ← 主程式：engine 選擇 + LLMGeneralizer 初始化
├── test_sidecar.py             ← sidecar 整合測試 (含真實 LLM API call)
└── docs/
    ├── ARCHITECTURE.md          ← 本文件
    ├── BUG_ANALYSIS.md          ← 已知 bug 分析與修復記錄
    └── 0514_async_ic3ia.md      ← 初始設計文件
```

## CTI 捕獲點 (capture_cti_context)

| 位置 | 觸發時機 | 涵蓋 engine |
|------|---------|------------|
| `ic3base.cpp:413` | `reaches_bad()` 發現 frontier 可到達 bad | 所有 IC3 變體 (IC3, IC3IA, MBIC3, ...) |
| `ic3.cpp:104` | bit-level IC3 的 `predecessor_generalization()` | IC3 (bit-level) |

## Candidate 處理點 (process_llm_candidates)

| 位置 | 觸發時機 |
|------|---------|
| `ic3base.cpp:177` | `check_until()` 每個 iteration 開始前 |
| `ic3base.cpp:453` | `step()` 中 `block_all()` 完成後 |
| `ic3base.cpp:643` | `block_all()` 內部每 50 個 proof goal |

## 資料格式

### Request (pono → sidecar)

JSONL，一行一個 CTI context：

```json
{
  "frame_idx": 5,
  "property": "<bad property name>",
  "literals": [
    {"varname": "x", "value": "true"},
    {"varname": "y", "value": "false"}
  ],
  "candidate_language": "cube-subset",
  "model": "deepseek-v4-pro"
}
```

- `varname`: IC3 中 literal 的變數名（bit-level IC3 為 boolean var；IC3IA 為 SMT expression）
- `value`: `"true"` 或 `"false"`，根據 literal 正負極性

### Response (sidecar → pono)

JSONL，一行一個 candidate lemma：

```json
{
  "type": "cube_subset",
  "frame_hint": 5,
  "keep_literals": ["x = true"],
  "drop_literals": ["y = false"],
  "rationale": "x 是核心條件，y 是附帶細節"
}
```

## Candidate 驗證管線

```
poll_candidates() → for each candidate:
  ├─ schema_ok?    (keep_literals 或 drop_literals 非空)
  ├─ parse_ok?     (cube-subset 總是 true; qf-smt 未實作)
  ├─ vocab_ok?     (used_symbols 存在於 ts)
  └─ budget_ok?    (num_accepted < llm_accepted_budget)
        │
        ▼
  cube_subset_to_blocking()
        │  從 keep_literals 提取純變數名（去掉 " = value" 後綴）
        │  比對原始 CTI cube children，保留匹配的 literal
        │  產出 disjunction IC3Formula (blocking clause)
        │
        ▼
  blocking.children 非空？
        │
        ▼
  rel_ind_check(target_frame, negated_blocking, ...)
        │  驗證 F[frame-1] ∧ T ∧ ¬blocking' 為 unsat
        │  (blocking clause 對該 frame 是 inductive)
        │
        ▼
  constrain_frame(frame, blocking)  ← ✅ 插入
```

## CLI 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--llm-gen-mode` | `none` | `async-cti` 啟用 LLM generalization |
| `--llm-candidate-language` | `cube-subset` | candidate 格式 (`cube-subset` / `qf-smt`) |
| `--llm-model` | `deepseek-v4-pro` | 模型名，會寫入 JSONL request 傳給 sidecar |
| `--llm-accepted-budget` | `50` | 最多接受幾個 LLM lemma |
| `--llm-req-path` | `/tmp/pono_llm_requests.jsonl` | request 輸出檔案 |
| `--llm-resp-path` | `/tmp/pono_llm_responses.jsonl` | response 讀取檔案 |
| `--llm-log` | `/tmp/pono_llm_log.jsonl` | LLM 互動 log |

### benchmark runner 額外參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--llm-max-requests` | `0` (無限) | 每個 benchmark 最多送幾個 LLM request |
| `--llm-model` | `deepseek-v4-pro` | 同時傳給 sidecar `--model` |
| `--parallel` | `4` | 平行 worker 數，每個有自己的 sidecar |

## 模型傳遞鏈

```
--llm-model (pono CLI)
    │
    ├─→ C++ opts_.llm_model_
    │       └─→ write_cti_context() 寫入 JSONL request 的 "model" 欄位
    │               └─→ sidecar 從 request 讀取 model，優先使用
    │
    └─→ --model (sidecar CLI, benchmark runner 傳遞)
            └─→ sidecar 作為 fallback (request 無 model 時使用)
                    └─→ DeepSeekClient.call(model_name=...)
```

## LLM Stats 輸出格式

pono 結束時輸出機器可讀行到 stderr：

```
LLM_STATS accepted=3 rejected=12 errors=0 requests=47 candidates=15 schema_fail=0 parse_fail=0 vocab_fail=0 induction_fail=12 subsumption_fail=0 budget_skip=0
```

benchmark runner 解析此行填入 CSV。

## Offline LLM Repair Replay

Offline replay is the experimental path for testing whether LLM proposals can become solver-accepted IC3/PDR lemmas without blocking the live IC3 loop on LLM latency.

Workflow:

```text
1. Pono offline-dump
   -> static_context.json
   -> cti_contexts.jsonl

2. Python propose
   -> proposals.jsonl

3. Pono offline-check
   -> proposal_replay_results.jsonl
   -> repair_requests.jsonl

4. Python repair
   -> repairs.jsonl

5. Pono offline-check
   -> repair_replay_results.jsonl

6. Python summarize
   -> summary.json
```

The static context is heuristic prompt input only. Every accepted lemma is checked by Pono with the full transition relation and the live PDR frame sequence.

Example:

```bash
REPLAY=llm_replay/foo
build/pono -e ic3ia --llm-gen-mode offline-dump --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py propose --replay-dir "$REPLAY" --model deepseek/deepseek-v4-pro
build/pono -e ic3ia --llm-gen-mode offline-check --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py repair --replay-dir "$REPLAY" --model deepseek/deepseek-v4-pro
build/pono -e ic3ia --llm-gen-mode offline-check --llm-replay-dir "$REPLAY" foo.btor2
python3 llm_worker/offline_repair_driver.py summarize --replay-dir "$REPLAY"
```

---

# Phase 2: Template-Guided Semantic Lemma Generation (Design)

## 方向轉變

Phase 1 的 cube-subset approach（LLM 從單一 CTI cube 挑 subset）已證明瓶頸：
LLM 做的是 correlation（找共通 literal），不是 causality（找 inductive invariant）。
所有 candidate 在 `rel_ind_check` 失敗。

Phase 2 改為 **template-guided semantic lemma generation**：
LLM 不再挑 CTI subset，而是依照固定 lemma schema 生成全新的 semantic lemma，
目標是一次 subsume 多個 frame clause，減少 clause 數量、加速 IC3 收斂。

## Lemma Schema（LLM 允許的語法）

```
1. Range:          lo <= x <= hi
2. Equality:       x = y, x != y
3. Offset:         x = y + c, x <= y + c
4. Bit-slice:      x[hi:lo] = c, x[hi:lo] = y[hi:lo]
5. Mutual exclusion:  !(a && b), at_most_one(a, b, c)
6. Mode implication:  mode = M => constraint
7. Guarded invariant: guard => relation
8. Counter summary:   enable => next(x) = x + 1
```

禁止：quantifiers, arrays, memory select/store, arbitrary nested BV。

## LLM Context Bundle

不再只給 CTI cube。Prompt 包含：

| Component | Purpose |
|-----------|---------|
| Target property | 要證明什麼 |
| Hot variables | CTI 相關信號及其語意含義 |
| Transition slice (pseudo-code) | relevant next-state logic |
| CTI batch | 多個 CTI，標注 common/varying literals |
| Frame clause clusters | 可被 subsume 的 clause 群組 |
| Lemma memory | 過去 accepted/rejected 的 candidate |

## 三層 Validation Gate

```
LLM candidate
  → syntax/type check
  → BMC shallow check (Init ∧ T^0..d ∧ ¬lemma, d=3-5)
  → relative induction check (F_k ∧ lemma ∧ T ∧ ¬lemma')
   → subsumption check (count clauses replaced)
```

---

# Phase 2 Progress (2026-05-25)

## MVP v0.5 Results

**Pipeline**: context dump → template-guided prompt → LLM candidates → cheap validation → manual inspection.

**Key finding**: Enriched context (design_context + predicate role tags) shifts LLM behavior:

| Context | LLM Lemma | Schema | Variables | Type |
|---------|-----------|--------|-----------|------|
| None (Task 7) | `input10 = state434` | equality | input+state | CTI literal |
| Enriched (Task 12) | `(not (= state434 #b1))` | disequality | state-only | State predicate |

**New files**:
- `llm_worker/run_mvp.py` — MVP driver (context dump → LLM → validate → report)
- `llm_worker/lemma_schema.py` — 8 allowed lemma families
- `llm_worker/template_prompt.py` — context bundle prompt builder
- `llm_worker/clause_cluster.py` — predicate clustering with role tags
- `llm_worker/transition_slice.py` — hot variable extraction + design context

**Next**: Transition slice extraction from IC3IA SMT, manual rel_ind_check, repair loop.

## Clause Clustering 前處理

把 frame 中共享 predicate label 的 clause 分群，找 common core vs varying details。
送到 LLM 時不只給 raw clause，而是給 cluster summary：
「這些 clause 都在約束 mode=BUSY 且 req=1 的 state，差異只在 cnt 的 bound 不同」

## LLM Output Format

```json
{
  "candidates": [{
    "lemma": "(=> (= mode IDLE) (= valid 0))",
    "lemma_type": "mode implication",
    "intuition": "valid is only raised when request is accepted; IDLE clears it",
    "expected_subsumed_cluster": "cluster_3",
    "variables_used": ["mode", "valid"],
    "risk_level": "medium"
  }]
}
```

## MVP 計畫

1. 挑一個 benchmark，手動 dump context bundle
2. 讓 LLM 產生 5-10 個 candidate lemma
3. 跑 formal gate（parse → BMC → induction → subsumption）
4. 記錄成功/失敗統計
