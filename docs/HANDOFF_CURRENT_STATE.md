# Handoff: Current State

**Last updated:** 2026-06-17 — Portfolio fast-path added; 10 benchmarks covered  
**Branch:** `main` (pono-llm research fork)

---

## 策略方向（一句話）

**Portfolio 方法：** 先用 k-induction / interpolation 快速嘗試（5s 並行），再用 LLM 生成 loop invariant 並注入 BTOR2 constraint，最後由 IC3IA 秒殺 prove。

---

## 全面 Soundness 達成

**10 個軟體來源 benchmark covered：**

**HWMCC 2024/2025 (arithmetic circuits) — LLM + IC3IA 路徑：**

| Benchmark | 關鍵 invariants | Total | pono |
|-----------|----------------|-------|------|
| `93.c`    | `x+y==3*i`, `i<=n` | ~24s* | ~0.05s |
| `77.c`    | `x>=i`, `y>=450-i` | ~13s* | ~0.02s |
| `fib_05`  | `eq(x,y)` (sym_pair) | ~16s* | ~0.2s |
| `fib_23`  | `i<=n`, `2*sum<=i*(i-1)` | ~31s* | ~0.05s |
| `fib_30`  | `i<=n`, `2*c<=i*(i-1)` | ~31s* | ~0.07s |
| `fib_37`  | `x<=n`, `m<=x` | ~15s* | ~0.02s |
| `paper_v3` | `x<=y`, `y>=x` | ~21s* | ~0.1s |

\* includes 5.5s portfolio fast-path overhead (ind+interp both timeout for arithmetic loops)

**HWMCC 2020 (goel benchmarks) — Portfolio 快速路徑：**

| Benchmark | Fast Engine | Total | 原 baseline |
|-----------|-------------|-------|-------------|
| `vcegar_QF_BV_ar` | `ind` (k-induction) | **1.0s** | timeout |
| `sw_ball2004_2`   | `ind` (k-induction) | **1.2s** | timeout |

**Baseline（無 preprocessing）:**
- 93.c: timeout; 77.c: timeout; fib_05: timeout; fib_23: 78s; fib_30: ~80s; fib_37: ~5s; paper_v3: timeout; vcegar_QF_BV_ar: timeout; sw_ball2004_2: timeout

---

## Pipeline（一般方法）

```
detect_software_origin(BTOR2)
  ↓ YES (C-style variable names OR output-label names)
Step 0: try_fast_engines(ind, interp, k=50, timeout=5s, PARALLEL)
  → PROVED? return (original_path, -1, engine) — caller uses fast engine, not IC3IA
  → timeout? continue to LLM path (5.5s max overhead)
  ↓
Phase 1: detect_symmetric_pairs() → inject eq(A,B) for each sym_pair (pono verified)
  ↓
Phase 2: LLM call with formula-rich prompt
  (transition sketch shows actual formulas: c' = (i>=n ? c : c+i))
  (prompt rule: "NEVER use division; use 2*sum == i*(i-1) not sum == i*(i-1)/2")
  ↓
Round-1: verify each candidate in PARALLEL (4 workers, timeout=4s)
  → SOUND: add to sound_asts
  → TIMEOUT: add to r2_retry; if eq(A,B) timed out, also add ule(A,B) fallback
  → REJECTED: discard
  ↓
Round-2: rebuild helper circuit with Round-1 sound invariants
  → verify each r2_retry candidate in PARALLEL (timeout=10s)
  → SOUND: add to sound_asts
  ↓
Deduplicate sound_asts (by canonical JSON key)
  ↓
[If no arithmetic found + accumulator pattern + not already fast]:
  → Retry LLM (up to 2x) with triangular-sum hint
  → Verify retry candidates in PARALLEL with sound_asts as helpers
  ↓
inject_as_constraints(sound_asts, BTOR2) → constrained.btor2
  ↓
pono --engine ic3ia constrained.btor2 → UNSAT (< 0.3s typically)
```

**Entry point:** `llm_worker/invariant_arith.py:preprocess_software_benchmark()`  
**Standalone CLI:** `scripts/preprocess_sw.py`  
**Usage:**
```bash
CONSTRAINED=$(python3 scripts/preprocess_sw.py circuit.btor2 2>/dev/null)
build/pono --engine ic3ia -k 500 "$CONSTRAINED"
```

---

## 關鍵發現

### ✅ 什麼有效
- **BTOR2 constraint injection 預處理**：IC3IA 在強化 BTOR2 上秒殺（<0.3s）
- **Multi-round parallel verification**：先快速找簡單 invariant（4 pono 並行），再以已驗證者為 helper 驗複雜 invariant
- **ule fallback for eq**: `2*sum==i*(i-1)` 無法驗，但 `2*sum<=i*(i-1)` 在 helper 下 0.1s 驗通
- **Retry loop with probe gate**：no arithmetic found + accumulator pattern → retry LLM；probe check 防止 fib_05 浪費 LLM call
- **Sym_pair 先注入**：fib_05 eq(x,y) 無需 LLM，結構分析即可確定
- **Formula-rich transition sketch**：LLM 看 `c' = (i>=n ? c : c+i)` 就能推出 triangular sum invariant
- **Output-label extraction**：fib_30/fib_37 states 無名但有 output 標籤，已正確提取
- **反除法 prompt 規則**：LLM 現在輸出 `2*sum == i*(i-1)` 而非 `sum == i*(i-1)/2`
- **ThreadPoolExecutor 並行驗算**：35% 套件加速（fib_05: 24→10s, fib_30: 47→25s）

### ❌ 什麼無效
- **Reactive sidecar predicate injection**（Q2/Q3/Q4）：IC3IA 接受算術謂詞但仍無法 close proof
- **單純等式驗算** `2*sum==i*(i-1)`：IC3IA 無法在有限時間內驗通，即使有 helper
- **加入太多 constraint**（如 `n==40`, `i>=0`）：ref-const bounds 使 IC3IA 5-10x 慢
- **複雜狀態機** (h_RCU, vis_arrays_buf*)：LLM 只能生成 const-bound candidates，被過濾

### 適用範圍

**有效 (LLM+IC3IA)：** C/Loop-based 電路（計數器、累加器、對稱更新、Fibonacci 式）  
**有效 (Portfolio 快速路徑)：** 有界路徑電路（location-bit FSM、concurrent programs）  
**無效：** Heap allocators、複雜 FSMs、DVE 格式模型、CBMC input-driven transitions

---

## 軟體來源 Benchmarks 位置

**HWMCC 2024/2025:**
| Benchmark | 路徑 (相對 `/home/swear01/`) |
|-----------|------|
| 93.c | `hwmcc_benchmarks/2024/btor2/2024/hku/arithmetic_circuits/93.c/93.c.btor2` |
| fib_30 | `hwmcc_benchmarks/2024/btor2/2024/hku/arithmetic_circuits/fib_30/fib_30.btor2` |
| fib_37 | `hwmcc_benchmarks/2024/btor2/2024/hku/arithmetic_circuits/fib_37/fib_37.btor2` |
| 77.c | `hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/arithmetic_circuits/77.c/77.c.btor2` |
| fib_05 | `hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/arithmetic_circuits/fib_05/fib_05.btor2` |
| fib_23 | `hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/arithmetic_circuits/fib_23/fib_23.btor2` |

**HWMCC 2020:**
| Benchmark | 路徑 (相對 `/home/swear01/`) |
|-----------|------|
| paper_v3 | `hwmcc_benchmarks/2020/hwmcc20/btor2/bv/2019/goel/crafted/paper_v3/paper_v3.btor2` |
| vcegar_QF_BV_ar | `hwmcc_benchmarks/2020/hwmcc20/btor2/bv/2019/goel/opensource/vcegar_QF_BV_ar/vcegar_QF_BV_ar.btor2` |
| sw_ball2004_2 | `hwmcc_benchmarks/2024/btor2/2019/goel/crafted/sw_ball2004_2/sw_ball2004_2.btor2` |

---

## 現有建構積木

| 模組 | 路徑 | 狀態 |
|------|------|------|
| Portfolio 快速路徑 | `llm_worker/invariant_arith.py:try_fast_engines()` | ✅ ind+interp parallel, 5s cap |
| 軟體原點檢測 | `llm_worker/invariant_arith.py:detect_software_origin()` | ✅ |
| 累加器模式檢測 | `llm_worker/invariant_arith.py:_has_accumulator_pattern()` | ✅ |
| 快速 probe 驗算 | `llm_worker/invariant_arith.py:_is_proof_fast()` | ✅ |
| 對稱對檢測 | `llm_worker/btor2_reader.py:detect_symmetric_pairs()` | ✅ |
| Formula 轉換 | `llm_worker/btor2_reader.py:_decode_expr()` | ✅ |
| Transition sketch | `llm_worker/btor2_reader.py:build_transition_sketch()` | ✅ (formula-level) |
| Output-label 提取 | `llm_worker/btor2_reader.py:parse_btor2()` | ✅ |
| 軟體 prompt builder | `llm_worker/invariant_arith.py:build_software_prompt()` | ✅ |
| Retry prompt builder | `llm_worker/invariant_arith.py:_build_retry_prompt()` | ✅ |
| Invariant 驗算 (parallel) | `llm_worker/invariant_arith.py:verify_invariant()` | ✅ |
| BTOR2 約束注入 | `llm_worker/invariant_arith.py:inject_as_constraints()` | ✅ |
| 完整預處理管線 | `llm_worker/invariant_arith.py:preprocess_software_benchmark()` | ✅ |
| 命令列預處理 | `scripts/preprocess_sw.py` | ✅ |
| BTOR2 Builder | `llm_worker/invariant_arith.py:Btor2Builder` | ✅ correct sort IDs |

---

## 基礎設施狀態

| 項目 | 狀態 |
|------|------|
| C++ build | `build/pono` (2026-06-17) |
| Python pipeline | `llm_worker/invariant_arith.py` — complete general pipeline |
| 6-benchmark suite (2024/2025) | ✅ all unsat, ~95s total (parallel) |
| 2020 goel LLM benchmarks | ✅ paper_v3 ~21s, vcegar_QF_BV_ar 1.0s (portfolio) |
| 2020 goel portfolio benchmarks | ✅ sw_ball2004_2 1.2s (ind), vcegar_QF_BV_ar 1.0s (ind) |
| `implies` AST form | ✅ added to ast_to_btor2 (2026-06-17) |
| Portfolio fast-path | ✅ try_fast_engines() parallel ind+interp 5s cap (2026-06-17) |

## 探索邊界（2026-06-17 確認）

| 類別 | 結果 |
|------|------|
| CBMC loops-crafted/eca-rers (26 circuits) | ❌ input-driven transitions，不適用 |
| sw_ball2004_2 (Ball/SLAM) | ✅ 由 portfolio k-induction 1.2s 解決 |
| Wolf Verilog 電路 (100+) | ❌ 硬體設計，協定不變量，LLM 無法推理 |
| HWMCC 2020 goel/industry (~40) | ❌ Verilog FSM，無軟體迴圈 |
| HWMCC 2024 hku/bv HLS | ❌ 256+ 陣列狀態元素 |

**10 個 benchmarks (8 LLM + 2 portfolio fast-path) 是目前 HWMCC benchmark 集合的自然上限。**
