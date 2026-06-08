> **HISTORICAL — legacy `cube_subset` bugs (2026-06-03).** Code path **will be deleted** with IC3 Frame v1.  
> See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md). Below documents pre-v1 failures.

# LLM-Guided Lemma Generalization: Bug Analysis

## Harness — baseline stdout 誤判（2026-06-07，已修）

**位置：** `scripts/run_benchmarks.py` `run_pono()`（舊版整段 stdout 比對）

**問題：** BTOR2 的 pono 印兩行（`sat`/`unsat` + `b0`）。harness 用 `stdout.strip()` 比對 `"sat"`/`"unsat"` 失敗 → `sat` 記成 `unknown`（exit 0）、`unsat` 記成 `error`（exit 1）。baseline log 看似「全 error、零解出」。

**修正：** `_parse_pono_stdout()` 讀 stdout **第一行**；中斷恢復見 [`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) § 中斷恢復（`baseline-patch` + `--skip-partial`）。

**與下方 Bug #3 的關係：** Bug #3 描述「幾乎全是 error/timeout 故 LLM stats 未觸發」— baseline 誤判會放大該現象；根因不同，但症狀重疊。

**修正後仍會有的真 `error`：** 少數 benchmark 在 IC3IA + Bitwuzla 上引擎無法繼續（interpolation 不支援、IC3 `reaches_bad` SMT unknown）。pono stdout 第一行為 `error`、exit 2 — 見 [`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) § `result` 語意。

---

## Summary

Benchmark 結果 LLM Accepted=0，LLM 貢獻完全為零。以下為系統性分析出的所有問題。

---

## Bug #1 (CRITICAL): `cube_subset_to_blocking` 字串格式不匹配

**位置**: `engines/ic3base.cpp:1194`

**問題**: LLM 回傳的 `keep_literals` 格式為 `"signal_name = true"`，但 `ts_.get_name(child)` 只回傳 `"signal_name"`（純變數名），導致 `keep_set.find(name)` 永遠找不到匹配項。

**證據鏈**:
1. `collect_cti_literals` (`ic3base.cpp:1166`) 設定 `lit.value = "true"`，寫入 JSONL request 時分兩個欄位: `{"varname": "signal", "value": "true"}`
2. Sidecar prompt 將它們格式化成 `signal = true` 給 LLM 看
3. LLM 回傳 `keep_literals: ["signal = true", ...]`
4. `cube_subset_to_blocking` (`ic3base.cpp:1194`) 用 `ts_.get_name(child)` 取得純名 `"signal"`，去比對 `"signal = true"` → **永不匹配**
5. 所有 candidate 都產出空 blocking clause (`ic3base.cpp:1309-1311`)，被 silent skip
6. 沒有任何 failure counter (`num_schema_fail`, `num_induction_fail` 等) 被遞增，因為 candidate 通過 validation 後才在此處失敗

**這解釋了為什麼 LLM Accepted 全為 0。**

---

## Bug #2 (MAJOR): Negated literals 的 value 全部被設為 "true"

**位置**: `engines/ic3base.cpp:1166`

```cpp
lit.varname = ts_.get_name(child);
lit.value = "true";  // 永遠是 "true"
```

**問題**: IC3 的 CTI cube 可以包含正負 literals（例如 `x` 和 `!y`）。對於 `!y` 這種 negative literal，它的 value 應該是 `"false"`。但程式把所有 literal 都標成 `"true"`，這會讓 LLM 接收到錯誤的信號狀態資訊。

此外，`ts_.get_name(child)` 作用在 `(not y)` 這種複合 term 上，行為可能不正確（smt-switch 的 `get_name` 通常只適用於符號節點）。

---

## Bug #3 (MAJOR): `_parse_llm_stats` 只在非 timeout/error 時執行

**位置**: `scripts/run_benchmarks.py:803`

```python
if mode == "llm" and result != "error" and result != "timeout":
    llm_acc, llm_rej, llm_err = _parse_llm_stats(r.stderr)
```

**問題**: 幾乎所有 benchmark 結果都是 `error` 或 `timeout`，因此 LLM stats 解析幾乎從未被觸發。

---

## Bug #4 (MAJOR): `_parse_llm_stats` 永遠找不到 "rejected" 或 "accepted" 的數字

**位置**: `scripts/run_benchmarks.py:688-708`

```python
if "accepted" in line.lower():
    accepted = int(re.search(r"(\d+)", line).group(1))
```

**問題**: C++ 端從不輸出 "rejected" 這個詞。stats log 行如:
```
LLM candidate ACCEPTED: inserted blocking clause at frame 3 (size=2)
```
這行的第一個數字是 `3`（frame index），不是 accepted count。所以即使 `_parse_llm_stats` 被呼叫，它也會取到錯誤的數字。

正確的設計應該是在 `log_stats()` (`llm_generalizer.cpp:247-260`) 輸出結構化的統計行，方便 parsing。

---

## Bug #5 (MAJOR): Sidecar stdout/stderr 被導向 DEVNULL

**位置**: `scripts/run_benchmarks.py:920-921`

```python
stdout=subprocess.DEVNULL,
stderr=subprocess.DEVNULL,
```

**問題**: Sidecar 的所有輸出（包含 API error、connection failed 等關鍵診斷資訊）全部被丟棄，無法在 benchmark 執行期間偵測任何 sidecar 問題。

---

## Bug #6 (MODERATE): `process_llm_candidates()` 被呼叫的頻率太低

**位置**: `engines/ic3base.cpp:177, 453`

**問題**: `process_llm_candidates()` 只在以下兩處被呼叫:
1. `check_until` 迴圈開始前 (`ic3base.cpp:177`)
2. `step()` 的 `block_all()` 之後 (`ic3base.cpp:453`)

但在 `block_all()` 內部（可能非常耗時），CTI contexts 被大量捕獲 (`reaches_bad` → `capture_cti_context`)，卻沒有任何 polling。LLM 可能已經回傳 candidate，但 pono 要到下一個 `process_llm_candidates()` 才能處理。

建議在 `block_all()` 內部適當位置（例如每處理 N 個 proof goal 後）也呼叫一次 polling。

---

## Bug #7 (MODERATE): `poll_candidates()` 的 JSON parsing 脆弱

**位置**: `engines/llm_generalizer.cpp:105-244`

**問題**: Candidate 的 JSON 是手動 parse 而非使用 JSON library，有以下缺陷:
1. 如果 LLM 回傳的 JSON 中包含 escaped 字元（如 `\"`），parse 可能失敗
2. `stoul` 在 frame_hint parse 失敗時會拋出 exception
3. 沒有對 truncated/malformed lines 的容錯

---

## Bug #8 (MINOR): Sidecar 和 pono 之間的 race condition

**位置**: Scripts 與 sidecar 啟動流程

**問題**: 
- Sidecar 在 pono 啟動前 1 秒啟動 (`time.sleep(1)`)
- 但如果 API key 未設定，sidecar 會立即 exit（但 stdout 被 suppress 所以無法偵測）
- Pono 開始寫 request 時，sidecar 可能尚未連上 API 或已 crash
- 沒有 heartbeat/health check 機制

---

## Bug #9 (MODERATE): IC3IA baseline 也無法解任何題目

**數據**: 1052 benchmarks, Solved=0

這可能是：
1. **Bound 太小** (100000) 或 timeout 太短 (300s)
2. IC3IA 在這個 benchmark set 上確實不適合（HWMCC 2024/2025 的 RISC-V formal/Rocket 等題目非常難）
3. Solver 選擇不當（BZLA vs Bitwuzla？）

---

## Bug #10 (MINOR): Sidecar log 中的 escape JSON 會 double-escape

**位置**: `engines/llm_generalizer.cpp:55` 和 `sidecar.py:46-50`

**問題**: C++ `escape_json` 會將 `"` 轉成 `\"`。然後 sidecar 又將 prompt text 用 `template.format()` 插入，如果 prompt template 裡有 JSON 範例中的 `"`, 會被解析成 template 的 placeholder 造成錯誤。

實際上因為 prompt template 使用 `{property_name}`, `{frame_idx}`, `{literals}` 作為 placeholder，而 LLM response 中的 JSON 範例用 `{{` `}}` 來 escape，所以 template.format() 不會誤觸。但這仍然是脆弱的地方。

---

## Fix Priority

| Priority | Bug | Fix |
|----------|-----|-----|
| **P0** | #1: keep_literals 格式不匹配 | 修改 `cube_subset_to_blocking`，把 `keep_set` 比對邏輯改成用純變數名比對 |
| **P0** | #2: Negated literals value 錯誤 | `collect_cti_literals` 中根據 literal polarity 設定 value |
| **P1** | #4: Stats parsing 永遠取不到正確值 | 重寫 stats log 格式，在 C++ 輸出結構化 JSON stats line |
| **P1** | #5: Sidecar 輸出被 suppress | 把 sidecar stderr 寫到檔案而非 DEVNULL |
| **P2** | #3: Stats 只在非 timeout/error 時解析 | 改為總是解析 stats |
| **P2** | #6: Polling 頻率不足 | 在 `block_all` 內部增加 polling 點 |
| **P2** | #7: JSON parsing 脆弱 | 考慮用 nlohmann/json 或其他 library |
| **P3** | #8: Race condition | 增加 sidecar health check / heartbeat |
| **P3** | #9: Baseline 0 solved | 嘗試調整 bound, timeout, solver 參數 |
