# Q3.1 + Q3.2 詳細實作計劃

**前置：** Q2 診斷（`diagnosis/Q2_current_method_summary.md`）  
**範圍：** 僅 Python prompt / sidecar（**無 C++ 變更**）  
**量測：** p040 5 輪獨立 smoke，加總 accept/API  
**狀態：** ✅ Q3.1+Q3.2 已實作（`llm_worker/prompt_format.py`、`sidecar.py`、測試 `test_prompt_format_q3.py`）；待 5 輪 A/B

---

## 1. 問題陳述（為什麼要做這兩項）

### Q2 診斷結論（6 輪 p040 smoke）

| 現象 | 數據 | 根因假說 |
|------|------|----------|
| `rejected_initial` 全為 B2 | 100% (45/45) | 模型把 **CTI 字面**當成可接受的 block |
| CTI 字面抄襲 | 98.4% disjuncts | 未理解「block = 否定不可達核心」 |
| MIC digest-negate 命中 | 0% | 未產出機械式 `!top_lit` block |
| Top pattern | `init0_clause_eq_0_pol_False` | init=`#b0` 卻輸出 `!state19=0`（與 witness 同 ref） |

**典型失敗例（真實 smoke）：**

```
witness: state19 -> #b0        # init 時 state19=0
failed_clause[0]: !state19=0   # polarity=false, rhs=0 → 在 init 上為 TRUE → rejected_initial
digest top-1:     state215=#b1 (count=67)  # 模型應否定這個，而非抄 state19
```

Q2.1 文字規則 **沒有約束住行為**；Q2.3 feedback 有 `failed_clause` 但 repair 行太泛。

### 兩項干預的分工

| ID | 針對 | 時機 |
|----|------|------|
| **Q3.1** | B2：witness 驅動的 **禁止 / 建議** 模板 | `attempt≥2` 或有 feedback |
| **Q3.2** | 0% MIC：digest top-1 **機械否定** 建議 | **每次** request（含 attempt 1） |

---

## 2. Q3.1 — Witness 驅動修復模板

### 2.1 目標

把 `_repair_line()` 從一句話變成 **可執行的約束**：

1. 標出 **FORBIDDEN** disjunct（與 witness + failed_clause 同型）
2. 標出 **INIT_CHECK**（clause 在 `witness_ref=witness_val` 必須為 FALSE）
3. 若有 digest，給 **SUGGESTED_ALT**（不同 ref 或 digest 否定）

### 2.2 資料來源（已有，無 schema 變更）

```python
fb = {
  "reason": "rejected_initial",
  "witness": {"ref": "state19", "next_value": "#b0"},
  "rejected_json": '{"clause_idx":0,"block_clauses":[[{"ref":"state19","op":"eq","rhs":"0","polarity":false}]]}'
}
```

解析鏈：`rejected_json` → `clause_idx` + `block_clauses`（Q2.3 已上線）。

### 2.3 Init witness 分類（複用 `parse_witness_value_tag`）

| Tag | 條件 | 佔 Q2 smoke RI |
|-----|------|----------------|
| `init0` | `#b0` / `0` / `false` | 多數 |
| `init1` | `#b1` / `1` / `true` | 次多 |
| `init_wide` | 寬常數 | 少數 |

### 2.4 FORBIDDEN 規則表（單 disjunct、witness ref 在 clause 內）

當 `reason=rejected_initial` 且 failed clause 含 `witness.ref`：

| init tag | 禁止的 disjunct 形狀（同 witness ref） | 說明 |
|----------|----------------------------------------|------|
| **init0** | `{ref, rhs:"1", polarity:true}` | `stateX=1` 在 init0 上為 false，但常見誤抄 CTI |
| **init0** | `{ref, rhs:"0", polarity:false}` | `!stateX=0` → 在 init0 上為 **TRUE**（top pattern） |
| **init1** | `{ref, rhs:"0", polarity:true}` | `stateX=0` 在 init1 上為 false |
| **init1** | `{ref, rhs:"1", polarity:false}` | `!stateX=1` → 在 init1 上為 TRUE |
| **init_wide** | 與 witness_val 完全同型之 `{ref, rhs, polarity}` | 保守：任何「在 witness 上為 true」的同款 |

**實作：** `forbidden_disjuncts_for_witness(wref, wval) -> list[dict]` 回傳禁止 JSON disjunct 列表。

**匹配：** `disjunct_matches_template(dj, template)` 比對 ref/rhs/polarity（rhs 經 `normalize_rhs`）。

### 2.5 輸出格式（併入 `format_feedback_block`）

每條 `rejected_initial` feedback 追加：

```
  [0] rejected_initial
      witness: state19 -> #b0
      failed_clause[0]: !state19=0
      INIT_CHECK: clause must be FALSE when state19=0 at reset
      FORBIDDEN (do not repeat): !state19=0 | state19=1
      SUGGESTED: use a different ref from digest stats, or digest top-1 negation (see below)
```

**`SUGGESTED` 邏輯：**

- 若 `witness.ref` 出現在 digest top-5：**不要**再用同一 ref 的 CTI 形字面
- 改推 `digest_negate_top1`（Q3.2 函式）若 top-1 ref ≠ witness.ref
- 若 top-1 ref == witness.ref：推 top-2 否定

### 2.6 System prompt 補強（`ic3_frame_v1.txt`）

在 Anti-patterns 後加 **Witness repair table**（靜態，與 user 模板呼應）：

```
3. init0 witness (stateX=0 at reset):
   FORBIDDEN on stateX: stateX=1, !stateX=0
4. init1 witness (stateX=1 at reset):
   FORBIDDEN on stateX: stateX=0, !stateX=1
```

### 2.7 新增函式（`prompt_format.py`）

| 函式 | 職責 |
|------|------|
| `parse_witness_tag(val) -> str` | 包裝 init0/init1/init_wide |
| `forbidden_disjuncts_for_witness(ref, val) -> list[dict]` | 規則表 |
| `disjunct_equals(dj, other) -> bool` | 比對 |
| `format_witness_repair_entry(fb, req?) -> list[str]` | 單條 feedback 的多行修復 |
| 修改 `_repair_line` / `format_feedback_block` | 呼叫上述 |

### 2.8 Sidecar 注入

維持現有順序；Q3.1 完全在 `format_feedback_block` 內，**無 sidecar 改動**（除非要把 `format_init_aware_block` 縮短避免重複）。

### 2.9 測試（`test_prompt_format_track.py`）

| Case | 斷言 |
|------|------|
| init0 + `!state19=0` failed | 含 `FORBIDDEN` 與 `!state19=0` |
| init0 + `state19=1` failed | 含 `state19=1` forbidden |
| init1 對稱 | 含 `!stateX=1` forbidden |
| 無 witness | 不 crash，fallback 舊 repair |
| `rejected_json` 無 clause_idx | fallback 最後 clause |

### 2.10 成功標準（p040 5 輪）

| 指標 | B0 (Q2) | B1 (+Q3.1) 目標 |
|------|---------|-----------------|
| accept/API | ~13–17% | **+5 pp** |
| B2 占 RI | 100% | **< 70%** |
| `init0_clause_eq_0_pol_False` 次數 | top-1 | **下降 ≥50%** |
| Top witness refs 重複失敗 | state19, state21… | 同 ref retry 失敗減少 |

---

## 3. Q3.2 — Digest top-1 機械否定

### 3.1 目標

每次 request 在 digest 區塊後給出 **可直接貼進 JSON 的建議 disjunct**，使模型不必從 CTI cube「猜」block。

機械規則（與 `analyze_accept_diagnosis.negate_top1_mic_clause` 一致）：

```
digest lit:  state215=#b1   →  block disjunct: {ref:state215, rhs:1, polarity:false}  → !state215=1
digest lit:  !state5=#b0    →  block disjunct: {ref:state5,  rhs:0, polarity:true}   → state5=0
```

Block clause 須在 **所有 CTI** 上為 false → 對 digest 高頻字面取 **布林否定** 即 MIC 直覺。

### 3.2 為何 attempt 1 也要注入

診斷顯示 **98% 第一次就抄 CTI**；僅 retry 才給建議太晚。Q3.2 在 **attempt 1** 就給「預設答案方向」。

### 3.3 字面選擇演算法

```python
def pick_digest_literals(req, max_n=3) -> list[str]:
    """Prefer simple stateNN/inputN=literals from cti_digest.literal_stats."""
    stats = (req.get("cti_digest") or {}).get("literal_stats") or []
    simple = [row["lit"] for row in stats if SIMPLE_LIT_RE.match(row["lit"])]
    return simple[:max_n] or [row["lit"] for row in stats[:max_n]]

def digest_lit_to_block_disjunct(lit: str) -> dict | None:
    """Parse 'lit' line → single IC3FrameDisjunct (negated for block)."""
    # Reuse LIT_RE: !?((?:state|input)\d+)=(.+)
    # polarity_negated = not digest_positive_polarity
```

**跳過：** 含 `bvor`/`bvcomp` 的複合 digest 字串（p040 常見）→ 取下一個 simple literal。

**無 digest 時（小 batch 全列 cube）：**

- 從第一個 `cti_entries[0]` cube 取 **最高頻** 或第一個 literal
- 或從多 cube 統計手動頻率（輕量實作：只用 entry[0]）

### 3.4 輸出格式（新區塊）

在 `format_cti_batch_digest` **之後**插入：

```
Digest-derived block hints (use as primary strategy):
  top-1 CTI literal: state215=1 (count=67)
  suggested disjunct (negation): !state215=1
  JSON: [{"ref":"state215","op":"eq","rhs":"1","polarity":false}]
  top-2 CTI literal: state24=1 (count=67)
  suggested disjunct: !state24=1
Rules:
  - Your block must be FALSE on every CTI cube: do NOT restate digest/CTI positive literals.
  - Prefer clause 0 = single suggested disjunct above.
  - FORBIDDEN: any disjunct identical to a listed CTI/digest positive literal.
```

**`FORBIDDEN` 列表：** digest top-5 正向字面（compact 一行），防抄襲。

### 3.5 與 `sample_generalization_hint` 對齊

| sample_id | 現行 | Q3.2 調整 |
|-----------|------|-----------|
| 0 | minimal 1–2 disjunct | **clause 0 = digest negate top-1 only** |
| 1 | digest high-freq | top-1 negate + 可選 top-2 OR（仍 ≤2 disjunct） |
| 2 | OR 3–4 literals | 改為 top-1..3 **各自否定** 的 3 disjunct（仍 OR） |

避免 sample 2 繼續鼓勵「抄 CTI OR」。

### 3.6 System prompt（`ic3_frame_v1.txt`）

新增 **Digest negation rule**：

```
- When cti_digest is present: your PRIMARY block strategy is to negate a high-frequency
  digest literal (see user message "Digest-derived block hints").
- Never emit a disjunct that matches a digest/CTI positive literal; that restates the
  bad path instead of blocking it.
```

加一個 **GOOD** 範例：

```
digest: state215=#b1 (count=67)
GOOD block_clauses[[{"ref":"state215","op":"eq","rhs":"1","polarity":false}]]
```

### 3.7 新增函式（`prompt_format.py`）

| 函式 | 職責 |
|------|------|
| `SIMPLE_LIT_RE` | `^!?((?:state\|input)\d+)=(.+)$` |
| `parse_digest_lit_line(lit) -> (ref, rhs, pol)` | 解析 digest 行 |
| `negate_digest_lit_to_disjunct(lit) -> dict \| None` | 機械否定 |
| `format_digest_block_hints(req) -> str` | 主輸出 |
| `collect_forbidden_positive_literals(req, n=5) -> list[str]` | 禁止抄襲列表 |

### 3.8 Sidecar 注入（`build_batch_user_prompt`）

```python
parts = [
    ...
    format_cti_batch_digest(...) or format_cti_batch_all(...),
    "",
    format_digest_block_hints(req),   # NEW — always when literals available
    "",
    format_frame_snapshot(...),
]
```

**attempt 1：** 有 hints + 縮短 `format_init_aware_block`（attempt 1 可省略 init block，減 token）。

**attempt≥2：** hints + feedback(Q3.1) + init block。

### 3.9 測試

| Case | 斷言 |
|------|------|
| digest `state215=#b1` | hints 含 `!state215=1` 與 JSON polarity false |
| digest `!state5=0` | hints 含 `state5=0` polarity true |
| 複合 bvor 字串 | 跳過，用下一條 simple |
| 無 digest，有 cti_entries | 從首 cube 產生 hint |
| forbidden 列表 | 含 top-3 正向字面 |

**回歸：** `diagnose_q2_smoke` 的 `mic_top1_shape_pct` 從 0% → **≥30%**（5 輪均值）。

### 3.10 成功標準（p040 5 輪）

| 指標 | B0 | B2 (+Q3.2) 目標 |
|------|-----|-----------------|
| accept/API | ~13–17% | **+8 pp** |
| `cti_literal_copy` disjunct % | 98% | **< 40%** |
| `mic_top1_shape_pct` | 0% | **≥ 30%** |
| B2 占 RI | 100% | **< 80%**（單獨 Q3.2 對 B2 幫助有限） |

---

## 4. 合併實作（Q3.1 + Q3.2）

### 4.1 建議一次 PR

兩者皆 prompt-only、同一檔案為主；合併可減少 5 輪 A/B 次數。

**注入順序（user prompt）：**

```
proof_context
sample_hint (Q3.2 調整後)
CTI digest / all cubes
Digest-derived block hints     ← Q3.2
frame_snapshot
symbol_hints
feedback + witness repair      ← Q3.1
init_aware_block (attempt≥2)
benchmark_context
response instructions
```

### 4.2 實驗矩陣（5 輪 p040）

| 組別 | 內容 |
|------|------|
| B0 | Q2 預設（tag `post-q2-clause-quality`） |
| B1 | B0 + Q3.1 |
| B2 | B0 + Q3.2 |
| **B3** | B0 + Q3.1 + Q3.2（目標合入 main） |

```bash
MAX_ATTEMPTS=3 STRICT=0 bash scripts/ab_q2_p040_multiround.sh  # B0 對 HEAD
# B1–B3：feature flag 或 branch，跑完 diagnose_q2_smoke.py 比 B2%/MIC%/CTI copy%
```

**合入門檻（B3 vs B0）：**

- accept/API **≥ +10 pp**
- `mic_top1_shape_pct` **≥ 25%**
- `cti_literal_copy` **≤ 50%**
- B2 占 RI **≤ 60%**

### 4.3 檔案清單

| 檔案 | Q3.1 | Q3.2 |
|------|------|------|
| `llm_worker/prompt_format.py` | ✓ | ✓ |
| `llm_worker/prompts/ic3_frame_v1.txt` | ✓ | ✓ |
| `llm_worker/sidecar.py` | — | ✓ |
| `llm_worker/tests/test_prompt_format_track.py` | ✓ | ✓ |
| `scripts/diagnose_q2_smoke.py` | — | 可選：加 `mic_match` 對照 |
| `docs/plans/clause_quality_q3_plan.md` | 連結本文件 | 連結本文件 |

**不修改：** C++、`options/`、`max_block_clauses` 預設。

### 4.4 風險與緩解

| 風險 | 緩解 |
|------|------|
| digest top-1 否定在 init 上為 true | Q3.1 INIT_CHECK + 換 top-2/top-3 |
| 複合 digest 無法解析 | 跳過；fallback 次頻 simple literal |
| prompt 變長 | hints 限 top-3；forbidden 限 top-5 一行 |
| 否定字面 induction 失敗 | 不阻擋；Q3.1 已處理 induction repair；量測 `induction_fail` |
| 寬常數 init | init_wide 用保守 FORBIDDEN（同款 disjunct） |

### 4.5 實作順序（建議 1–2 天）

1. **Q3.2 核心函式** + unit tests（negate、hints、forbidden）
2. **Q3.1 規則表** + `format_witness_repair_entry` + tests
3. **sidecar 注入** + `ic3_frame_v1.txt` 更新
4. **單次 p040 smoke** 肉眼檢查 user prompt（attempt 1/2）
5. **5 輪 B0 vs B3** + `diagnose_q2_smoke.py`
6. 更新 `clause_quality_q3_plan.md` gate

---

## 5. 範例：同一 batch 的完整 user prompt 片段（目標狀態）

```
CTI digest (cti_total=67, sample_cubes=3/3):
High-frequency literals across all CTI cubes:
  state215=#b1  (count=67)
  state24=#b1   (count=67)
  ...

Digest-derived block hints (primary strategy):
  top-1: state215=1 → suggested block: !state215=1
  JSON disjunct: {"ref":"state215","op":"eq","rhs":"1","polarity":false}
  FORBIDDEN (do not copy): state215=1 | state24=1 | state211=1 | ...

=== Correctness failures (init / reachable) ===
  [0] rejected_initial
      witness: state19 -> #b0
      failed_clause[0]: !state19=0
      INIT_CHECK: clause must be FALSE when state19=0 at reset
      FORBIDDEN (do not repeat): !state19=0 | state19=1
      SUGGESTED: use digest top-1 negation (!state215=1) — different ref than witness
```

---

## 6. 與 Q3 路線圖的關係

- **Q3.1 + Q3.2** 完成後若達 gate → Q3.5  eleven-case 子集 5 輪
- 若 B2 仍 >50% → Q3.4 negative_literal_stats（frame snapshot）
- 若 MIC 高但 accept 仍低 → 查 induction / vocab
- 若仍卡 ~20% → Track B `drop_literals`（C++ 路徑）

本文件為 **Q3.1/Q3.2 的實作規格**；執行入口見 [`clause_quality_q3_plan.md`](clause_quality_q3_plan.md)。
