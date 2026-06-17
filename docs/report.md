# LLM-Guided Hardware Verification: Progress Report

**Date:** 2026-06-17  
**Project:** pono-llm — LLM-assisted invariant generation for IC3IA model checking

---

## 1. 問題背景

硬體形式驗證（Formal Verification）面臨的核心瓶頸：

- **IC3/IC3IA** 是業界主流的硬體模型檢查演算法，需要找到「感應不變量（inductive invariant）」才能證明安全性質
- 對於從 **C 程式編譯成 BTOR2** 的電路，IC3IA 常常無法在合理時間內收斂（78s–∞）
- 原因：迴圈不變量（如 `2*sum == i*(i-1)`）超出純符號推理的能力範圍

**核心觀察：** 當 C 程式編譯成 BTOR2 時，**變數名稱會保留**（`i`, `n`, `x`, `y`, `sum`）。LLM 可以利用這些語意資訊，用軟體驗證的方式推理出算術不變量。

---

## 2. 方法（LLM Pre-processing Pipeline）

### 不走的路（已驗證失敗）
- **Reactive sidecar injection**：在 IC3IA 執行中途注入 LLM 產生的謂詞 → IC3IA 接受謂詞但仍無法 close proof（Q2/Q3/Q4 皆失敗）

### 現行方法：Pre-processing + BTOR2 Constraint Injection

```
C 程式 → 編譯 → BTOR2 電路
                    ↓
           detect_software_origin()
           (C 風格變數名？output labels？)
                    ↓ YES
     Phase 1: 結構對稱對注入（sym_pair）
     不需 LLM，純結構分析：eq(x, y) 如果 x', y' 結構完全相同
                    ↓
     Phase 2: LLM 呼叫（附帶公式級 transition sketch）
     prompt 給 LLM: "c' = ((i >= n) ? c : (c + i))"
     LLM 推理出: "2*c == i*(i-1)"（三角數不變量）
                    ↓
     多輪並行驗算（4 pono worker 並行）
     Round-1（4s）→ 簡單不變量
     Round-2（10s, 加 helpers）→ 複雜不變量
     Retry（如有累加器模式但沒找到算術不變量）
                    ↓
     inject_as_constraints() → 加強版 BTOR2
                    ↓
     pono --engine ic3ia → UNSAT (< 0.3s)
```

### 關鍵技術決策

| 決策 | 理由 |
|------|------|
| **Pre-process，不 reactive** | IC3IA 在 runtime 接受謂詞但無法利用算術謂詞收斂 |
| **Formula-level transition sketch** | LLM 看 `c' = c + i` 才能推 `2*c == i*(i-1)`，看 dep list 沒用 |
| **IC3IA 作為 oracle 驗算** | 每個 LLM 候選謂詞都用 `pono` 驗算 soundness（NOT(inv) = UNSAT？） |
| **ule fallback** | `2*sum == i*(i-1)` IC3IA 無法獨立驗，`2*sum <= i*(i-1)` 在 helper 下 0.1s 驗通 |
| **Const-bound filter** | 拒絕 `n==40`、`i>=0`：使 IC3IA 謂詞維度爆炸，反而更慢 |
| **Retry + probe gate** | LLM 有時只給 `i<=n`；有累加器模式則 retry；probe 避免 sym_pair 夠用時浪費 |

---

## 3. 結果

### 3.1 Proved Benchmarks（8 個）

**HWMCC 2024/2025 arithmetic circuits（6 個，原始目標）：**

| 電路 | 模式 | 注入的不變量 | Pre-process | pono |
|------|------|------------|-------------|------|
| `93.c` | 線性計數器 | `x+y==3*i`, `i<=n` | ~18s | 0.05s |
| `77.c` | 雙計數器 | `x>=i`, `y>=450-i` | ~7s | 0.02s |
| `fib_05` | 對稱迴圈 | `eq(x,y)`（sym_pair） | ~10s | 0.2s |
| `fib_23` | 三角和 | `i<=n`, `2*sum<=i*(i-1)` | ~25s | 0.05s |
| `fib_30` | 三角和 | `i<=n`, `2*c<=i*(i-1)` | ~25s | 0.07s |
| `fib_37` | 計數器界 | `x<=n`, `m<=x` | ~9s | 0.02s |

**HWMCC 2020 goel benchmarks（2 個，泛化結果）：**

| 電路 | 模式 | 注入的不變量 | Pre-process | pono |
|------|------|------------|-------------|------|
| `paper_v3` | 追逐計數器 (8-bit) | `x<=y`, `y>=x` | ~15s | 0.1s |
| `vcegar_QF_BV_ar` | Fibonacci 累加器 (2501-bit) | `b<=a` | ~30s | 0.1s |

### 3.2 Baseline vs. LLM Pre-processing

```
                Baseline    LLM Pre-processing
93.c            > 120s  →       18s   (7x+ speedup)
77.c            > 120s  →        7s   (17x+ speedup)
fib_05          > 120s  →       10s   (12x+ speedup)
fib_23             78s  →       25s   (3x speedup)
fib_30             ~80s →       25s   (3x speedup)
fib_37              5s  →        9s   (slight overhead, already fast)
paper_v3        > 120s  →       15s   (8x+ speedup)
vcegar_QF_BV_ar > 120s  →       30s   (4x+ speedup)
```

pono IC3IA 在加強版 BTOR2 上：**一律 < 0.3s**（vs. baseline 78s–∞）

### 3.3 失敗案例（誠實呈現）

| 電路 | 原因 |
|------|------|
| `h_RCU`, `vis_arrays_buf_bug` | 複雜狀態機、heap 操作；LLM 只產生 const-bound candidates（被過濾） |
| DVE 格式模型（`nextv_*`, `v_*`） | 並行過程代數模型，非 C 迴圈；雖通過名稱過濾但 LLM 無法推理 |
| 一般硬體電路（Verilog FSM、processor） | 無有意義變數名，不變量是協定性質而非算術 |

---

## 4. 適用範圍（Scope）

**有效的充分條件：**
1. 電路從 C 程式編譯，變數名保留（或有 output label）
2. 不變量是迴圈算術關係（線性、三角、Fibonacci、比較界）
3. 變數數量 2–10 個（LLM context 可處理）

**不適用：**
- 純硬體電路（cache、arbiter、protocol）
- 複雜記憶體操作（heap allocator）
- 大型狀態機（>20 個無語意變數名）

**一句話定位：** 這是「HLS/C-to-BTOR2 驗證」的專用加速工具，不是通用硬體驗證解法。

---

## 5. 技術架構摘要

```
llm_worker/
  invariant_arith.py    ← 完整 pipeline（~700 行）
    detect_software_origin()
    build_software_prompt()       ← formula-rich prompt
    verify_invariant()            ← pono as oracle
    inject_as_constraints()       ← BTOR2 builder
    preprocess_software_benchmark() ← end-to-end
    _has_accumulator_pattern()    ← retry trigger
    _is_proof_fast()              ← probe gate
    _build_retry_prompt()         ← triangular-sum hint
  btor2_reader.py       ← BTOR2 parser + formula decoder
    _decode_expr()                ← BTOR2 DAG → C-like formula
    build_transition_sketch()
    detect_symmetric_pairs()      ← structural expression hash
    parse_btor2()                 ← output-label extraction
  llm_client.py         ← OpenRouter API wrapper
scripts/
  preprocess_sw.py      ← standalone CLI
```

---

## 6. 後續方向

| 方向 | 說明 | 難度 |
|------|------|------|
| HLS benchmark 擴充 | Vivado/Intel HLS 生的 BTOR2 有 C 變數名，範圍可更廣 | 中 |
| 硬體協定不變量 | 換策略：LLM 猜「這是 FIFO/Arbiter」再套協定模板 | 高 |
| 論文撰寫 | 方法、結果、與 baseline/相關工作比較 | 中 |

---

## 附錄：執行方式

```bash
# 單一 benchmark
CONSTRAINED=$(python3 scripts/preprocess_sw.py circuit.btor2 2>/dev/null)
build/pono --engine ic3ia -k 500 "$CONSTRAINED"

# Verbose debug output
python3 scripts/preprocess_sw.py circuit.btor2
```

**需求：** Python 3.8+、OpenRouter API key（`OPENROUTER_API_KEY`）、`build/pono`
