# Clause 品質提升計劃 Q2

**狀態：** Q2.1+Q2.3 已實作；Q2.2 harness 就緒；p040 3 輪 smoke 已驗證  
**基線 commit：** `aa7c3ba`（tag `pre-q2-clause-quality`）  
**診斷：** `diagnosis/D_summary.md`、`diagnosis/D3b_init_semantics.json`

## 目標

- p040（`vgasim_imgfifo-p040`）：`accept/API ≥ 40%`
- 11 案高失敗子集：`accept/API ≥ 20%`
- 全量 tier 分開驗收（ILA 另議）

## Phase A 基線

| 指標 | 值 |
|------|-----|
| accept / API | ~1.0%（20 / ~1899） |
| rejected_initial | ~87% reject |
| D3b B2（CTI/init 不一致） | 64.6% |
| D3b C2（OR 兄弟 disjunct） | 34.9% |
| retry API 占比（a2+a3） | ~64% |

## Q2 實作項

| ID | 狀態 | 內容 | 檔案 |
|----|------|------|------|
| Q2.1 | ✅ | Init-aware prompt + B2/C2 反例 | `ic3_frame_v1.txt`, `prompt_format.py`, `sidecar.py` |
| Q2.2 | ✅ harness | `max_block_clauses=1` 實驗（`--llm-max-block-clauses` / `MAX_BLOCK_CLAUSES`） | `options/`, `scripts/smoke_p040.sh` |
| Q2.3 | ✅ | Feedback 完整 `block_clauses` + `clause_idx` | `llm_generalizer.cpp`, `prompt_format.py` |
| Q2.4 | 待定 | 小 batch digest / symbol hint | 視綜合 A/B 結果 |

## 實驗矩陣

| 組別 | 內容 |
|------|------|
| **A0** | Phase A 基線（tag `pre-q2-clause-quality`） |
| **A1** | Q2.1 only（system prompt） |
| **A2** | Q2.1 + Q2.2（`max_block_clauses=1`） |
| **A3** | Q2.1 + Q2.2 + Q2.3（init prompt + 單 clause + enriched feedback） |

子集：p040 + 10 案高 `rejected_initial`（見 `analyze_accept_diagnosis.py` D1）。

### p040 smoke 結果（vgasim_imgfifo，`K=1`，`max_attempts=3`，3 輪）

| 組別 | accept/API | rejected_initial | Δ vs 對照 |
|------|------------|------------------|-----------|
| A0 baseline | **6.7%** (2/30) | 19 | — |
| A1 Q2.1+Q2.3, mbc=3 | **17.2%** (5/29) | 18 | +10.6 pp vs A0 |
| A2 Q2 + mbc=1 | **12.9%** (4/31) | 18 | +6.2 pp vs 同輪 mbc=3 |

**Q2.3 驗證：** `attempt≥2` request 含 `clause_idx` + `block_clauses`；`format_feedback_block` 輸出 `failed_clause[idx]`。

**解讀：** 單次 smoke 波動大（曾 0% vs 25%）；3 輪平均後 Q2.1+Q2.3 明顯優於 baseline，但距 40% 目標仍遠。`mbc=1` 降低 `rejected_initial`，建議納入 A3 綜合配置。

## Harness

```bash
# 單次 smoke（預設 qspiflash；p040 請設 BTOR）
BTOR=$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2 \
  MAX_ATTEMPTS=3 MAX_BLOCK_CLAUSES=1 STRICT=0 bash scripts/smoke_p040.sh

# 3 輪 A0 vs A1（baseline tag vs HEAD）
ROUNDS=3 MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_p040_multiround.sh

# 3 輪 mbc=3 vs mbc=1（HEAD only）
ROUNDS=3 MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_mbc1_multiround.sh

# 3 輪 A0 vs A3 綜合（baseline vs Q2.1+Q2.2+Q2.3, mbc=1）
ROUNDS=3 MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_combined_multiround.sh
```

歸檔量測：

```bash
python3 scripts/analyze_accept_diagnosis.py --phase all
```

## 後續 Gate

- A3 綜合 ≥ 25%（p040 3 輪均值）→ 擴 11 案子集
- 達標 → tier + Phase A′ 全量（~1900 API）
- B2 仍高 → Q2.4
- 仍低 → Track B `drop_literals`
- induction_fail 主導（ILA）→ X1
