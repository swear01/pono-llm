# HWMCC 實驗分層編排（Tier 0–3）

**目的：** 分階段跑 HWMCC，先建立 baseline 與選案，再跑 LLM。  
**程式入口：** [`scripts/run_benchmarks.py`](../scripts/run_benchmarks.py)  
**平行政策：** 預設 **8 開** — 見 [`plans/experiment_parallel_policy.md`](plans/experiment_parallel_policy.md)。  
**API：** 成本不設上限；並發以 **牆鐘時間** 與 **RAM/CPU** 為限，不為省 API 刻意縮子集或降 parallel。

---

## 當前建議執行順序

```
1. --phase baseline（全量，無 LLM）
2. --phase report（classification.csv + report.md）
3. --phase find-solvable（candidates.json，有 blocking 的案）
4. --phase llm（依 baseline + candidates 選案；八開）
```

**不要**在未完成 baseline 前跑 `--phase hwmcc`（會接著跑 LLM）。  
**不要**用 `--phase llm` 的 competition 自動選案當唯一依據（首輪 beem 前 N 全 timeout）；優先 `candidates.json` 中 `blocking_phases > 0`。

---

## Baseline phase（本來行為）

`--phase baseline` **只跑 pono、不啟動 sidecar、不需要 `DEEPSEEK_API_KEY`**。

### 做什麼

1. 從 `--hwmcc-dir` + `--hwmcc-years` 收集 `.btor2`（預設 `2020,2024,2025`）
2. 過濾：有 known expected（sat/unsat）；competition 結果為 `unknown` 的案跳過
3. 每案執行：`pono -e <engine> -k <bound> --llm-gen-mode none <benchmark.btor2>`
4. `--parallel` 個 worker 從 queue 取案（預設 **8** thread + subprocess）
5. 每案軟記憶體上限 `--memory-limit`（預設 **14 GB**）；超過則 kill
6. 單案牆鐘上限 `--timeout`（預設 **1000s**）
7. 寫入 `{output-dir}/results_baseline.csv`

### 預設參數（可不傳，即本來行為）

| 參數 | 預設 | 說明 |
|------|------|------|
| `--phase` | `hwmcc` | **只跑 baseline 時必須設** `--phase baseline` |
| `--hwmcc-dir` | `~/hwmcc_benchmarks` | |
| `--hwmcc-years` | `2020,2024,2025` | |
| `--engine` | `ic3ia` | |
| `--bound` | `100000` | `-k` |
| `--timeout` | `1000` | 秒 |
| `--parallel` | `8` | baseline worker 數 |
| `--memory-limit` | `14` | GB / 案 |
| `--output-dir` | `./bench_results` | |
| `--limit` | `0` | `0` = 全部案；除錯可設小數 |

### CSV 欄位與分類

`results_baseline.csv`：`benchmark`, `year`, `track`, `expected`, `mode=baseline`, `result`（sat/unsat/timeout/error/memout）, `wall_time`, `category`, `match`。

`category`（依**本機** wall_time）：

| category | 條件 |
|----------|------|
| fast | wall_time < 30s |
| medium | 30s ≤ wall_time < 500s |
| slow | wall_time ≥ 500s |
| timeout / error | 對應 result |

### `result` 語意（sat / unsat / timeout / error / memout）

| result | 意義 |
|--------|------|
| `sat` / `unsat` | 本機 IC3IA 在 `-k` bound 內**判定完成**（stdout 第一行） |
| `timeout` | 單案牆鐘達 `--timeout`（預設 1000s）被 harness kill |
| `memout` | RSS 超過 `--memory-limit` 被 kill |
| `error` | pono **無法繼續證明**而中止（見下）；**不是** harness 誤判 |

**與 timeout 的差別：** `timeout` 是「還在跑但時間到」；`error` 是引擎明確失敗或 SMT 回 `unknown`，通常加時間也**不會**變成 sat/unsat。

#### 真 `error`（IC3IA + 預設 Bitwuzla，可接受）

harness 修正後（`_parse_pono_stdout`），若 pono stdout 第一行為 `error`、exit code **2**，即為**真 error**。pono 在 stderr 印原因後印 `error` / `b0`（`pono.cpp` catch）。

預設 stack：`-e ic3ia`，主 solver 與 interpolator 皆 **Bitwuzla (`bzla`)**。全量 baseline 中少數案（約數％）會落在此類，**屬預期**，不代表 benchmark 壞檔或 harness bug。

常見兩類（2026-06-07 `baseline-patch` 實測）：

| 類型 | stderr 關鍵字 | 原因 |
|------|---------------|------|
| **Interpolation 不支援** | `interpolation queries with mixed lemmas not supported` | `IC3IA::refine()` 對抽象反例做 sequence interpolation；Bitwuzla interpolator 不支援該公式序列（多見 **array** / FIFO 類，如 mann、部分 zipcpu） |
| **IC3 核心查詢 unknown** | `Bad state check in IC3 returned unknown`；常伴 `[bzla] warning: Equality over constant arrays not fully supported yet` | `IC3Base::reaches_bad()` 須 sat/unsat；Bitwuzla 對含 **constant array** 的查詢回 `unknown`，IC3 無法繼續（多見 `picorv32_mut*_mem-*`） |

程式錨點：interpolation → [`engines/ic3ia.cpp`](../engines/ic3ia.cpp) `refine()` / `get_sequence_interpolants`；unknown → [`engines/ic3base.cpp`](../engines/ic3base.cpp) `reaches_bad()`。

**勿與已修 bug 混淆：** 舊 harness 把 `unsat`+exit 1 誤記為 `error`；修正後該類會是 `unsat`。CSV 裡 stdout 為 `error`、exit 2 的列才是引擎真失敗。

**報告解讀：** `result=error` =「此 **engine + solver 組合** 未完成判定」，不表示 competition 無解。其他 solver（msat 等）可能解出。

可選實驗（非 baseline 預設）：`--smt-interpolator msat` 或 `-e msat-ic3ia`（需 build 含 MathSAT）。baseline 為可重現性固定 `ic3ia` + 預設 bzla。

### 標準命令（完整 HWMCC baseline）

```bash
# 建議獨立 output-dir，背景跑
OUT=bench_results/hwmcc_baseline_$(date +%Y%m%d)
mkdir -p "$OUT"

nohup python3 scripts/run_benchmarks.py \
  --phase baseline \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --output-dir "$OUT" \
  --parallel 8 \
  --memory-limit 14 \
  --engine ic3ia \
  > "$OUT/nohup.log" 2>&1 &

# 監控
tail -f "$OUT/nohup.log"
# 進度：log 內 baseline progress: N/M
```

完成後：

```bash
python3 scripts/run_benchmarks.py --phase report \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --output-dir "$OUT"
```

產物：`classification.csv`（competition 對照）、`report.md`。

### pono stdout 格式（harness 解析）

BTOR2 的 pono 在 stdout 印**兩行**（見 `pono.cpp`）：

```
sat
b0
```

harness 必須讀**第一行**判斷 `sat`/`unsat`/`unknown`/`error`。若整段 stdout 比對，會把 `sat\nb0` 誤判為 `unknown`（exit 0）、`unsat\nb0` 誤判為 `error`（exit 1）。此問題已於 2026-06-07 修正（`_parse_pono_stdout`）。

### 中斷恢復（suspend → patch → resume）

harness **不支援**從 `nohup.log` 一鍵 resume 全量；中斷後建議：

```
1. baseline-patch   — 從 nohup.log 重建「已完成」案
2. baseline --skip-partial — 跳過 partial，跑剩餘案，自動合併
```

**Step 1 — `baseline-patch`**

- **信任 log**：`timeout`、`memout`（wall_time 取自 log）
- **重跑**：log 裡的 `error`、`unknown`（用修正後 parser 再跑 pono）
- 產物：`results_baseline_partial.csv`、`baseline_patch_manifest.json`

```bash
OUT=bench_results/hwmcc_baseline_<date>

nohup python3 scripts/run_benchmarks.py \
  --phase baseline-patch \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --output-dir "$OUT" \
  --baseline-log "$OUT/nohup.log" \
  --parallel 8 \
  --memory-limit 14 \
  --engine ic3ia \
  > "$OUT/patch.log" 2>&1 &
```

**Step 2 — `baseline --skip-partial`**

- 讀 `{output-dir}/results_baseline_partial.csv`（或 `--partial-csv`）
- 跳過 partial 已有 path 的案，只跑剩餘案
- 結束時 **自動合併** partial + 新結果 → `results_baseline.csv`（依 collect 順序，共 1052 行）

```bash
nohup python3 scripts/run_benchmarks.py \
  --phase baseline \
  --skip-partial \
  --output-dir "$OUT" \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --parallel 8 \
  --memory-limit 14 \
  --engine ic3ia \
  > "$OUT/nohup_resume.log" 2>&1 &
```

進度 log 為整體計數，例如 `baseline progress: 178/1052`（含已跳過的 partial 案）。

| 參數 | 預設 | 說明 |
|------|------|------|
| `--baseline-log` | `<output-dir>/nohup.log` | `baseline-patch` 用的 harness log |
| `--skip-partial` | off | resume 時跳過 partial 已有案 |
| `--partial-csv` | `<output-dir>/results_baseline_partial.csv` | 自訂 partial 路徑 |

**勿在 patch 完成前**跑 `--skip-partial`（partial 不完整會漏案）。

### 與 `--phase hwmcc` 的差異

| | `--phase baseline` | `--phase hwmcc` |
|--|-------------------|-----------------|
| download | 否（需已下載） | 是 |
| baseline | 是 | 是 |
| llm | **否** | 是（自動選 competition medium/slow/timeout） |
| report | 否（需另跑） | 是 |

---

## 兩層驗收（LLM 階段）

| 層級 | 問什麼 | 通過標準（例） |
|------|--------|----------------|
| **通道健康** | sidecar ↔ pono 是否正常？ | `responses = requests × K`、`batch_timeouts = 0`、無 JSONL parse 錯誤 |
| **品質** | LLM block 是否被 IC3 收下？ | `accepted ≥ 1` 或 `rejected_initial` / `induction_fail` 有改善趨勢 |

**Smoke PASS 只代表通道健康，不代表 `accepted > 0`。**

---

## 標準資源設定（32 核 / 125 GiB）

| 參數 | 值 | 說明 |
|------|-----|------|
| `--parallel` | **8** | baseline / LLM 皆預設 8 worker |
| `--memory-limit` | **14** | 125GiB ÷ 8 ≈ 15，留 OS 餘量 |
| `--snapshot-max-clauses` | **0** | Track A digest（僅 LLM phase） |
| `--llm-drain-sec` | **300** | sidecar drain（僅 LLM phase） |

伺服器 RAM 硬上限約 **8–10 開**（14GB/案）；CPU 軟上限 ~12–16 開。常態 **8 開**。

---

## Tier 0 — 通道 smoke（必做）

```bash
export DEEPSEEK_API_KEY=sk-...
cd build && touch ../pono.cpp && make -j4 pono-bin
cd ..
SNAPSHOT_MAX=0 BATCH_WAIT_SEC=300 ./scripts/smoke_p040.sh
```

詳見 [`llm_worker/README.md`](../llm_worker/README.md) § Smoke。

---

## Tier 1 — find-solvable（有 refinement、非太快）

```bash
python3 scripts/run_benchmarks.py --phase find-solvable \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --output-dir bench_results/hwmcc_baseline_<date> \
  --engine ic3ia
```

**掃描範圍：** `collect_benchmarks` 的**全部**案（預設 1052）；`--find-max N` 或 `--limit N` 僅用於除錯子集。

**納入 `candidates.json` 條件（同時滿足）：**

| 條件 | 說明 |
|------|------|
| 探測解出 sat/unsat | `-v 2` 短跑（≤300s，或 baseline 解出案依其 wall_time 放寬） |
| `blocking_phases > 0` | 有 IC3 blocking / refinement（排除 too simple） |
| `wall_time ≥ --fast-threshold` | 預設 **30s**（排除 too fast） |

**若同目錄有 `results_baseline.csv`：** 先跳過 baseline 已為 timeout/memout/error 或 fast（&lt;30s）的案，避免重跑 ~700+ 明顯不符條件的探測。

產物：`candidates.json`（含 `blocking_phases`、`wall_time`）。

**目的：** 找「本机能解、有 refinement、不太快」的 LLM 候選；**不是**所有 solvable 案。Tier 2 再 ∩ baseline 解出。

---

## Tier 2 — LLM（Phase A / Phase B）

先完成 baseline。用 `--llm-phase` 從 `results_baseline.csv` 選案（自動含 **p040** 對照若不在子集內）。

| `--llm-phase` | 子集 | 目的 |
|---------------|------|------|
| **a** | 非 fast 解出（wall≥30s 的 sat/unsat，約 145）+ p040 | **算法有效性**（accepted、時間、match） |
| **b** | timeout + memout（約 665）+ p040 | **能否多解**（baseline 未解 → LLM 後 sat/unsat） |
| `competition` | 舊邏輯：competition medium/slow/timeout | legacy |

```bash
OUT=bench_results/hwmcc_baseline_<date>
export DEEPSEEK_API_KEY=sk-...

# Phase A — 算法有效性
nohup python3 scripts/run_benchmarks.py --phase llm --llm-phase a \
  --output-dir "$OUT" --hwmcc-dir ~/hwmcc_benchmarks \
  --parallel 8 --memory-limit 14 --snapshot-max-clauses 0 \
  > "$OUT/llm_phase_a.log" 2>&1 &

# Phase B — 多解 case（A 完成後或另開）
nohup python3 scripts/run_benchmarks.py --phase llm --llm-phase b \
  --output-dir "$OUT" --hwmcc-dir ~/hwmcc_benchmarks \
  --parallel 8 --memory-limit 14 --snapshot-max-clauses 0 \
  > "$OUT/llm_phase_b.log" 2>&1 &
```

產物：
- `results_llm_phase_a.csv` / `results_llm_phase_b.csv`
- `llm_targets_phase_a.json` / `llm_targets_phase_b.json`
- `runs/{run_id}_phase_a/`、`runs/{run_id}_phase_b/` 歸檔

（可選 Tier 1 `find-solvable` 僅用於 blocking 分析；Phase A/B 選案**不依賴** blocking 探測。）

---

## Tier 3 — 全管線（等同舊預設）

```bash
python3 scripts/run_benchmarks.py --phase hwmcc \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --parallel 8 \
  --memory-limit 14
```

等價：`download` → `baseline` → `llm` → `report`。若要**先只 baseline**，勿用此 phase。

---

## Phase 對照

| `--phase` | 內容 |
|-----------|------|
| `test` | `make check` + schema + Phase L pytest |
| `download` | 下載 benchmark / CSV |
| **`baseline`** | **`--llm-gen-mode none`，寫 `results_baseline.csv`** |
| **`baseline-patch`** | **從 `nohup.log` 重建 partial；timeout/memout 信 log，error/unknown 重跑** |
| `report` | CSV → `report.md` + `classification.csv` |
| `find-solvable` | 探測 blocking phases → `candidates.json` |
| `llm` | sidecar + async-cti + Phase L 歸檔 |
| `hwmcc` | download + baseline + llm + report |

---

## 相關文件

- 平行政策：[`plans/experiment_parallel_policy.md`](plans/experiment_parallel_policy.md)
- 總檢視：[`plans/experiment_plan_review.md`](plans/experiment_plan_review.md)
- 協議：[`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)
