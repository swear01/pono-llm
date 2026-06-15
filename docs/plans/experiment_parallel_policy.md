# 實驗平行度政策（八開預設）

**狀態：** 已實施（harness + 文件）  
**日期：** 2026-06  
**相關：** [`hwmcc_experiment_tiers.md`](../hwmcc_experiment_tiers.md)、[`ARCHITECTURE.md`](../ARCHITECTURE.md)

---

## 政策

所有 HWMCC / LLM 批次實驗預設 **8 路平行**（`--parallel 8`），除非單案除錯。

LLM 成本不設上限；優先 **牆鐘時間**。

---

## 架構

八開 = **8 個獨立 worker**，每個 worker 各有一組：

- `pono`（IC3IA + async-cti）
- `sidecar.py`（獨立 `req/resp/log` JSONL 於專用 tmpdir）

**不是**單一 sidecar 服務 8 個 benchmark。

單一 sidecar 內部並行（與跨案八開正交）：

| 參數 | 預設 | 說明 |
|------|------|------|
| `--max-inflight-requests` | 8 | 同時處理多條 request line |
| `--llm-parallel-samples` | **1** | 每條 batch API 次數（可選 K>1；預設單樣本） |

---

## 伺服器容量（本機：32 核 / 125 GiB）

| 等級 | 開數 | 說明 |
|------|------|------|
| **標準** | **8** | CPU、RAM 平衡；實驗預設 |
| RAM 硬上限 | ~8–10 | `--memory-limit 14` → 125÷14≈9 |
| CPU 軟上限 | ~12–16 | 再上去 solver 互搶、邊際變慢 |
| 不建議 | >16 | 32 核上 IC3IA 過密 |

Swap 僅 2 GiB 且常滿 — **不可依賴 swap**。

---

## Harness 預設（`run_benchmarks.py`）

| 參數 | 預設 |
|------|------|
| `--parallel` | 8 |
| `--memory-limit` | 14 GB |
| `--snapshot-max-clauses` | 0（Track A digest） |
| `--llm-drain-sec` | 300 |
| `--llm-batch-wait-sec` | 300（傳給 pono） |

每個 LLM job 另傳：`llm_max_inflight=8`、`llm_parallel_samples=1`（與 pono/sidecar 預設一致）。

---

## 標準命令

```bash
# Baseline 全量（無 LLM、無 API key）
python3 scripts/run_benchmarks.py --phase baseline \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 \
  --output-dir bench_results/hwmcc_baseline_<date> \
  --parallel 8 \
  --memory-limit 14

# LLM（baseline CSV 已存在於同 output-dir）
python3 scripts/run_benchmarks.py --phase llm \
  --hwmcc-dir ~/hwmcc_benchmarks \
  --output-dir bench_results/hwmcc_baseline_<date> \
  --parallel 8 \
  --memory-limit 14 \
  --snapshot-max-clauses 0

# Tier 0 smoke（單案，非八開）
SNAPSHOT_MAX=0 BATCH_WAIT_SEC=300 ./scripts/smoke_p040.sh
```

Baseline 行為詳見 [`hwmcc_experiment_tiers.md`](../hwmcc_experiment_tiers.md) § Baseline phase。

### Baseline 中斷恢復（patch + skip-partial）

```bash
OUT=bench_results/hwmcc_baseline_<date>

# 1) 從 nohup.log 補齊已完成案（重跑 log 裡 error/unknown）
python3 scripts/run_benchmarks.py --phase baseline-patch \
  --output-dir "$OUT" --baseline-log "$OUT/nohup.log" \
  --parallel 8 --memory-limit 14

# 2) 跳過 partial，跑剩餘案，自動合併 → results_baseline.csv
python3 scripts/run_benchmarks.py --phase baseline --skip-partial \
  --output-dir "$OUT" --hwmcc-dir ~/hwmcc_benchmarks \
  --hwmcc-years 2020,2024,2025 --parallel 8 --memory-limit 14
```

**注意：** 不支援從 log 直接 resume 全量；需先 `baseline-patch` 產出 `results_baseline_partial.csv`。

---

## 牆鐘估算（timeout 主導）

`wall ≈ ceil(N / parallel) × timeout + drain`

例：7 案、600s timeout、parallel=8 → **~10–12 分鐘**（非串行 ~70 分鐘）。

---

## 驗證八開

```bash
# 試跑時另開終端
ps aux | grep -E '[b]uild/pono|[s]idecar.py' | wc -l
# 預期：最多 16（8 pono + 8 sidecar）
```

各 worker tmpdir 內應有獨立 `llm_log.jsonl`。

---

## 實驗紀錄（Phase L，已實施）

`--phase llm` 跑完後，除 `results_llm.csv` 外，每 run 歸檔至 `{output-dir}/runs/{run_id}/`：

```
bench_results/
  results_llm.csv              # 完整 LLM_STATS 欄位
  candidates.json              # find-solvable 輸出（Tier 1）
  runs/
    20260603_120000/
      run_manifest.json        # parallel、model、snapshot、每案摘要
      2024_bv_p040/
        llm_log.jsonl
        responses.jsonl
        requests.jsonl         # 僅 req_n > 0
        pono_stderr.log
        sidecar_stderr.log
```

| 歸檔內容 | 條件 | 估計大小 |
|----------|------|----------|
| `llm_log.jsonl` | 一律 | < 5 KB/案（無活動則空） |
| `responses.jsonl` | 一律 | < 50 KB/案 |
| `requests.jsonl` | 僅 `req_n > 0` | ~0.3–0.5 MB/案（digest 後） |
| `pono_stderr.log` / `sidecar_stderr.log` | 一律 | < 100 KB/案 |

CLI：`--run-id` 覆寫歸檔目錄名；`--archive-full-requests` 強制存 `requests.jsonl`（除錯用）。

計畫細項：[`experiment_plan_review.md`](experiment_plan_review.md) Phase L。
