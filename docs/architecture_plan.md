# Architecture Plan: LLM-Guided Hardware Verification — Full Exploration

**Created:** 2026-06-17  
**Status:** Planning document — all directions considered

---

## 現狀總結

目前已實作的架構：
```
detect_software_origin → portfolio(ind/interp 5s) → LLM invariant → verify → inject → IC3IA
```
已覆蓋 10 個 benchmarks（7 LLM path + 2 portfolio fast-path + paper_v3 LLM）。  
自然上限已確認：HWMCC 2020/2024/2025 中無更多軟體迴圈電路。

---

## A. 現有架構延伸（同架構、擴展功能）

### A1: Portfolio 快速路徑 ✅ **已實作**
- k-induction + interpolation 並行 5s
- sw_ball2004_2 (1.2s), vcegar_QF_BV_ar (1.0s) 解決

### A2: BAD 條件結構反向分析 ✅ **已實作** (2026-06-17, 整合於 A3)
**做法：** 解析 bad 節點，剝離 `and(const(1), cond)` 和 `not(not(cond))` 包裝  
**實作：** `btor2_reader.py:build_bad_condition_text()` 內的 `_peel_const1_and()` 和 `_peel_double_not()`  
**結果：** 對軟體電路（93.c, fib_23, paper_v3 等）都能正確提取 bad 條件  
**備注：** `bad' = bad OR trigger` 模式（FSM-style）在我們的電路中未見到；軟體電路的 bad 是純組合邏輯

### A3: BAD 反向可達性分析給 LLM ✅ **已實作** (2026-06-17)
**做法：** 解析 bad_lineno 的表達式並渲染為 LLM 可讀文字  
**實作：** `btor2_reader.py:build_bad_condition_text()` — 剝離 and(1,.) 和 not(not(.)) wrapper  
**結果：** 
- fib_23: `!((i < n) || (sum > 0))` → LLM 知道需要「i 達到 n 時 sum > 0」
- 93.c: `((i >= n) && ((n * 3) != (x + y)))` → 直接看到需要 x+y=3*n

### A4: 具體執行 Trace 給 LLM ✅ **已實作** (2026-06-17)
**做法：** 正向模擬電路 9 步（all inputs=0），展示 table 給 LLM  
**實作：** `btor2_reader.py:simulate_circuit_trajectory()` + `_eval_node()` BTOR2 evaluator  
**結果：**
- fib_23 trace: sum=0,0,1,3,6,10,15,21,28 → 三角數序列一眼看出 `2*sum==i*(i-1)`
- 93.c trace: x=0,2,4,6,8,10,12,14,16; y=0,1,2,3,4,5,6,7,8 → x+y=3*i 立刻明顯
- 93.c 測試: LLM 現在連續生成 `x + y == 3 * i`（6/6 次）
- 77.c (selector 電路): 偵測到 all-same trace → 自動略過 trace section
**備注：** 不需要 pono BMC 或外部工具；用 Python evaluator 直接模擬

### A5: 多輪 Chain-of-Thought 推理
**做法：** 問 LLM 三個問題的 chain：  
1. "What makes bad unreachable?"（目標拆解）  
2. "What state conditions ensure each guard?"（條件推導）  
3. "What arithmetic relations maintain these conditions?"（invariant 生成）  
**實作：** 新增 `build_chain_of_thought_prompt()`，3 次 LLM 呼叫  
**已規劃：** Direction B3 from previous session  
**風險：** API 成本 3x，收益不確定

---

## B. 完全不同的架構

### B1: Predicate Abstraction + CEGAR with LLM
**核心想法：** 不用 IC3IA，改用謂詞抽象 (predicate abstraction) + CEGAR 迴圈  
```
LLM → predicates P₁,...,Pₙ
  ↓
Abstract circuit C_abs (boolean abstraction over predicates)
  ↓  
BFS/SAT on C_abs → SAFE or COUNTEREXAMPLE
  ↓ (if spurious CEX)
Refine: ask LLM to add discriminating predicate for this CEX
  ↓ (repeat)
```
**對比現有：** 現有架構 IC3IA 做的是全局不動點計算；CEGAR 做的是漸進抽象精化  
**優點：** CEGAR 對算術迴圈有完備理論（SLAM/BLAST）  
**缺點：** 需要實作謂詞抽象引擎（重度工程），現有 pono 沒有這個功能  
**可行性：** 低（需要 2-3 個月工程量）

### B2: IC3 Generalization Hook with LLM
**核心想法：** 不在 IC3IA 前注入 constraints，而是 hook 進 IC3 的 GENERALIZATION 步驟  
```
IC3 blocks state s₀ (cube c)
  ↓
Normal: IC3 generalizes c → c' (drop literals, CTG blocking)
New: send c to LLM → LLM suggests clause l₁ ∧ l₂ (generalization with arithmetic)
  ↓
Verify that clause is inductive (quick SAT check)
  ↓ use if OK, fall back to IC3 otherwise
```
**優點：** LLM 直接影響 IC3 的 generalization quality；可處理非算術不變量  
**缺點：** 需要修改 pono C++ 代碼中的 IC3IA 引擎  
**已嘗試相關：** Q2/Q3 sidecar 的想法，但 hook 點不同（那個是 CTI level，這個是 generalization level）  
**可行性：** 中（需要 C++ pono 修改，2-4 週）

### B3: Abstract Interpretation with LLM-Driven Abstract Domain Selection
**核心想法：** 不用 IC3IA，改用 Abstract Interpretation（AI/區間/八邊形/多面體）  
```
LLM: "I think the invariant is a linear relation: α*x + β*y = γ*i"
  ↓
Choose abstract domain: Linear arithmetic (polyhedra)
  ↓
Run abstract interpreter (APRON library or similar) with this domain
  ↓
Check: does the fixpoint → safety?
```
**對比現有：** 現有架構用 IC3IA（bit-level interpolation）；這個用 AI（integer arithmetic domain）  
**優點：** 對算術迴圈電路天然適合；完備在 linear arithmetic domain  
**缺點：** BTOR2 → integer abstraction 的轉換非平凡；需要外部 AI 庫  
**可行性：** 低（需要 AI 庫整合，工程量大）

### B4: Synthesis-Based Approach (SyGuS)
**核心想法：** 把不變量推理變成 syntax-guided synthesis 問題  
```
Grammar: invariant ∈ {polynomial_rel | linear_rel | bound}
LLM: "I think grammar template is 2*acc <= i*(i-1) for some bounds on acc and i"
  ↓
SyGuS solver fills in the coefficients/bounds
  ↓
Verify the synthesized invariant
```
**優點：** LLM 給 SHAPE，SMT solver 給 COEFFICIENTS — 分工清晰  
**LLM 弱點：** LLM 不擅長精確數值（如係數 2501）  
**SMT 強點：** SMT solver 可以精確計算正確的係數  
**實作：** 需要 SyGuS 求解器（e.g., CVC5 SyGuS mode）  
**可行性：** 中等（需要 CVC5 整合，但想法清晰）

### B5: Modular / Compositional Verification
**核心想法：** 把複雜電路分解為多個模組，各模組獨立驗證  
```
Decompose BTOR2 into sub-circuits by connectivity analysis
  ↓
For each sub-circuit: LLM generates interface invariant (contract)
  ↓
Verify each sub-circuit with its assumed contracts
  ↓
Compose: if all sub-circuits are safe under assumed contracts → global safe
```
**適用：** 複雜 FSM 電路（protocol stacks, pipeline stages）  
**缺點：** BTOR2 decomposition 非平凡；contract 語言設計複雜  
**可行性：** 低（需要完整新框架）

### B6: LLM Fine-Tuning on Circuit-Invariant Pairs
**核心想法：** 用已知 10 個 benchmark 的 (circuit, invariant) pairs fine-tune 一個小模型  
**問題：** 10 個樣本遠不夠 fine-tuning  
**解法：** 資料擴增 — 程序生成大量算術迴圈電路 + 已知正確 invariant  
**可行性：** 低（資料生成 + fine-tuning 基礎設施需要大量工作）

### B7: Program Analysis (Daikon-Style) without LLM
**核心想法：** 用 Daikon-style 不變量推斷：枚舉電路的「近似執行軌跡」，從軌跡資料中統計推斷可能的不變量  
```
Simulate circuit for random inputs (2000 steps)
  ↓
Collect state variable values at each step
  ↓
Run Daikon-style inference: find arithmetic relations that always hold in data
  ↓
Verify candidates with IC3IA
```
**優點：** 不需要 LLM；純數學推斷  
**缺點：** BTOR2 simulation 需要 SAT solver（initial state choice）；
Daikon 需要大量樣本；不保證找到所有必要 invariants  
**可行性：** 中等（可用 pono --engine bmc 生成軌跡，Daikon 有 Python 介面）

### B8: Neural Network Invariant Prediction
**核心想法：** 訓練 GNN (Graph Neural Network) 在電路結構圖上預測 invariant 形式  
**問題：** 需要大量訓練資料（至少 1000 個 circuit-invariant pairs）  
**可行性：** 低（研究方向，非短期可行）

---

## C. 擴展到不同電路類別

### C1: CBMC-Aware Preprocessing
**問題：** CBMC 電路有 `!{$(in_main#0)<i>}` 名稱 mangling，input-driven transitions  
**解法：**  
1. 偵測 CBMC 名稱模式（regex `!{\$\(`）
2. 提取 `valid` flag（admissible path condition）
3. 將 valid 加為 `assume`（而非 `constraint`）
4. 提取真實 C 變數名（去除 mangling）
5. 對 valid-path-constrained 電路套用 LLM invariant generation  
**可行性：** 中等（需要 CBMC-specific btor2_reader extension，2-3 週）  
**但：** 目前 HWMCC CBMC 電路未知是否有我們可以找到的 invariants

### C2: Array Invariant Generation (HLS 電路)
**問題：** 256+ array state elements，invariant 涉及 forall/exists 量詞  
**解法：** LLM 生成 quantified invariants，e.g.:  
- `∀ i: 0 ≤ i < n → arr[i] ≤ MAX`
- `∃ i: arr[i] == target`  
**挑戰：** IC3IA oracle 無法驗證 quantified invariants（需要 Exists/Forall alternation）  
**需要：** 支援量化 invariant 的 oracle（e.g., CHC solving with forall）  
**可行性：** 低（需要新的 verification oracle）

### C3: Protocol/FSM 電路（硬體設計）
**問題：** Wolf Verilog/picorv32/zipcpu 是硬體 FSM，LLM 無法無 domain knowledge 推理  
**解法：** 加入硬體 protocol 知識作為 LLM context  
- 詢問 LLM "what are common invariants for RISC-V processors?"
- Provide RTL specification文字  
**可行性：** 低（需要 circuit-specific domain knowledge，無法自動化）

---

## D. 最可行的「不同架構」排序

### 優先級 1: BAD 反向分析 (A2 + A3) — 1-2 週
**最接近可實作，不需要外部工具：**
- 提取 BAD pre-image 公式
- 加入 LLM prompt 作為「反向提示」
- 測試對 sw_ball2004_2 是否有幫助（location-conditioned 電路）

### 優先級 2: BMC Trace 導引 (A4) — 1-2 週
**具體化 LLM reasoning：**
- 找到近 bad trace（pono BMC witness）
- 格式化為自然語言 + 狀態表
- 測試 LLM 是否能從具體 trace 推斷 invariant

### 優先級 3: IC3 Generalization Hook (B2) — 3-4 週
**更深的整合：**
- Requires C++ pono changes
- High risk, high reward: could fundamentally improve IC3IA convergence

### 優先級 4: SyGuS Template (B4) — 2-3 週
**LLM 提供形狀，SMT 提供數值：**
- 需要 CVC5 或自訂 template enumeration
- Addresses LLM 數值不精確的弱點

### 優先級 5: Daikon-Style Simulation (B7) — 2-3 週
**完全不依賴 LLM：**
- pono BMC 生成軌跡 → Daikon 推斷 → IC3IA 驗算
- 作為 LLM 的 fallback 或 comparison

---

## E. 立即可嘗試的實驗

以下可在 1-2 天內實驗（不需要架構重寫）：

### E1: BAD Pre-image 加入 LLM Prompt
```python
# In build_software_prompt():
bad_preimage = compute_bad_preimage(info)  # one-step pre of BAD
prompt += f"\nThe circuit reaches bad when: {bad_preimage}\n"
prompt += "Suggest invariants that prevent any state from satisfying this condition.\n"
```

### E2: 顯示具體初始狀態值給 LLM
```python
# Current prompt shows formulas (symbolic)
# New: also show initial state assignments
prompt += f"\nInitial state: {', '.join(f'{v.symbol}=0' for v in sw_vars)}\n"
```

### E3: 讓 LLM 解釋它的推理
```python
# Change response format: ask for explanation first
system_prompt += "\nFor each invariant, first explain WHY it's true (2 sentences), then give the predicate_ast."
```

---

## F. 結論

**最可能擴展覆蓋率的方向：**
1. BAD pre-image analysis (A2/A3)：0 extra benchmarks guaranteed，但改善 LLM reasoning quality
2. CBMC-aware preprocessing (C1)：可能 unlock 26 CBMC circuits（如果它們有 arithmetic invariants）
3. SyGuS template synthesis (B4)：可能解決 LLM 數值不精確問題，unlock more arithmetic circuits

**完全不可行的方向（短期）：**
- Fine-tuning (B6)：資料太少
- Neural invariant (B8)：需要大量基礎設施
- Compositional verification (B5)：需要新框架

**結論：** 10 個 benchmarks 是 HWMCC 集合的自然上限（已窮盡掃描）。如要突破，需要：
1. 新的 benchmark 集合（包含更多 C-source 電路）
2. 或擴展到 CBMC 電路（需要 CBMC-aware parsing）
3. 或擴展 invariant 形式（quantified / protocol-based）
