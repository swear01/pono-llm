# Clause 品質提升計劃 Q3

**狀態：** 規劃中（Q2 已 tag `post-q2-clause-quality`）  
**前置：** [`clause_quality_q2_plan.md`](clause_quality_q2_plan.md)、`diagnosis/D3b_init_semantics.json`  
**品質量測標準：** 5 輪獨立 smoke，加總 `accepted/requests`（見 Q2 plan）

## Q2 收斂摘要

| 指標 | Phase A | Q2（p040 3 輪） | 目標 |
|------|---------|-----------------|------|
| accept/API | ~1.0% | **17.2%**（HEAD 預設） | p040 **40%** |
| 主因 | B2 64.6%、C2 34.9% | `rejected_initial` 仍主導 | — |

**已上線預設（= 17.2% 那組）：** Q2.1 init prompt + Q2.3 enriched feedback、`mbc=3`、`max_attempts=3`、`K=1`。

**未採納：** `max_block_clauses=1`（A3 綜合未勝出 mbc=3）。

### Q2 現行方法診斷（6 輪 p040 smoke 彙總）

來源：`diagnosis/Q2_current_method_summary.md`、`scripts/diagnose_q2_smoke.py`

| 發現 | 數值 | 含義 |
|------|------|------|
| `rejected_initial` 仍 **100% B2** | 45/45 | Q2.1 反例 **未**消除 CTI/init 不一致 |
| CTI 字面抄襲率 | **98.4%** disjuncts | 模型幾乎直接複製 CTI/digest 字面 |
| MIC top-1 否定形狀命中 | **0%** | 未產出機械式 digest-negate block |
| 單 disjunct clause | **100%** | p040 smoke 上 C2 幾乎為 0；**收窄 OR 非當務之急** |
| Top B2 pattern | `init0_clause_eq_0_pol_False` | init=#b0 卻用 `!ref=0` 等「看起來像 CTI」的字面 |

**結論：** Q3 應優先 **Q3.1 witness 模板 + Q3.2 強制 digest 否定**，而非 mbc=1。

## Q3 目標

| 層級 | accept/API | 備註 |
|------|------------|------|
| **G1** p040（vgasim_imgfifo） | ≥ **40%** | 5 輪均值 |
| **G2** 11 案高 `rejected_initial` 子集 | ≥ **20%** | 5 輪均值 |
| **G3** tier 分開 | ILA / BV 分開驗收 | ILA 可較低，induction 主導另議 |

## 診斷驅動優先序（Q3）

仍從 D3b 出發；Q2 後預期 B2 占比仍高（p040 smoke 上 `rejected_initial` 未明顯下降）。

| 優先 | 問題 | Q3 對應 | 預期 |
|------|------|---------|------|
| P1 | **B2** CTI/init 不一致（64.6%） | Q3.1 witness 驅動修復模板 | 降 `rejected_initial` |
| P1 | 模型仍抄 CTI 字面 | Q3.2 digest top-1 **否定** block | 單 disjunct、避 init-true |
| P2 | **C2** OR 兄弟 disjunct（34.9%） | Q3.3 prompt 強制 ≤1 disjunct/clause | 不改 mbc 預設，先收窄 OR |
| P2 | retry 仍盲試 | Q3.4 feedback→`negative_literal_stats` 進 snapshot | attempt≥2 避開失敗字面 |
| P3 | 跨案泛化 | Q3.5 11 案子集 5 輪 harness | 驗 G2 |
| P3 | tier 差異 | Q3.6 ILA vs BV 分開報表 | 避免單一門檻誤殺 |

## Q3 實作項

| ID | 內容 | 檔案 | 依賴 |
|----|------|------|------|
| **Q3.0** | 5 輪 p040 + 11 案子集 re-baseline（HEAD 預設） | `scripts/ab_q3_subset_multiround.sh` | — |
| **Q3.1** | Witness 修復模板：`init0`→禁 `ref=1 pol T`；feedback 附 `init_check: ref=witness_val` | `prompt_format.py`, `ic3_frame_v1.txt` | — |
| **Q3.2** | Digest 導向：「用高頻 literal 的 **否定** 做單一 disjunct，勿照搬 CTI cube」 | `prompt_format.py`, `sidecar.py` | — |
| **Q3.3** | 每 clause ≤1 disjunct（prompt 硬規則 + 範例）；保留 mbc=3 作策略多樣性 | `ic3_frame_v1.txt` | 與 Q3.2 同批 |
| **Q3.4** | `_negative_stats_from_feedback` 併入 `format_frame_snapshot`（attempt≥2） | `prompt_format.py` | Q2.3 已有 JSON |
| **Q3.5** | 11 案子集 harness（來自 `analyze_accept_diagnosis.py` D1 `zero_accept_high_reject_subset`） | `scripts/`, `docs/` | Q3.0 |
| **Q3.6** | 子集結果按 tier 彙總（ila / bv / …） | `scripts/analyze_accept_diagnosis.py` 或新報表 | Q3.5 |

## 實驗矩陣（Q3）

在 **HEAD 預設（Q2 已上線）** 上疊加，5 輪量測：

| 組別 | 內容 |
|------|------|
| **B0** | Q2 預設（對照） |
| **B1** | B0 + Q3.1 witness 模板 |
| **B2** | B1 + Q3.2 digest 否定 |
| **B3** | B2 + Q3.3 單 disjunct |
| **B4** | B3 + Q3.4 negative stats |

**決策規則：** 僅當 B{k} 在 p040 5 輪均值 **≥ B0 + 5 pp** 且 `rejected_initial` 下降，才合入 main。

## Harness（規劃）

```bash
# Q3.0：p040 5 輪 re-baseline（Q2 預設）
BTOR=$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2 \
  MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_p040_multiround.sh

# Q3.5：11 案子集（待實作）
# MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q3_subset_multiround.sh
```

## Gate（Q3 結束條件）

| 結果 | 下一步 |
|------|--------|
| G1+G2 達標 | Phase A′ 全量 rerun（~1900 API）；更新 smoke 預設 |
| p040 ≥25% 但 <40% | 再加一輪 prompt（B2 字面 blacklist）或 Q3.7 symbol reset hint |
| p040 <25% 且 B2 仍 >50% | **Track B** `drop_literals` / cube-subset（見 `frame_snapshot_quality_plan.md`） |
| ILA induction_fail 主導 | **X1** lemma expressiveness（另 roadmap） |

## 預算估計（僅供排程）

| 項目 | API 量級 |
|------|----------|
| Q3.0 p040 5 輪 | ~50–60 |
| Q3.5 11 案 × 5 輪 | ~150–250 |
| B0–B4 矩陣 p040 only | ~250–400 |
| 達標後 Phase A′ | ~1900 |

## 時程建議

1. **Q3.0** — 5 輪 p040 + 11 案子集 baseline（確認 Q2 穩定區間）
2. **Q3.1–Q3.4** — 一批實作 + p040 5 輪 A/B
3. **Q3.5–Q3.6** — 子集 + tier 報表
4. Gate → Track B 或 Phase A′
