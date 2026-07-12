> Archived: 2026-07-11
> Reason: Historical reactive IC3/sidecar experiment plan; superseded by corrected Phase 1+2 validation.
> Replacement: docs/plan.md
> Status: historical only; do not use as active truth.

# 實驗計畫總檢視

**狀態：** 進行中（Track A / 八開 / Phase L 已完成；**Baseline 全量 → find-solvable → Phase E LLM**）  
**日期：** 2026-06  
**相關：** [`experiment_parallel_policy.md`](experiment_parallel_policy.md)、`hwmcc_experiment_tiers.md` (archived/missing historical reference)

---

## 已完成

### Track A — Frame 品質

- [x] P0 contrastive feedback + Repair
- [x] P-parallel per-sample hint（程式保留；**預設 K=1**，僅 `--llm-parallel-samples>1` 時多 hint）
- [x] P0.5 symbol hints
- [x] P1 attempt1 省略 bodies + proof_context
- [x] P2 clause_digest + RAP-ranked samples（C++）
- [x] CTI digest prompt 截斷（防大 batch 膨脹）
- [x] pytest + smoke 通道驗證

**p040 實測：** `batch_timeouts=0`；~6–7 KB prompt；~4.4s/batch；曾 `accepted=1`。

### 八開政策

- [x] `run_benchmarks --parallel` 預設 8
- [x] `--memory-limit` 預設 14、`--snapshot-max-clauses` 0、`--llm-drain-sec` 300
- [x] `sidecar --max-inflight-requests` 預設 8
- [x] 文件：tiers / integration / README / DOC_INDEX

### 架構（定案）

每 benchmark **一組** `(pono + sidecar + 獨立 JSONL)`；八開 = 8 組同時存在。  
「預先開 sidecar」= 同案內 sidecar 早於 pono 1–2s，非全域 sidecar 池。

---

## 首輪實驗教訓

| 發現 | 行動 |
|------|------|
| LLM 子集用 `--parallel 1` → ~70 min | 已改預設 8；重跑應 ~10 min |
| find-solvable 30 案無 blocking | Tier1 需輸出 `candidates.json`；勿當 LLM 子集來源 |
| beem 前 N 案全 timeout、無 LLM flush | 子集改 p040 + `blocking_phases > 0` 候選 |
| tmpdir 在 `/tmp` 跑完即失 | **Phase L 歸檔**（見下） |
| baseline log 大量 error/unknown、0 sat/unsat | harness 未讀 pono 兩行 stdout；已修 `_parse_pono_stdout` |
| baseline 中斷後無 resume | 新增 `baseline-patch` + `baseline --skip-partial` 合併流程 |
| baseline 少數 `error`（IC3IA+bzla） | 真引擎限制（interpolation / SMT unknown），非 harness bug；見 tiers § `result` 語意 |

---

## 紀錄與分析

| 層級 | 現況 | 夠用？ |
|------|------|--------|
| CSV `results_*.csv` | 僅 `llm_accepted/rejected/errors` | 粗結果夠；品質分布不夠 |
| `/tmp/pono_bench_*` | 完整 JSONL + llm_log | 詳細但**未歸檔** |
| smoke manifest | 通道 + `llm_timing` | 單案夠 |

**歸檔體積估計：** 有 LLM 活動 ~0.3–0.5 MB/案；單次 run 多數 < 20 MB（磁碟非瓶頸）。

**API 政策：** 成本不設上限；parallel / 子集大小依 **RAM、CPU、選案品質**，不為省 API 縮規模。

---

## 待辦（執行順序）

### Phase Baseline — 全量 HWMCC（進行中）

- [x] **B0** harness stdout 解析修正（`sat\nb0` → 讀第一行）
- [x] **B0b** `baseline-patch` + `--skip-partial` resume / 合併
- [ ] **B1** `--phase baseline` 全年份（2020+2024+2025），八開 → `results_baseline.csv`
  - 本輪：`hwmcc_baseline_20260607` — 已 suspend → `baseline-patch` → `--skip-partial` resume
- [ ] **B2** `--phase report` → `classification.csv` + `report.md`
- [ ] **B3** `--phase find-solvable`（全量掃描，排除 too fast / 0 blocking）→ `candidates.json`
- [ ] **B4** LLM Phase A (`--llm-phase a`) + Phase B (`--llm-phase b`)；見 tiers § Tier 2

**命令：** 見 `hwmcc_experiment_tiers.md` (archived/missing historical reference) § Baseline phase。

### Phase L — 實驗紀錄強化（已完成）

- [x] **L1** 每案 LLM 結束後歸檔 tmpdir → `output-dir/runs/<run_id>/<bench_slug>/`
- [x] **L2** `req_n > 0` 才複製 `requests.jsonl`；一律複製 `llm_log`、`responses`、stderr
- [x] **L3** 擴充 `_parse_llm_stats` → CSV 寫入完整 `LLM_STATS` 欄位
- [x] **L4** 每次 run 寫 `run_manifest.json`（parallel、snapshot、model、時間）
- [x] **L5** find-solvable 輸出 `candidates.json`
- [x] **L6** 更新 [`experiment_parallel_policy.md`](experiment_parallel_policy.md) §紀錄
- [x] **L7** Phase L pytest：[`scripts/tests/test_run_benchmarks_phase_l.py`](../../scripts/tests/test_run_benchmarks_phase_l.py)（30 tests，納入 `--phase test`）

**檔案：** [`scripts/run_benchmarks.py`](../../scripts/run_benchmarks.py)

### Phase E — 八開重跑

- [ ] **E1** p040 smoke（`SNAPSHOT_MAX=0`）
- [ ] **E2** 八開 LLM 子集（正確選案 + `parallel 8`）
- [ ] **E3** 輸出至 `bench_results/run_<date>/`

### Phase Q — 品質決策

- [ ] **Q1** 依歸檔 `LLM_STATS` 評估 `rejected_initial` / `accepted`
- [ ] **Q2a** 若改善不足 → 啟動 Track B（cube-subset）
- [ ] **Q2b** 若穩定 `accepted≥1` → 建 `scripts/ab_snapshot_quality.sh`（A0 vs A3）
- [ ] **Q3** 填寫 [`lemma_expressiveness_roadmap.md`](lemma_expressiveness_roadmap.md) § Gate 0（是否需擴 expressiveness）
- [ ] **Q4** 若 Gate 0 觸發 → 排程 **Phase X1**（`refine_predicate` 接入）；見該文件

---

## 執行順序

```
Phase L（已完成）
  → Phase Baseline（全量 baseline + report + find-solvable）
  → Phase E（LLM，八開，正確選案）
  → Phase Q（Track B 或 A/B；或 Phase X1 見 lemma roadmap）
```

觸發：「跑 baseline」／「執行 Phase E」。

---

## 風險

- Swap 已滿：常態 `--memory-limit 14`，勿 >10 開
- 子集全 timeout 且 `req_n=0`：選案問題，非通道故障
- `bench_results/` 建議自管備份（未必進 git）
