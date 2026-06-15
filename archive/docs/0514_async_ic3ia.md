> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

# 研究計畫書：基於 IC3-IA 與非同步 LLM 輔助泛化之硬體形式化驗證框架

> **2026-06-03 對齊 IC3 Frame v1：** 線上 CTI → structured JSON → `constrain_frame` / `add_predicate`。  
> Legacy `cube_subset` / Path 1 injection **將直接刪除**。現行規格：[`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)  
> **以下正文為 2026-05-14 原始研究計畫正文（historical），cube-subset / qf-smt 描述已 obsolete。**

**Asynchronous LLM-Guided Generalization for Word-Level IC3-IA in Hardware Model Checking**

**版本日期：2026-05-14**  
**前一版本：plan0428_focused_semantic.md（2026-04-28）**

---

## 摘要與本版重大調整

本計畫於前一版（plan0428）之基礎上，依文獻調研、工具實作可行性分析，以及近期研究方向調整，將研究核心由「LLM 直接產生 lemma / predicate」改為 **LLM 輔助 PDR/IC3-IA 之 lemma generalization**。本版做出以下四項根本性調整：

1. **核心研究問題由 lemma generation 改為 lemma generalization**：傳統 PDR/IC3 的效率高度依賴 CTI blocking 後產生之 lemma 是否足夠泛化。若 lemma 過窄，solver 會反覆處理相似 CTI；若 lemma 能正確概括一類 unreachable states，則可大幅加速 frame 收斂。本研究不讓 LLM 作為可信證明器，而是將其定位為 **untrusted generalization advisor**，根據 CTI、目前 frame、局部 transition cone 與 RTL 語意，提出候選 generalized lemma。
2. **演算法層次提升至 Word-level IC3-IA**：捨棄傳統 bit-level PDR 之 CNF-only 表示，改以 IC3 with Implicit Predicate Abstraction（Cimatti et al., TACAS 2014）為基礎演算法。此舉解決 LLM 自然語意輸出（如 `head < tail`、`state ∈ {IDLE, BUSY}`、`valid -> ready_or_stall`）與 bit-level CNF 之表達層次落差，使 LLM 產出物可逐步由受限 SMT formula 擴展至 word-level generalized lemma。
3. **採用 pono 作為實作基座**：選定 Stanford Centaur 之開源 word-level model checker `pono` 作為修改對象，優先修改其 native IC3/IC3-IA 相關 engine，而非僅使用外部 wrapper。LLM 產生之候選 lemma 必須經由 Pono 內部 SMT solver 完成 parse/type check、frame legality check、relative inductiveness check、subsumption check 後，才可加入對應 frame 或 predicate abstraction domain。
4. **採用 Python sidecar 式非同步生產者-消費者架構**：將 LLM 從 PDR critical path 解耦。Pono 主執行緒只負責蒐集 CTI context、輪詢候選 lemma、驗證與注入；DeepSeek V4 Pro API 呼叫與 prompt 組裝由 Python sidecar 完成。主執行緒不阻塞等待 LLM，候選 lemma 以機會性方式於同步點注入。

---

## 一、研究背景與動機

### 1.1 形式化驗證中反歸納反例之挑戰

在現代積體電路設計中，形式化驗證為確保系統功能正確性之核心手段。底層 SMT/SAT 求解器於執行歸納證明時，常因狀態空間爆炸而遭遇反歸納反例（Counterexample to Induction, CTI），導致證明程序無法收斂。Property Directed Reachability（PDR / IC3, Bradley VMCAI 2011）透過逐 frame 推進與 inductive generalization 自動推導輔助引理（auxiliary lemma），但於高複雜度控制邏輯下仍頻繁因 lemma 探索空間過大而 timeout。

### 1.2 PDR/IC3 中 generalization 之瓶頸

PDR/IC3 的核心並非單純「產生越多 lemma 越好」，而是要從某個 CTI cube 泛化出能排除一整類 unreachable states 的 blocking lemma。若 generalization 過弱，solver 只排除單一或少量狀態，導致大量相似 proof obligations 重複出現；若 generalization 過強，則可能無法通過 relative inductiveness check，不能合法加入 frame。

硬體設計中大量 CTI 具有明顯語意結構，例如：

* valid/ready handshake protocol
* request/grant arbitration protocol
* FIFO empty/full 與 read/write pointer 關係
* FSM legal state encoding
* pipeline stall/flush 控制關係

傳統 syntactic generalization 與 solver-driven unsat core 雖能自動刪減 literal，但不一定能辨識上述硬體語意。本研究之核心假設為：**LLM 可根據 RTL 命名、控制結構與 CTI pattern 提供較具語意的 generalization candidate，而候選結果仍由 SMT solver 嚴格驗證。**

### 1.3 LLM 應用於硬體驗證之主要侷限

**侷限一：語意迷失（Lost in the Middle）**  
工業級 RTL 中龐大之資料路徑（datapath：乘法器、加法器、記憶體陣列）會掩蓋真正影響狀態轉移之控制邏輯。語言模型注意力機制無法有效聚焦於關鍵控制流，導致生成大量無效候選 lemma。

**侷限二：輸出形式錯配（Representation Mismatch）**  
傳統硬體 PDR 採用 bit-level CNF clause 作為 lemma 表示形式，與 LLM 自然產生之 word-level 語意公式（如 `head <= tail`、`state == IDLE -> !busy`）存在表達層次落差。因此本研究選擇 word-level IC3-IA 作為 LLM 與 solver 的共同介面。

**侷限三：LLM 不可作為可信證明器**  
LLM 可能產生語法錯誤、hallucinated signal、過高階 temporal property、或雖然可由 SMT parser 接受但不滿足 transition system 的錯誤 lemma。因此本研究明確規定：LLM 只提供候選泛化，所有候選 lemma 皆須通過 Pono/SMT 端之形式化驗證。

**侷限四：同步耦合導致速度瓶頸**  
若每個 CTI 都同步呼叫 LLM，LLM API 的秒級延遲會放大 PDR 主迴圈延遲。故本研究採用 Python sidecar 非同步架構，將 LLM 呼叫、prompt 組裝、response parsing 與 Pono 主搜尋流程解耦。

### 1.4 本研究之切入角度

本研究借鑑軟體形式化驗證社群之 predicate abstraction 與 IC3 modulo theories 思想，以 word-level formula 作為 LLM 與 solver 之共同語言；並將 LLM 角色從「lemma generator」收斂為「generalization advisor」。LLM 產生之 generalized lemma 不會直接成為系統假設，而是進入 Pono 內部驗證流程：語法檢查、合法 vocabulary 檢查、initial check、frame-relative inductiveness check、subsumption check、以及成本與效益統計。

---

## 二、研究目標與核心貢獻

本計畫之核心目標為：**設計並實作一個非同步 LLM 輔助之 IC3-IA lemma generalization 框架，在不犧牲 soundness 的前提下改善硬體 model checking 之收斂速度與 token 成本效率。**

本計畫之四項核心貢獻如下：

1. **LLM-Guided Lemma Generalization for IC3-IA**  
   將 LLM 由「直接產生可信 lemma」改為「針對 CTI 與現有 frame 提出候選泛化」。Pono 端負責驗證此 lemma 可合法加入哪一層 frame，並在通過 relative inductiveness check 後才注入。此設計使 LLM 的錯誤輸出最多造成額外驗證成本，不會造成 unsound proof。

2. **分階段受限輸出語言（Staged Candidate Lemma Language）**  
   本研究不一開始就允許 LLM 輸出任意 SMT-LIB formula，而採分階段策略：第一階段限制 LLM 只能在 CTI cube literals 中選擇保留/刪除，產生 clause-level generalization；第二階段允許 quantifier-free word-level SMT formula；第三階段再探索受控的 predicate-level relation。此設計兼顧實作可行性、soundness 與研究擴展性。

3. **Python Sidecar 式非同步 LLM-PDR 解耦架構**  
   Pono 主執行緒只負責 IC3-IA 搜尋、CTI context serialization、候選 lemma validation 與 frame insertion；DeepSeek V4 Pro 呼叫由 Python sidecar 負責。此架構使 LLM backend 可替換，並便於記錄 token cost、prompt、response、invalid lemma 比例與實驗重現。

4. **面向 LLM 注意力之語意降維表示**  
   明確區分傳統 COI 分析（目的：縮減 solver 狀態空間）與本研究之語意降維（目的：改善 LLM 對控制邏輯之理解）。系統產出雙軌表示：LLM-friendly 降維 Verilog 與 solver-friendly BTOR2 / Pono transition system，並以 name mapping 串接。

---

## 三、系統架構與技術實作

### 3.1 整體架構

本系統由三個主要元件組成：

1. **Modified Pono IC3-IA Engine**：負責原生 IC3-IA 搜尋、CTI 擷取、候選 lemma 驗證、frame-aware insertion、subsumption check 與統計資料輸出。
2. **Python LLM Sidecar**：負責呼叫 DeepSeek V4 Pro、管理 prompt template、批次處理 CTI context、解析 LLM JSON output、記錄 token cost。
3. **Semantic Reducer**：負責從原始 RTL 產生 LLM-friendly 降維 Verilog、solver-friendly BTOR2，以及 signal name mapping。

系統資料流如下：

```text
Golden RTL + Property
        |
        v
Semantic Reducer
        |-- simplified.v       -> Python LLM Sidecar
        |-- simplified.btor2   -> Pono IC3-IA
        |-- name_map.json      -> formula/signal translation
        |
        v
Modified Pono IC3-IA
        |-- CTI context JSONL  -> Python Sidecar
        |<- candidate lemma JSONL
        |
        v
Validation + Frame Insertion + Statistics
```

### 3.2 語意抽象模型生成（Semantic Datapath Abstraction）

本階段利用 PyVerilog / Yosys 對原始 Golden RTL 進行結構化簡化。需明確區分：傳統 EDA 工具中之 COI 分析以「縮減 solver 狀態空間」為目標；本研究之降維以「最佳化 LLM 注意力機制」為目標。

**實作流程：**

* 追蹤目標斷言之影響錐（Cone of Influence），保留與 property、FSM、handshake、arbiter、FIFO control 相關之訊號。
* 將高位元寬且不影響控制流之資料路徑變數進行摘要化、cut-point 或黑箱化。
* 完整保留有限狀態機（FSM）、控制訊號（`valid` / `ready` / `req` / `ack`）、條件分支邏輯。
* 產生三項輸出：
  1. `simplified.v`：人類可讀之降維 Verilog，供 LLM 閱讀。
  2. `simplified.btor2`：word-level netlist，供 Pono/IC3-IA 執行。
  3. `name_map.json`：Verilog 訊號與 BTOR2/Pono 內部 symbol 之對照表。

### 3.3 LLM 輔助泛化模式（LLM Generalization Modes）

為支援 baseline 與 ablation，本研究在 Pono 中加入少量但必要之 command-line options：

* `--llm-gen-mode=none`：完全關閉 LLM，原生 Pono baseline。
* `--llm-gen-mode=seed-only`：僅於啟動前或初始化階段產生初始候選 lemma / predicate。
* `--llm-gen-mode=async-cti`：完整啟用 CTI-guided asynchronous generalization。
* `--llm-model=deepseek-v4-pro`：指定 LLM backend，預設使用 DeepSeek V4 Pro。
* `--llm-candidate-language={cube-subset,qf-smt,predicate-relation}`：指定 LLM 輸出限制層級。
* `--llm-log=<path>`：輸出 prompt、response、token cost、validation result 與 runtime statistics。

API key 不寫入程式或 log，統一透過環境變數 `DEEPSEEK_API_KEY` 由 Python sidecar 讀取。

### 3.4 分階段候選 lemma 語言

本研究採分階段放寬 LLM 輸出能力。

#### Phase 1：Cube-subset generalization

LLM 不直接輸出任意 SMT formula，而是在 CTI cube 中選擇哪些 literals 應保留，哪些可刪除。Pono 端自行將 generalized cube 轉成 blocking clause。

範例 CTI cube：

```text
valid = true
ready = false
state = BUSY
counter = 3
fifo_empty = false
```

LLM 回傳：

```json
{
  "type": "cube_subset",
  "keep_literals": ["valid = true", "ready = false", "fifo_empty = false"],
  "drop_literals": ["state = BUSY", "counter = 3"],
  "rationale": "counter and exact FSM state appear to be datapath/control-location details; valid-ready-fifo relation is the semantic core."
}
```

Pono 端轉為 candidate clause：

```text
!valid || ready || fifo_empty
```

此階段風險最低，因為 LLM 不需產生完整 SMT expression，只需提供 literal selection 建議。

#### Phase 2：Quantifier-free SMT formula

允許 LLM 產生受限 quantifier-free SMT formula，但禁止：

* quantifier (`forall`, `exists`)
* temporal operator (`eventually`, `until`, `next` 的自然語言形式)
* hallucinated symbol
* 未定義 predicate name
* 超出 solver 支援 theory 的 expression

LLM output 必須為 JSON：

```json
{
  "type": "qf_smt_formula",
  "frame_hint": 4,
  "formula": "(=> valid (or ready stall))",
  "used_symbols": ["valid", "ready", "stall"],
  "rationale": "valid transaction must either be accepted or stalled."
}
```

Pono 端只信任 `type`、`frame_hint`、`formula`、`used_symbols`，`rationale` 僅作為 log。

#### Phase 3：Predicate-level relation

在前兩階段穩定後，進一步允許 LLM 提出 word-level predicate relation，例如 FIFO pointer 與 empty/full 的關係：

```text
fifo_empty == (read_ptr == write_ptr)
```

此階段可與 IC3-IA predicate abstraction domain 更緊密結合，但需更嚴格的 vocabulary check、sort check、relative induction check 與 predicate budget 控制。

### 3.5 Pono 內部修改點與插入位置

本研究優先修改 Pono native IC3/IC3-IA 相關流程。實際檔名與函式名稱可能隨 Pono 版本略有差異，但初步修改範圍如下：

#### 3.5.1 新增 `LLMGeneralizer` 模組

新增 C++ 模組：

* `engines/llm_generalizer.h`
* `engines/llm_generalizer.cpp`

職責：

* 將 CTI、frame index、property、local cone、現有 frame lemma 序列化為 JSONL request。
* 從 Python sidecar 輪詢 candidate lemma JSONL。
* 執行 basic schema validation。
* 將候選 lemma 交給 IC3/IC3-IA validation routine。
* 記錄 request 數、candidate 數、accepted 數、invalid 數、token cost、runtime 等統計。

#### 3.5.2 修改 `engines/ic3.cpp` / `engines/ic3base.cpp`

在 IC3/PDR 主迴圈中加入非阻塞 poll 點：

* 每個 major iteration 開頭。
* 每次處理 proof obligation batch 後。
* propagation 前後。

流程：

```text
poll candidate lemmas
for each candidate:
    parse/type-check
    determine legal frame
    run relative induction check
    run subsumption/redundancy check
    if accepted:
        insert into frame or predicate domain
        log accepted result
```

#### 3.5.3 修改 `engines/ic3ia.cpp`

在 IC3-IA refinement / predicate abstraction 流程加入：

* CTI capture hook：遇到 spurious CEX 或 refinement trigger 時，擷取 CTI context。
* Candidate predicate insertion hook：若候選 lemma 屬於 predicate-level relation，則在通過檢查後加入 abstraction domain。
* 保持原生 refine/interpolant 機制不變，LLM 只提供額外候選，不取代既有流程。

#### 3.5.4 修改 `options/options.{h,cpp}` 與 `pono.cpp`

加入必要參數：

* `llm_gen_mode`
* `llm_model`
* `llm_candidate_language`
* `llm_log_path`
* Python sidecar request/response path

參數保持精簡，主要目的是支援 baseline、ablation 與重現性。

#### 3.5.5 新增 Python sidecar

新增目錄：

* `llm_worker/sidecar.py`
* `llm_worker/prompts/`
* `llm_worker/deepseek_client.py`
* `llm_worker/jsonl_protocol.py`

職責：

* 監聽 Pono 輸出的 request JSONL。
* 批次組裝 CTI prompt。
* 呼叫 DeepSeek V4 Pro。
* 將 response 轉為嚴格 JSON candidate lemma。
* 記錄 token cost、model name、prompt hash、response hash、時間戳。

### 3.6 Candidate lemma validation pipeline

LLM 產生的 candidate 不會直接加入 Pono。每個候選需依序通過以下檢查：

1. **Schema check**：確認 JSON 欄位完整，`type` 與目前 candidate language mode 相符。
2. **Parse/type check**：確認 formula 可由 Pono/smt-switch 解析，且 bit-vector width、Boolean sort、array sort 等型別正確。
3. **Vocabulary check**：確認所有 symbol 皆存在於目前 transition system、property、或已註冊 predicate domain 中。
4. **Initial check**：若 lemma 欲作為 invariant 或加入早期 frame，檢查 `Init => L`。
5. **Frame legality check**：尋找 candidate 可合法加入之 frame `k`，檢查 `F_{k-1} ∧ T => L'`。
6. **Blocking usefulness check**：確認 lemma 至少 block 原始 CTI 或同 batch 中部分 CTI。
7. **Subsumption / redundancy check**：若 candidate 已被既有 lemma 覆蓋，或可覆蓋既有 lemma，則更新 frame lemma set，必要時手動觸發 Pono 的 subsumption/cleanup routine。
8. **Budget check**：限制每個 benchmark 接受之 LLM lemma 數，避免大量正確但無用的 lemma 拖慢 solver。

只有通過上述流程者才可注入 frame 或 predicate domain。

### 3.7 Soundness Guarantee

本系統之 soundness 不依賴 LLM 正確性。LLM 只產生候選泛化，所有候選 lemma 皆由 Pono/SMT 驗證。

核心原則：

* LLM lemma 不可直接作為 transition relation constraint 或 global assumption。
* 若 candidate 要加入 frame `F_k`，必須通過相對歸納檢查。
* 若 candidate 要作為 global invariant，必須通過 initiation 與 consecution 檢查。
* 若 candidate 屬於 IC3-IA predicate abstraction strengthening，必須確保加入 predicate domain 不會改變 concrete transition system，只能細化 abstraction。
* 錯誤 LLM 輸出最多造成 parse failure、validation failure、額外 solver query 或 runtime overhead，不會造成 false proof。

---

## 四、實驗設計與評估指標

實驗分兩階段執行。第一階段聚焦於 internal integration、候選 lemma 語言、validation pipeline 與 Python sidecar；第二階段啟用完整 CTI-guided async generalization 並做正式效能評估。

### 4.1 第一階段（PoC，2026 年中前完成）：受限 generalization 與 Pono 插入機制

**目標：** 驗證 LLM 產生之受限候選泛化可被 Pono 正確解析、驗證並加入 frame，且能在小型 benchmark 上改善 runtime 或降低 CTI blocking 次數。

**範圍限制：**

* LLM candidate language 只使用 `cube-subset`。
* DeepSeek V4 Pro 透過 Python sidecar 呼叫。
* Pono 端先實作 request/response JSONL、validation pipeline、frame insertion 與 logging。
* 可先以 hardcoded / replayed LLM response 測試 Pono 修改正確性，再接上真實 API。

**實作 milestone：**

1. **M1：Pono baseline 建置與量測**  
   Clone/build Pono，跑通 `ic3` / `ic3ia` engine on 小型 BTOR2 benchmark（counter、FIFO、arbiter）。記錄 baseline runtime、timeout、SMT query 數。

2. **M2：Hardcoded generalized lemma injection PoC**  
   手動指定一條已知正確 lemma，測試 parse/type check、frame legality check、relative induction check、frame insertion 與 subsumption cleanup。

3. **M3：`LLMGeneralizer` C++ 模組**  
   新增 JSONL request/response protocol、candidate schema validation、statistics logger。

4. **M4：Python sidecar + DeepSeek V4 Pro**  
   實作 `llm_worker/sidecar.py`、DeepSeek client、prompt template、token cost logging。API key 由 `DEEPSEEK_API_KEY` 讀取。

5. **M5：Cube-subset prompt 與 parser**  
   LLM 輸入 CTI cube、signal description、property、少量 known lemmas；輸出 keep/drop literals。Pono 端轉為 blocking clause。

6. **M6：Semantic reducer 初版**  
   實作 PyVerilog/Yosys 降維流程，產出 `simplified.v`、`simplified.btor2`、`name_map.json`。

**測試標的：** counter、FIFO、round-robin arbiter、valid-ready handshake controller、小型 AXI-lite 控制模組。

### 4.2 第二階段（正式實驗，2026 年底前完成）：CTI-Guided 非同步泛化與成本分析

**目標：** 啟用完整 `async-cti` 模式，驗證 LLM-guided generalization 在中大型硬體 benchmark 上是否能改善證明時間與 token 成本效率。

**實作 milestone：**

1. **M7：CTI capture hook**  
   在 proof obligation / blocking / refine 相關流程擷取 CTI、frame index、failed generalization trace、local cone 與相關 frame lemmas。

2. **M8：非同步 Python sidecar 批次處理**  
   Sidecar 以 batch 方式處理多個 CTI，產生候選泛化。Pono 主流程不等待 sidecar，僅在同步點輪詢結果。

3. **M9：Quantifier-free SMT candidate language**  
   將 LLM 輸出由 `cube-subset` 擴充至 `qf-smt`，允許簡單 implication、equality、bit-vector comparison、Boolean combination。

4. **M10：Subsumption 與 budget control**  
   若 Pono 原生流程未自動清除 redundant lemma，則手動觸發或新增 cleanup routine。加入 accepted lemma budget，避免 lemma pollution。

5. **M11：中大型 benchmark 評估**  
   評估 CVA6 控制模組、AXI4 控制器、FIFO/arbiter family、HWMCC benchmark subset。

### 4.3 Baseline 與比較組

正式實驗比較以下組別：

* **A. Native Pono**：`--llm-gen-mode=none`。
* **B. Seed-only**：只使用啟動階段 LLM 候選 lemma。
* **C. Async CTI + cube-subset**：完整非同步，但候選語言限制在 CTI literal subset。
* **D. Async CTI + qf-smt**：完整非同步，允許 quantifier-free SMT formula。
* **E. Sync CTI ablation**：模擬同步 per-CTI 呼叫，用於比較 async 設計價值。
* **F. No semantic reduction ablation**：餵原始 RTL 給 LLM，檢驗語意降維效果。

### 4.4 評估指標

**主指標：**

1. **Runtime / wall-clock proof time**：核心效能指標，包含 Pono 端驗證與候選 lemma 處理成本。LLM API latency 在主要實驗中可另外標示，因 sidecar 與非同步化可進一步最佳化。
2. **Token cost**：每個 benchmark、每個 solved property、每個 accepted lemma 之 token 成本。
3. **Solved instances / timeout reduction**：在固定 timeout 下可解 instance 數量。

**副指標：**

1. Invalid lemma ratio：parse/type/vocabulary/induction/subsumption failure 比例。
2. Accepted lemma ratio：LLM candidate 中通過驗證並注入者比例。
3. SMT query count：比較 LLM generalization 是否減少 solver query。
4. CTI blocking attempts：比較是否減少重複 CTI blocking。
5. Average lemma size：觀察泛化程度。
6. Subsumption statistics：accepted lemma 覆蓋或取代既有 lemma 的數量。
7. Candidate language ablation：`cube-subset` vs `qf-smt` vs `predicate-relation`。

**本研究不將 LLM API latency 作為主要貢獻指標**，因 API latency 可透過 batching、caching、local model、parallel sidecar 或更快 backend 進一步最佳化；本研究重點在於 LLM 產生之 generalization 是否能改善 IC3-IA 搜尋效率，以及 token 成本是否合理。

---

## 五、預期貢獻

1. **將 LLM 輔助方向從 lemma generation 收斂為 lemma generalization**  
   本研究不宣稱 LLM 可直接產生可信不變式，而是將其作為 CTI-guided generalization advisor。此定位更貼近 PDR/IC3 的核心瓶頸，也更容易透過 SMT validation 維持 soundness。

2. **提出可驗證且分階段放寬的 LLM candidate language**  
   由 `cube-subset` 起步，再擴展至 `qf-smt` 與 `predicate-relation`，避免一開始即面對任意 SMT-LIB 解析與 hallucination 問題。

3. **實作 Pono 內部整合與 Python sidecar 非同步架構**  
   相較 external wrapper，本研究直接在 Pono IC3/IC3-IA 內部蒐集 CTI、驗證 candidate lemma、決定合法 frame 並注入。Python sidecar 則降低 C++ HTTP/API 實作複雜度，提升可重現性與實驗效率。

4. **建立 runtime + token cost 導向之評估方法**  
   除了 wall-clock runtime，也量化 token cost、invalid lemma ratio、accepted lemma ratio、CTI blocking attempts、SMT query count 與 subsumption effect，使 LLM 是否真正幫助 generalization 可被具體評估。

---

## 六、參考文獻

**A. PDR / IC3 / 形式化驗證基礎**

[B1] A. R. Bradley, "SAT-Based Model Checking without Unrolling," VMCAI 2011.  
[B2] N. Een, A. Mishchenko, R. Brayton, "Efficient Implementation of Property Directed Reachability," FMCAD 2011.  
[B3] A. Cimatti, A. Griggio, S. Mover, S. Tonetta, "IC3 Modulo Theories via Implicit Predicate Abstraction," TACAS 2014.  
[B4] A. Cimatti, A. Griggio, "Software Model Checking via IC3," CAV 2012.  
[B5] A. Komuravelli, A. Gurfinkel, S. Chaki, "SMT-Based Model Checking for Recursive Programs," CAV 2014.（Spacer）  
[B6] A. Goel, K. A. Sakallah, "AVR: Abstractly Verifying Reachability," TACAS 2020.（word-level hardware IC3）  
[B7] M. Mann et al., "Pono: A Flexible and Extensible SMT-based Model Checker," CAV 2021.（本研究實作基座）

**B. LLM × 不變式 / 引理生成（直接相關）**

[1] H. P. et al., "Large Lemma Miners: Neurosymbolic Invariant Generation," arXiv:2511.02521, Nov 2025.  
[2] "Quokka: Accelerating Program Verification with LLMs via Invariant Synthesis," arXiv:2509.21629, Sep 2025.  
[7] "CIll: CTI-Guided Invariant Generation via LLMs for Model Checking," arXiv:2602.23389, Feb 2026.（最直接對標）  
[8] "LeGend: A Data-Driven Framework for Lemma Generation in Hardware Model Checking," arXiv:2602.24010, Feb 2026.  
[9] "Loop Invariant Generation: A Hybrid Framework of Reasoning optimised LLMs and SMT Solvers," arXiv:2508.00419, Aug 2025.  
[10] "Neuro-Symbolic Proof Generation for Scaling Systems Software Verification," arXiv:2603.19715, Mar 2026.  
[11] "Not All Invariants Are Equal: Curating Training Data to Accelerate Program Verification with SLMs," arXiv:2603.15510, Mar 2026.  
[12] "Can LLM Aid in Solving Constraints with Inductive Definitions?" arXiv:2603.03668, Mar 2026.  
[13] "LLM-Guided Quantified SMT Solving over Uninterpreted Functions," arXiv:2601.04675, Jan 2026.（exclusion-clause feedback）

**C. LLM × SVA / Assertion 生成（對照差異化）**

[3] "STELLAR: Structure-guided LLM Assertion Retrieval and Generation for Formal Verification," arXiv:2601.19903, Jan 2026.  
[4] "From Language to Logic: Bridging LLMs & Formal Representations for RTL Assertion Generation," arXiv:2604.23100, Apr 2026.  
[14] "PALM: Program Analysis and LLM Methods for Crafting SystemVerilog Assertions," DATE 2026.  
[15] "DeepAssert: An LLM-Aided Verification Framework with Fine-Grained Assertion Generation," arXiv:2509.14668, Sep 2025.  
[16] "ChatSVA: Bridging SVA Generation for Hardware Verification," arXiv:2604.02811, Apr 2026.  
[17] "AssertGen: Enhancement of LLM-aided Assertion Generation through Cross-Layer Signal Bridging," arXiv:2509.23674, Sep 2025.  
[18] "ATLAS: AI-Assisted Threat-to-Assertion Learning for SoC Security Verification," arXiv:2603.01170, Mar 2026.

**D. Pre-LLM 神經不變式生成（學術 lineage）**

[19] X. Si, H. Dai, M. Raghothaman, M. Naik, L. Song, "Learning Loop Invariants for Program Verification," NeurIPS 2018.（Code2Inv）  
[20] G. Ryan, J. Wong, J. Yao, S. Jana, R. Gu, "CLN2INV: Learning Loop Invariants with Continuous Logic Networks," ICLR 2020.

**E. 基準測試與 SAT 結構**

[5] "FVEval: A Comprehensive Benchmark for Hardware Formal Verification," arXiv:2410.23299, Oct 2024.  
[21] "Extracting Problem Structure with LLMs for Optimized SAT Local Search," arXiv:2501.14630, Jan 2025.

---

## 附錄 A：Pono 修改點清單

| 檔案 / 模組 | 修改類型 | 內容 |
|---|---|---|
| `engines/llm_generalizer.h` | 新增 | 定義 CTI request、candidate lemma、validation status、statistics 結構 |
| `engines/llm_generalizer.cpp` | 新增 | JSONL request/response、candidate schema validation、statistics logging |
| `engines/ic3.cpp` | 修改 | proof obligation / blocking 流程加入 CTI capture hook 與 candidate polling hook |
| `engines/ic3base.cpp` | 修改 | 主迴圈同步點加入非阻塞 candidate drain、validation、frame insertion |
| `engines/ic3ia.cpp` | 修改 | IC3-IA refinement 入口擷取 spurious CTI；predicate-level candidate 通過驗證後加入 abstraction domain |
| `engines/ic3ia.h` | 修改 | 暴露必要 hook 或 friend interface 給 `LLMGeneralizer`，避免破壞原生 IC3-IA 流程 |
| `options/options.{h,cpp}` | 修改 | 新增 `--llm-gen-mode`、`--llm-model`、`--llm-candidate-language`、`--llm-log` 等少量必要參數 |
| `pono.cpp` | 修改 | 初始化 LLM generalizer、傳遞 option、輸出實驗統計 |
| `utils/term_analysis.cpp` | 視需要修改 | 支援 candidate formula vocabulary check、symbol collection、sort check |
| `utils/ts_analysis.cpp` | 視需要修改 | 支援 local cone / relevant signal extraction |
| `llm_worker/sidecar.py` | 新增 | Python sidecar 主程式，監聽 request JSONL 並輸出 candidate JSONL |
| `llm_worker/deepseek_client.py` | 新增 | DeepSeek V4 Pro API adapter，讀取 `DEEPSEEK_API_KEY` |
| `llm_worker/prompts/` | 新增 | cube-subset、qf-smt、predicate-relation 三階段 prompt template |
| `semantic_reducer/` | 新增 | PyVerilog/Yosys 降維腳本、`name_map.json` 產生 |

---

## 附錄 B：本版相對 plan0428 之變更摘要

| 項目 | plan0428 | plan0514（本版） |
|---|---|---|
| 核心問題 | LLM 產生輔助 invariant / lemma | LLM 輔助 IC3/PDR lemma generalization |
| LLM 角色 | candidate lemma generator | untrusted generalization advisor |
| 核心演算法 | k-induction strengthening（bit-level） | IC3-IA / word-level IC3 |
| Lemma 形式 | 通用 auxiliary invariant | 分階段：cube-subset → qf-smt → predicate-relation |
| Solver | 未指定 | Pono（Stanford Centaur） |
| LLM backend | 未指定 | DeepSeek V4 Pro（透過 Python sidecar） |
| LLM 整合方式 | 啟動 + per-CTI | 非同步 CTI-guided generalization |
| 候選驗證 | 並行 BMC / 未細化 | parse/type/vocabulary/init/frame-relative induction/subsumption/budget check |
| Frame 處理 | 未明確 | 驗證 candidate 可合法加入哪一層 frame |
| Subsumption | 未明確 | 若 Pono 不自動處理，新增手動 cleanup / subsumption routine |
| 主要指標 | proof runtime | runtime + token cost + solved instances |
| 副指標 | 未明確 | invalid lemma ratio、accepted lemma ratio、SMT query、CTI blocking、subsumption effect |
| 實驗階段 | seed-only + async 框架 vs 完整 CTI-guided async | 受限 cube-subset PoC → qf-smt async generalization → predicate-level relation |
