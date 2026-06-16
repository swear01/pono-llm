# Handoff: Current State

**Last updated:** 2026-06-16 — Software-origin benchmark pipeline working (初步soundness achieved)  
**Branch:** `main` (pono-llm research fork)

---

## 策略方向（一句話）

LLM 看 C 編譯電路（變數名保留如 i, n, x, y），用 loop invariant 推理生成算術謂詞（如 `x+y==3*i`），IC3IA 在強化後的 BTOR2 上秒殺 prove。

---

## 初步 Soundness 達成（2026-06-16）

兩個軟體來源 benchmark 均在 15 秒內 PROVED UNSAT：

| Benchmark | LLM invariant | Total time |
|-----------|--------------|------------|
| `93.c` | `x+y==3*i`, `i<=n`, `x<=3*i`, `y<=3*i` | ~13s |
| `77.c` | `x>=i`, `y>=450-i` | ~8s |

**Pipeline：**
```
detect_software_origin(BTOR2)
  ↓  YES
build_software_prompt → LLM → parse candidates
  ↓
verify_invariant(each, BTOR2)  ← IC3IA proves NOT(inv) = UNSAT
  ↓ sound ones
inject_as_constraints(asts, BTOR2) → /tmp/constrained.btor2
  ↓
pono --engine ic3ia constrained.btor2 → UNSAT (< 1s)
```

**Entry point:** `llm_worker/invariant_arith.py:preprocess_software_benchmark()`  
**Standalone script:** `scripts/preprocess_sw.py`

---

## 關鍵發現

### ✅ 什麼有效
- **BTOR2 constraint injection**（預處理再跑 IC3IA）可以在 <1s 內 prove
- `inject_as_constraints()` 生成正確的 BTOR2 constraint 節點（ulte/eq/add/mul）
- LLM (DeepSeek v4-flash) 可靠地生成 `x+y==3*i` 和 `i<=n` 類型的不變量
- `verify_invariant()` 正確篩選：用 `bad = NOT(inv)` + IC3IA 驗算（UNSAT = sound）
- 算術謂詞 (`add`/`mul`) 注入 IC3IA 謂詞集 **成功**（已用 verbosity 確認）

### ❌ 什麼無效
- **Reactive sidecar predicate injection**：IC3IA 接受算術謂詞（`x+y==3*i`）但仍無法 close proof（refinement 添加 bit-extraction predicates，非常慢）
- **BTOR2 constraint 注入（在 pono 執行中途）**：IC3IA 已在跑，無法重載
- **加入太多 constraint**（如 `n==40`, `i>=0`）：使 IC3IA 比兩個精準約束慢 5-10 倍

### 過濾策略
只注入含 `add/sub/mul` 的約束（算術不變量）加上 ref-ref 比較（`i<=n`）。  
過濾：純 ref-const 比較（`n==40`, `i>=0`, `x<=500`）。

---

## Q2/Q3/Q4 已死

三個階段均達到 0% accept rate，根因是策略問題（per-CTI reactive blocking in wrong abstraction layer）。所有相關代碼已刪除。**不要復原。**

---

## 現有可用建構積木

| 模組 | 路徑 | 狀態 |
|------|------|------|
| 軟體原點檢測 | `llm_worker/invariant_arith.py:detect_software_origin()` | ✅ |
| 軟體 prompt builder | `llm_worker/invariant_arith.py:build_software_prompt()` | ✅ |
| Invariant 驗算 | `llm_worker/invariant_arith.py:verify_invariant()` | ✅ |
| BTOR2 約束注入 | `llm_worker/invariant_arith.py:inject_as_constraints()` | ✅ |
| 完整預處理管線 | `llm_worker/invariant_arith.py:preprocess_software_benchmark()` | ✅ |
| 命令列預處理 | `scripts/preprocess_sw.py` | ✅ |
| Sidecar shell | `llm_worker/sidecar.py` | ✅ |
| Stage 0 handler | `llm_worker/invariant_sidecar.py:handle_stage0_request()` | ✅ |
| IC3IA add/mul AST | `engines/ic3_frame_ast.cpp` | ✅ (BVAdd/BVSub/BVMul) |
| Symbol registry fix | `engines/ic3base.cpp:init_llm_symbol_registry()` | ✅ uses prover_interface_ts() |
| BTOR2 Builder | `llm_worker/invariant_arith.py:Btor2Builder` | ✅ correct sort IDs |

---

## 待做（Next Steps）

1. **更多 software-origin benchmarks**：找出 2024/2025 HWMCC 中所有 `*.c.btor2` 類型的 benchmarks
2. **Sidecar 整合 pre-processing**：目前 sidecar 仍走 reactive predicate injection 路線（不夠）；需要新協議讓 pono 能 reload 強化後的 BTOR2
3. **Stage 2 software-origin**：當 Stage 0 候選不夠時，Stage 2 可以再試更深層的不變量
4. **Reliability check**：確認 LLM 在多次呼叫中穩定產生正確的算術不變量（非隨機成功）

---

## 基礎設施狀態

| 項目 | 狀態 |
|------|------|
| C++ build | `build/pono` (2026-06-16 18:22) — add/mul/sub support in ic3_frame_ast.cpp |
| Python pipeline | `llm_worker/invariant_arith.py` — full pipeline working |
| 93.c verified | ✅ `unsat` in 13s |
| 77.c verified | ✅ `unsat` in 8s |
| Symbol registry | ✅ fixed (uses conc_ts_ via prover_interface_ts()) |
| Sidecar IPC | ✅ working (stage0 request/response flow confirmed) |
