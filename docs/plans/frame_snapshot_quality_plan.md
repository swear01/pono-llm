# Frame Snapshot 品質改進計劃（v6 終稿）

**狀態：** Track A 已實施；實驗 harness 預設 parallel 8（見 [`experiment_parallel_policy.md`](experiment_parallel_policy.md)）  
**日期：** 2026-06  
**相關：** [`ic3_frame_v1_integration.md`](../ic3_frame_v1_integration.md)、[`hwmcc_experiment_tiers.md`](../hwmcc_experiment_tiers.md)

---

## 核心結論

品質不是靠「多看 frame tail clause」，而是：

1. **CTI 上 MIC 式 generalize**（drop incidental literals）
2. **witness 驅動的外科修正**（contrastive feedback + Repair 指令）
3. **goal-conditioned 檢索**（top-5 相關 clause + literal_stats，非 tail dump）

**tail-N 預設廢止**；僅 `--snapshot-mode tail` debug 保留。

---

## 現況與 smoke 診斷

| 現象 | 解讀 |
|------|------|
| `accepted=0`, `rejected_initial=9`, `induction_fail=3` | 品質問題，非通道（`batch_timeouts=0`） |
| prompt「do not restate clauses」卻送 tail-50 | 誘導複讀舊 block |
| K parallel samples 同一份 user prompt | diversity 不足 |
| `symbol_registry` 有 Verilog，sidecar 只送 name+bad | init 相關 reject 偏高 |

---

## 文獻依據（精簡）

| 來源 | 啟示 |
|------|------|
| [IC3Syn](https://arxiv.org/html/2605.24619v1) | focused bad-state batch，非 full invariant |
| [CIll](https://arxiv.org/html/2602.23389) | CTI + 結構化 CEX 迴圈 |
| [CTG/MIC](https://www.cs.utexas.edu/~hunt/FMCAD/FMCAD13/papers/85-Better-Generalization-IC3.pdf) | witness = generalization 障礙 |
| [Rango RAP](https://arxiv.org/html/2412.14063) | proof-state 條件檢索 top-K |
| [ConVer ICE](https://arxiv.org/html/2605.27051) | 分類 CEX + repair directive |
| [0514 cube-subset](docs/0514_async_ic3ia.md) | attempt1 `drop_literals` 最低風險 |
| [IC3-Evolve](https://arxiv.org/html/2604.03232v1) | witness-gated 下多數 reject 是常態 |

---

## 目標架構

```
Primary:   CTI digest + Contrastive feedback/Repair
Secondary: symbol hints + clause literal_stats + RAP top-5
Tertiary:  accepted blocks（同 run positive example）
廢止:      tail-N 預設
```

### 驗收（p040）

- **Hit@K**：`accepted ≥ 1`
- `rejected_initial` 降 ≥30%（P0 後）
- `user_prompt_bytes` < 15KB

---

## Track A — 上下文（建議先做）

| ID | 內容 | 工時 | 主要檔案 |
|----|------|------|----------|
| P0 | Contrastive feedback 三區 + Repair 一行 | 0.5d | `prompt_format.py`, `ic3_frame_v1.txt` |
| P-parallel | per-`sample_id` generalization hint | 0.25d | `sidecar.py` |
| P0.5 | symbol_registry 輕量 hints | 0.5d | `sidecar.py` |
| P1 | attempt1 省略 clause bodies + `proof_context` | 0.5d | `ic3base.cpp`, `sidecar.py` |
| P1.5 | witness 選擇（優先 CTI/衝突 ref） | 0.5d | `ic3base.cpp` |
| P2 | clause_digest + MIC hint + negative_stats | 1.5d | C++ + `prompt_format.py` |
| P2.5 | lightweight RAP top-5 + pos/neg ex | 1d | C++ + sidecar |

### P0 — Feedback 格式（範例）

```text
=== Correctness (init) ===
[0] rejected_initial  witness: state93=0
    Repair: block MUST be false when state93=0 at initial state

=== Inductiveness (CTG) ===
[1] induction_failed  witness: next(state12)=1
    Repair: block must rule out transition where state12@next=1
```

witness 語意見 [`integration.md` L271–272](../ic3_frame_v1_integration.md)。

### P-parallel — sample 策略

| sample_id | hint |
|-----------|------|
| 0 | minimal block (1–2 disjuncts); drop datapath |
| 1 | block from high-freq clause_stats only |
| 2 | OR of 3–4 literals covering CTI cores |

---

## Track B — 任務重定義（視 A/B）

attempt1：`drop_literals[]` from CTI batch → C++ MIC 轉 block。  
需擴充 schema；修正舊 `cube_subset_to_blocking` 格式 bug（[`BUG_ANALYSIS.md`](../BUG_ANALYSIS.md)）。

---

## A/B 矩陣

腳本（待建）：`scripts/ab_snapshot_quality.sh`（A/B 跑法與 Tier 2 相同，**`--parallel 8`**）

| 組 | 設定 |
|----|------|
| A0 | tail-50 baseline |
| A1 | P0 + P-parallel + P0.5 |
| A2 | A1 + P1 omit |
| A3 | A2 + P2 digest |
| A4 | A3 + P2.5 RAP |
| B1 | A2 + Track B subset |

**決策：** A1 後 `rejected_initial` 未降 → 提前 Track B；任一組 `accepted≥1` → 更新 smoke 預設。

---

## P0 執行清單（最小增量，約 1 天）

1. `format_feedback_block` — 三區 + Repair
2. `build_batch_user_prompt` — per-sample hint + symbol hints
3. `ic3_frame_v1.txt` — witness 說明
4. pytest + smoke（通道仍須 PASS）
5. A/B A0 vs A1 on p040

---

## 後續（與實驗計畫銜接）

Track A 程式已完成；下一階段見 [`experiment_plan_review.md`](experiment_plan_review.md)：

1. **Phase L** — harness 歸檔 + CSV 完整 LLM_STATS
2. **Phase E** — 八開重跑（p040 + 正確選案）
3. **Phase Q** — 決定 Track B 或 A/B（`ab_snapshot_quality.sh`）

## 執行觸發

- **「執行 Phase L」** — 實驗紀錄強化（[`run_benchmarks.py`](../../scripts/run_benchmarks.py)）
- **「執行 Phase E」** — 八開重跑實驗
- **「執行 Track B」** — cube-subset schema
