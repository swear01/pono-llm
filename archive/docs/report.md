> Archived: 2026-07-11
> Reason: Historical 2026-06-17 constraint-injection report superseded by sound predicate injection and Phase 1+2 validation plan
> Replacement: docs/overview.md
> Status: historical only; do not use as active truth.

# LLM-Guided Hardware Verification: Progress Report

**Date:** 2026-06-17  
**Project:** pono-llm — LLM-assisted invariant generation for IC3IA model checking

> ⚠️ **Update (2026-06-20) — read first**: this is a 2026-06-17 snapshot. A later
> soundness audit found that injecting hints as BTOR2 **constraints** is unsound
> (under-approximation); the main pipeline was switched to SOUND **predicate**
> injection (`pono --initial-predicates`). The arithmetic results below remain
> numerically valid (those invariants are true), but the injection mechanism is
> now predicates, not constraints. See `docs/roadmap.md` (B2) and `docs/notes.md`.

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
| `h_RCU`, `vis_arrays_buf_bug` | RCU 協定、heap 操作；需要 protocol invariant，非算術迴圈不變量 |
| `sw_ball2004_2` | 軟體模型檢查電路，location bit 類型；3 個位置條件不變量可驗，但關鍵安全不變量需多步推理，IC3IA-as-oracle 無法完成 |
| CBMC 格式（loops-crafted, eca-rers）| transition 為 input-driven（next state 是 input），無法產生有用 transition sketch |
| DVE 格式模型（`nextv_*`, `v_*`） | 並行過程代數模型，非 C 迴圈 |
| Wolf Verilog 電路（picorv32, zipcpu, dblclockfft） | 純硬體設計，名稱雖短但是協定信號，非迴圈變數 |
| HLS 電路（hl_arr_access_128_bv） | Vivado HLS 生成，256+ 陣列狀態元素，不變量涉及記憶體內容 |

### 3.4 延伸探索結果（本次調查）

探索範圍：HWMCC 2024/2025 全部非 arithmetic_circuits 目錄、HWMCC 2020 全部 goel 電路、Wolf/Mann 電路。

| 類別 | 數量 | 結論 |
|------|------|------|
| CBMC loops-crafted 電路 | 3 | input-driven，不適用 |
| CBMC eca-rers2012 電路 | 23 | 同上 |
| sw_ball2004_2 (Ball/SLAM) | 1 | 部分可用；`implies` 形式新增；但關鍵不變量超出 IC3IA oracle 能力 |
| Verilog 硬體電路（wolf）| 100+ | 名稱短但為硬體信號，LLM 無法推理 |
| HWMCC 2020 goel/industry | ~40 | 全部為 Verilog FSM，無軟體迴圈 |
| HWMCC 2024 hku/bv HLS | 2 | 陣列電路，256+ 狀態，不適用 |

**結論：HWMCC 2020/2024/2025 benchmark 集合中，本方法已找到全部可解電路（8 個）。**

---

## 4. 適用範圍（Scope）

**有效的充分條件：**
1. 電路從 C 程式編譯，變數名保留（或有 output label）
2. 不變量是迴圈算術關係（線性、三角、Fibonacci、比較界）
3. 變數數量 2–10 個（LLM context 可處理）

**不適用：**
- 純硬體電路（cache、arbiter、protocol、processor）
- CBMC/ESBMC 生成電路（input-driven transitions，mangled names）
- 複雜記憶體操作（heap allocator、陣列電路）
- 需要多步路徑條件不變量的電路（sw_ball2004_2 類型）

**一句話定位：** 這是「C-to-BTOR2 驗證」的專用加速工具，針對保留迴圈算術結構的電路。不是通用硬體驗證解法。

---

## 5. 技術架構摘要

```
llm_worker/
  invariant_arith.py    ← 完整 pipeline（~800 行）
    detect_software_origin()
    build_software_prompt()       ← formula-rich prompt
    verify_invariant()            ← pono as oracle
    inject_as_constraints()       ← BTOR2 builder
    preprocess_software_benchmark() ← end-to-end
    _has_accumulator_pattern()    ← retry trigger
    _is_proof_fast()              ← probe gate
    _build_retry_prompt()         ← triangular-sum hint
    ast_to_btor2()                ← 支援 implies 形式（新增）
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
| 論文撰寫 | 方法、結果、與 baseline/相關工作比較 | 中 |
| HLS benchmark 自製 | 用 Vivado HLS 從 C 程式生成 BTOR2，擴充 benchmark 集合 | 高（需工具鏈） |
| CBMC 電路支援 | 從 CBMC 的 BMC encoding 反向解析迴圈結構；不同架構 | 高 |
| 位置條件不變量（sw_ball2004_2 類型） | 需要鏈式多步驗算策略，超出目前 IC3IA oracle 能力 | 高 |

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
