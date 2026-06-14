# LLM Semantic Guidance for IC3 — Implementation Plan v2

**狀態：** 🟢 Active  
**日期：** 2026-06-14  
**取代：** Q2/Q3/Q4 reactive per-CTI blocking（0% accept，已刪除）

---

## 一句話策略

> **LLM 不猜 bit-level literal；LLM 看電路語意、生成 invariants，C++ 做所有 formal 驗算。**

---

## 為什麼之前的方向沒用

| 舊架構問題 | 根因 |
|-----------|------|
| per-CTI reactive：每個 CTI 問一次 LLM | 4-6s × 數千 CTI = 不可行 |
| 輸入是 `state512`, `state798` | LLM 對匿名 ref 沒有 domain knowledge |
| 輸出要 bit-level literal 值 | 必須猜對具體值才過 SAT；LLM 做不到 |
| 驗算：per-CTI reject | 槓桿 = 1（blockl 一個 CTI） |
| prompt 語意反轉 | `clause_false_at_init` 問反了 |

**新方向的槓桿：一個 invariant 消滅幾百個 CTI，LLM 只需一次 API call。**

---

## 架構：四個 Stage

```
Stage 0  Pre-flight（IC3 啟動前）
  RTL 語意 bundle → LLM → 10-20 個候選 invariants → C++ 批次驗算 → 注入 F0

Stage 1  IC3 正常執行（含監控）
  IC3 正常跑，同時監控三個觸發條件：
    T1: CTI cluster density（同 frame 連續相似 CTI）
    T2: Frame clause plateau（連續 R 輪無新 clause）
    T3: Frame clause budget exceeded

Stage 2  Mid-run 同步引導（任一條件觸發）
  現場証據 bundle → LLM → Type 1/2/3 候選 → C++ 驗算 → 注入
  注入後：重置 cooldown，繼續 Stage 1

Stage 3  迴圈
  如果再次卡住 → 回到 Stage 2（有 cooldown 避免連續觸發）
```

---

## 三種 LLM 輸出類型

| 類型 | 用途 | C++ 處理 |
|------|------|----------|
| **Type 1: 新 invariant** | 直接消滅 CTI cluster | `constrain_frame(0..K, predicate)` |
| **Type 2: clause lifting** | 把 N 個具體 clause 合併為 1 個更強的表達 | 替換現有 frame clauses |
| **Type 3: IC3IA predicate** | 增加抽象 predicate，讓 IC3IA 精化 | `add_predicate(predicate)` |

---

## 可復用的現有代碼

| 模組 | 路徑 | 復用方式 |
|------|------|---------|
| JSONL IPC 協議 | `jsonl_protocol.py` | 完全不動，新加 request type |
| LLM API client | `llm_client.py` | 完全不動 |
| 環境設定 | `env_config.py` | 完全不動 |
| Sidecar 輪詢主迴圈 | `sidecar.py` | 已清理為乾淨 shell，加 handler 即可 |
| `constrain_frame` | `engines/ic3base.cpp` | 注入 invariant 的核心路徑 |
| `is_init_safe_block_disjuncts` | `engines/ic3base.cpp:1062` | Init check 復用 |
| `rel_ind_check` | `engines/ic3base.cpp:577` | Induction check 復用 |
| `serialize_frame_snapshot_json` | `engines/ic3base.cpp:2020` | Frame clause 序列化 |
| `build_cti_digest` | `engines/llm_generalizer.cpp` | CTI cluster 統計 |
| `write_benchmark_context` | `engines/llm_generalizer.cpp` | symbol_registry 輸出 |
| `symbol_registry` | `engines/llm_generalizer.h` | Verilog 名稱對應 |
| `benchmark_context.json` | C++ 輸出 | Stage 0 RTL 語意來源 |

---

## JSON Schemas

### Stage 0 Request（`ic3_stage0_request`）

```json
{
  "type": "ic3_stage0_request",
  "request_id": "stage0_vgasim_p040",
  "benchmark": "vgasim_imgfifo-p040",
  "property_desc": "imgfifo output never exceeds valid count",
  "hot_variables": [
    {"ref": "state512", "verilog": "imgfifo_wr_ptr", "width": 13, "init": "0"},
    {"ref": "state798", "verilog": "imgfifo_rd_ptr", "width": 13, "init": "0"},
    {"ref": "state21",  "verilog": "imgfifo_count",  "width": 14, "init": "0"}
  ],
  "transition_sketch": [
    "if (wr_en && !full): imgfifo_wr_ptr' = imgfifo_wr_ptr + 1",
    "if (rd_en && !empty): imgfifo_rd_ptr' = imgfifo_rd_ptr + 1",
    "imgfifo_count' = imgfifo_wr_ptr' - imgfifo_rd_ptr'"
  ]
}
```

### Stage 2 Request（`ic3_stage2_request`）

```json
{
  "type": "ic3_stage2_request",
  "request_id": "stage2_f3_t42",
  "trigger": "T2_plateau",
  "proof_state": {
    "current_frame": 3,
    "frames_stuck_rounds": 12,
    "total_cti_count": 89,
    "frame_clause_count": 47
  },
  "hot_variables": [ /* 同 stage0 */ ],
  "cti_cluster": [
    {"verilog": {"imgfifo_wr_ptr": 7, "imgfifo_rd_ptr": 4, "imgfifo_count": 3}},
    {"verilog": {"imgfifo_wr_ptr": 9, "imgfifo_rd_ptr": 6, "imgfifo_count": 3}}
  ],
  "frame_clause_clusters": [
    {"pattern_desc": "count=3 variations", "count": 12,
     "example_verilog": "imgfifo_count≠3 ∨ imgfifo_rd_ptr≠4"}
  ],
  "previously_injected": ["imgfifo_count < 8"]
}
```

### Response（兩種 request 共用）

```json
{
  "type": "ic3_invariant_response",
  "request_id": "stage2_f3_t42",
  "candidates": [
    {
      "id": 1,
      "kind": "Type1_invariant",
      "verilog_expr": "imgfifo_count == imgfifo_wr_ptr - imgfifo_rd_ptr",
      "predicate_ast": {"op": "eq",
        "lhs": {"ref": "state21"},
        "rhs": {"op": "sub", "lhs": {"ref": "state512"}, "rhs": {"ref": "state798"}}},
      "intuition": "count tracks wr_ptr minus rd_ptr"
    },
    {
      "id": 2,
      "kind": "Type2_lift",
      "subsumes_pattern": "count=3 variations",
      "verilog_expr": "imgfifo_count + imgfifo_rd_ptr <= imgfifo_depth",
      "predicate_ast": { "op": "ule", "lhs": {"op": "add", ...}, "rhs": {...} },
      "intuition": "unify 12 specific clauses"
    },
    {
      "id": 3,
      "kind": "Type3_predicate",
      "verilog_expr": "imgfifo_full == (imgfifo_count >= imgfifo_depth)",
      "predicate_ast": { "op": "eq", ... },
      "intuition": "full signal semantics"
    }
  ]
}
```

---

## C++ 實作計劃

### 改動 1：Stage 0 觸發（`llm_generalizer.cpp`，~80 行）

位置：`IC3Base::initialize()` 結尾，IC3 主迴圈開始前。

```cpp
if (llm_gen_ && llm_gen_->has_stage0_enabled()) {
    string req_json = llm_gen_->build_stage0_request_json(
        property_desc_, init_raw_json_          // 從現有 field 取
    );
    llm_gen_->write_jsonl_request(req_json);    // 寫 JSONL
    llm_gen_->sync_wait_and_apply_invariants(); // 同步 poll + 注入
}
```

`build_stage0_request_json()`：
- `hot_variables`：從 `symbol_registry_` 取 Verilog 名稱 + width + init value
- `transition_sketch`：從 BTOR2 next-state equations 轉為 pseudo-code（每個 hot var 一行）
- Hot variables = 出現在 `init_raw_json_` 的前 N 個 ref

### 改動 2：Stage 2 觸發條件（`ic3base.cpp`，~100 行）

位置：`IC3Base::block_all()` 每輪 flush 後，或主迴圈 frame 推進失敗時。

```cpp
bool should_trigger = false;
string trigger_reason;
size_t fi = frontier_idx();

if (llm_gen_->cti_cluster_density(fi) >= LLM_CLUSTER_THRESHOLD) {
    should_trigger = true; trigger_reason = "T1_cluster";
}
if (llm_gen_->frames_stuck_rounds() >= LLM_STUCK_ROUNDS) {
    should_trigger = true; trigger_reason = "T2_plateau";
}
if (frames_.at(fi).size() >= LLM_CLAUSE_BUDGET) {
    should_trigger = true; trigger_reason = "T3_budget";
}

if (should_trigger && !llm_gen_->stage2_cooldown_active()) {
    string req = llm_gen_->build_stage2_request_json(fi, trigger_reason);
    llm_gen_->write_jsonl_request(req);
    llm_gen_->sync_wait_and_apply_invariants();
    llm_gen_->reset_stage2_cooldown(LLM_COOLDOWN_CTIS);
}
```

### 改動 3：Response 處理（`llm_generalizer.cpp`，~150 行）

`sync_wait_and_apply_invariants()`：
1. Poll `resp_path_` 直到看到 `request_id` 匹配的 response（最多 `LLM_TIMEOUT_MS`）
2. 對每個 candidate：
   - `parse_predicate_ast(cand["predicate_ast"])` → `Term`
   - `is_init_safe_from_predicate(term)` → init check
   - **Type 1 / Type 2**：`constrain_frame(0, term)` 注入 F0
   - **Type 3**：`try_apply_llm_refine_predicate(term)` 傳給 IC3IA
3. 更新 stats：`num_stage0_injected`, `num_stage2_triggered`, `num_stage2_accepted`

### 新 field/method 清單（`llm_generalizer.h`）

```cpp
// State
bool stage0_enabled_ = false;
int  stage2_cooldown_remaining_ = 0;
int  frames_stuck_rounds_ = 0;
string last_invariant_request_id_;

// Methods
string build_stage0_request_json(const string& property_desc, const string& init_raw);
string build_stage2_request_json(size_t frame_idx, const string& trigger_reason);
void   write_jsonl_request(const string& req_json);
void   sync_wait_and_apply_invariants();
bool   stage2_cooldown_active() const;
void   reset_stage2_cooldown(int cooldown_ctis);
int    cti_cluster_density(size_t frame_idx) const;
int    frames_stuck_rounds() const;
```

---

## Python 實作計劃

### 新檔：`llm_worker/invariant_sidecar.py`（~200 行）

```python
# handle_stage0_request / handle_stage2_request 的具體實作
# 由 sidecar.py import

def handle_stage0_request(client, request):
    prompt = build_stage0_prompt(request)
    text, tokens, latency_ms = client.call(
        prompt,
        system_prompt=INVARIANT_SYSTEM_PROMPT,
        reasoning_effort="low",
    )
    candidates = parse_invariant_response(text)
    return {
        "type": "ic3_invariant_response",
        "request_id": request["request_id"],
        "candidates": candidates,
        "_token_count": tokens,
        "_latency_ms": latency_ms,
    }

def handle_stage2_request(client, request):
    # 同上，但 prompt 包含 CTI cluster + frame clause evidence
    ...
```

### 新檔：`llm_worker/invariant_prompt.py`（~150 行）

**Stage 0 System Prompt：**
```
你是硬體驗證專家。給定電路語意和待驗 property，
列出 10-15 個候選不變量（invariants）。
- 只用 state variables（不含 input）
- 用 predicate_ast 格式輸出（JSON array）
- 每個附 verilog_expr（可讀）和 intuition（直覺說明）
- kind 選: Type1_invariant, Type2_lift, Type3_predicate
```

**Stage 2 User Prompt 核心：**
```
IC3 在 frame {N} 卡住了（{M} 輪無進展）。
觸發原因：{trigger}

觀察到的 CTI cluster（{K} 個 CTI，Verilog 名稱）：
{cti_cluster}

Frame clause 分布（{N} 個 clause）：
{frame_clause_clusters}

已注入過的 invariants：{previously_injected}

請分析這些 CTI 的共同模式，提供：
- Type1: 能消滅這個 cluster 的 invariant
- Type2: 能統合分散 clause 的更強表達式
- Type3: IC3IA predicate 建議（可選）
```

### 修改：`sidecar.py`（已完成）

```python
from invariant_sidecar import handle_stage0_request, handle_stage2_request
```
在 `handle_stage0_request` / `handle_stage2_request` 實作完成後，替換掉 stub。

---

## 檔案清單

| 檔案 | 動作 | 估計規模 |
|------|------|---------|
| `llm_worker/sidecar.py` | 已清理為 shell ✅ | 200 行 |
| `llm_worker/invariant_sidecar.py` | **新建** | ~200 行 |
| `llm_worker/invariant_prompt.py` | **新建** | ~150 行 |
| `engines/llm_generalizer.h` | 新 fields + method 宣告 | +50 行 |
| `engines/llm_generalizer.cpp` | Stage 0/2 request building + response handling | +300 行 |
| `engines/ic3base.cpp` | Stage 2 觸發條件 | +80 行 |
| `engines/ic3_frame_ast.cpp` | `parse_predicate_ast` from JSON | +100 行（可能已有基礎） |

---

## 實作順序

### Week 1 — Minimum Viable Path

```
Day 1-2  Python 先行（不需要 C++）
  - invariant_prompt.py：Stage 0 prompt builder
  - invariant_sidecar.py：handle_stage0_request
  - 手動測試：把 p040 的 benchmark_context.json 當 Stage 0 request 輸入，
    確認 LLM 輸出是 Verilog 名稱的 candidates，不是 stateNN

Day 3  Stage 0 C++ request building
  - llm_generalizer.cpp: build_stage0_request_json
    （hot_variables from symbol_registry + init values）
  - 手動 trigger：在 initialize() 加 flag --llm-stage0
  - smoke: pono 啟動 → request JSONL 出現 → sidecar 回應 → response JSONL 出現

Day 4  Response parsing + injection
  - parse_predicate_ast()（JSON → IC3 Term）
  - sync_wait_and_apply_invariants()：init check + constrain_frame
  - Smoke metric: 有幾個 candidate 通過 init check？有幾個通過 rel_ind?

Day 5  A/B 量測 Stage 0
  - 對 p040：有/無 Stage 0 injection 的 CTI 數、frame 數、wall clock
  - Go/no-go decision
```

### Week 2 — Stage 2 Mid-run（如果 Stage 0 A/B 通過）

```
Day 6  Stage 2 Python
  - invariant_prompt.py: build_stage2_prompt（加 CTI cluster + frame evidence）
  - invariant_sidecar.py: handle_stage2_request

Day 7  Stage 2 C++ trigger conditions
  - ic3base.cpp: T1/T2/T3 trigger detection + cooldown
  - llm_generalizer.cpp: build_stage2_request_json（CTI cluster in Verilog names）
  - Smoke: p040 跑到卡 → Stage 2 trigger log 出現

Day 8-10  量測 + 調整
  - A/B: 有/無 Stage 2 的差異
  - Adjust: 調整 threshold（T2 plateau rounds, T3 budget）
  - Scale: 2-3 個其他 benchmark
```

---

## Go / No-go 標準

| 指標 | 目標 | 意義 |
|------|------|------|
| Stage 0 候選 init_safe 率 | ≥ 30% | LLM 生成的 invariant 有基本品質 |
| Stage 0 候選 inductive 率 | ≥ 10% | 通過完整驗算 |
| Stage 0 後 CTI 數下降 | ≥ 15% | Pre-flight injection 有效 |
| Stage 2 後 CTI 數下降 | ≥ 10% | Mid-run guidance 有效 |
| Type 2 lift 成功 | ≥ 1 次/run | Clause 合併機制有作用 |
| Wall clock 增加 | ≤ 20% | LLM latency 可接受（同步模式） |

**爆發性成功：** 有 HWMCC benchmark 因 invariant injection 而首次在時限內 solve。

---

## 停損條件

- 10 個 benchmark 試下來 init_safe 率 < 10%（LLM 不了解 init semantics → 換 prompt 策略）
- CTI elimination 在所有 benchmark < 2%（invariant 太弱 → 換 schema 或加條件）

---

## Agent 須知

1. **Commit 後 push**：每次 commit 後 `git push origin main`
2. **新 smoke 基準**：`scripts/smoke_semantic_invariant.sh`（待建）
3. **不要**跑舊的 `ab_q*` 腳本（已刪除）
4. **不要**再動 per-CTI blocking clause 路線
5. **Stage 0 先做**：驗證 LLM 輸出品質再做 Stage 2
