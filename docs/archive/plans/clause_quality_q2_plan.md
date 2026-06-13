# Clause 品質提升計劃 Q2

**狀態：** ✅ 已發布（tag `post-q2-clause-quality`）  
**基線 commit：** `aa7c3ba`（tag `pre-q2-clause-quality`）  
**發布 commit：** 見 tag `post-q2-clause-quality`  
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
| **A3 綜合**（Q2.1+Q2.2+Q2.3, mbc=1） | **9.4%** (3/32) | 22 | +9.4 pp vs A0（同腳本 3 輪） |

**Q2.3 驗證：** `attempt≥2` request 含 `clause_idx` + `block_clauses`；`format_feedback_block` 輸出 `failed_clause[idx]`。

**解讀：** 單次 smoke 波動大（曾 0% vs 25%）；多輪平均後 Q2 優於 baseline，但距 40% 目標仍遠。表現最好的是 **HEAD + mbc=3**（17.2%，實作上為 Q2.1+Q2.3）；A3 綜合（+mbc=1）本輪 9.4%，**尚未優於前者**，故 **不** 改預設 `max_block_clauses`。

### 品質測試標準（multi-round）

- **目的：** 降低 LLM 隨機性造成的量測誤差（不是多跑幾輪把成績磨高）
- **方法：** 同一配置、同一 benchmark，跑 **5 輪獨立 smoke**，將 `accepted` / `requests` **加總** 得 accept/API
- **預設：** `scripts/ab_q2_*_multiround.sh` 的 `ROUNDS` 預設 **5**（可用環境變數覆寫）
- **品質 A/B 建議參數：** `MAX_ATTEMPTS=3`（與 C++ 預設一致）、`K=1`；單次 `smoke_p040.sh` 仍預設 `MAX_ATTEMPTS=1` 作 channel health check

### 目前預設 vs 實驗組別

| 項目 | C++/HEAD 預設 | 實驗 A1（矩陣定義） | 實測最佳 arm |
|------|---------------|---------------------|--------------|
| Q2.1 init prompt | ✅ 已上線 | ✅ | HEAD |
| Q2.3 enriched feedback | ✅ 已上線 | ❌（A1 僅 Q2.1） | HEAD |
| `max_block_clauses` | **3** | 3 | **3**（mbc=1 未勝出） |
| `max_attempts` | **3** | 3 | 3 |

**結論：** 目前 **HEAD 預設 ≈ 實測最佳配置**（Q2.1+Q2.3、mbc=3、attempts=3）。嚴格矩陣上的「A1 only」未單獨量測；實作時 Q2.1 與 Q2.3 已一併合入 main。

## Harness

```bash
# 單次 smoke（預設 qspiflash；p040 請設 BTOR）
BTOR=$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2 \
  MAX_ATTEMPTS=3 MAX_BLOCK_CLAUSES=1 STRICT=0 bash scripts/smoke_p040.sh

# 品質測試（預設 5 輪）：A0 vs HEAD
MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_p040_multiround.sh

# 5 輪 mbc=3 vs mbc=1（HEAD only）
MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_mbc1_multiround.sh

# 5 輪 A0 vs A3 綜合（baseline vs Q2.1+Q2.2+Q2.3, mbc=1）
MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_combined_multiround.sh
```

歸檔量測：

```bash
python3 scripts/analyze_accept_diagnosis.py --phase all
```

## 後續 Gate

- A3 綜合 ≥ 25%（p040 多輪均值）→ 擴 11 案子集（本輪 9.4%，未達）
- 達標 → tier + Phase A′ 全量（~1900 API）
- B2 仍高 → Q2.4
- 仍低 → Track B `drop_literals`
- induction_fail 主導（ILA）→ X1
