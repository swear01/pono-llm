# Clause 品質提升計劃 Q2（基線版本）

**狀態：** 基線已標記；Q2 實作進行中  
**基線 commit：** （見 git tag `pre-q2-clause-quality` 或本文件所在 commit）  
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

| ID | 內容 | 檔案 |
|----|------|------|
| Q2.1 | Init-aware prompt + 反例 | `ic3_frame_v1.txt`, `prompt_format.py` |
| Q2.2 | `max_block_clauses=1` 實驗旗標 | `options/`, harness |
| Q2.3 | Feedback 完整 disjuncts + clause_idx | `llm_generalizer.cpp` |
| Q2.4 | 小 batch digest / symbol hint | 視 A/B 結果 |

## 實驗矩陣

- **A0** Phase A 基線
- **A1** Q2.1
- **A2** Q2.1 + Q2.2
- **A3** Q2.1 + Q2.2 + Q2.3

子集：p040 + 10 案高 `rejected_initial`（見 `analyze_accept_diagnosis.py` D1）。

## 量測

```bash
python3 scripts/analyze_accept_diagnosis.py --phase all
```

## 後續 Gate

- 達標 → 擴 tier + Phase A′ 全量（~1900 API）
- B2 仍高 → Q2.4
- 仍低 → Track B `drop_literals`
- induction_fail 主導（ILA）→ X1
