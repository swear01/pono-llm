# p040 Smoke：Session 隔離 + Latency 優化計畫

**狀態：** 待確認實作（2026-06-04）

---

## 使用者決策（已納入）

- **完全 session 隔離**：每次 run 獨立目錄，禁止共用 `/tmp/p040_*`。
- **不設定 `max_tokens` 上限**：維持現有 client 行為，不為 latency 截斷 completion。
- **~22KB 釐清**：見下文「送進 LLM 的到底是什麼」。

---

## 送進 LLM 的到底是什麼？

Compact prompt 改的是 **sidecar 呼叫 API 時的 HTTP body**，不是 JSONL 檔案大小。

每次 API call 在 [`llm_worker/deepseek_client.py`](../llm_worker/deepseek_client.py) 送：

```text
messages[0] system  ← ic3_frame_v1.txt（~2.4 KB）
messages[1] user    ← build_user_prompt() 產出（compact line text）
```

| 數字 | 是什麼 | 是否送進 LLM |
|------|--------|--------------|
| **~22 KB** | **user message**（477 clauses、`snapshot-max-clauses=0`） | **是** |
| **~2.4 KB** | system message（Layer 0 規則 + 範例） | **是** |
| **~24 KB 合計** | 單次 call 的 **input 字元數**（粗估 ~6k tokens input） | **是** |
| **~101 KB** | JSONL 單行（C++ 全量 `frame_snapshot` JSON） | **否**（sidecar 讀檔後轉 compact 再送 API） |
| **~54k total_tokens**（sidecar log） | API 回傳的 `usage.total_tokens`（**input + output 合計**） | 計費/延遲指標，≠ 22 KB |

**結論：** ~22 KB 是 **送進 LLM 的 user 段**；加上 system 約 **~24 KB input 字元**。101 KB 是磁碟 JSONL，不直接等於 API payload。

---

## Latency 根因診斷（2026-06-04 實測）

對同一 mature request（477 clauses）直接呼叫 `deepseek-v4-pro`，量測 `usage.prompt_tokens` / `completion_tokens`：

| 場景 | user bytes | prompt_tok | completion_tok | total_tok | latency |
|------|------------|------------|----------------|-----------|---------|
| full477（全量 snapshot） | 21999 | **10843** | 8355 | 19198 | **177s** |
| last50 | 5469 | 3327 | 10117 | 13444 | **218s** |
| cti_only | 3590 | 2512 | 4255 | 6767 | **94s** |

另一次 full477 分解：

| 欄位 | 值 |
|------|-----|
| 可見 JSON output | **568 chars** |
| 隱藏 `reasoning_content` | **16243 chars** |
| prompt_tokens | 10843 |
| completion_tokens | 4513 |
| latency | **101s** |

### 結論（~100s 是什麼問題）

1. **不是 input 沒壓好**：compact 後 prompt 約 **10.8k tokens**（不是 54k）；22 KB user 確實有送進 API。
2. **主因是 `deepseek-v4-pro` 的 hidden reasoning**：模型在回 ~500 字 JSON 前，先產生 **~16k 字 reasoning chain**（計入 completion_tokens）。
3. **縮小 snapshot 不能穩定加速**：last50 input 更小但 **218s > 177s**（reasoning 更長）。
4. sidecar 先前 log 的 **~54k tokens/request** 可能是 **K 個 sample token 加總** 或舊 prompt；單次 call 實測 total 約 **7k–19k**。

### 要接近 10s（在不設 max_tokens 上限前提下）

| 方向 | 說明 |
|------|------|
| **換非 reasoning 模型** | 例如 `deepseek-chat`（需 smoke 驗證 JSON 品質）— 可能最有效 |
| CTI-only prompt | 實測 **94s**，仍遠離 10s（reasoning 仍在） |
| 縮 input | 有幫助但不決定性的；瓶頸在 reasoning 長度 |

### 計畫調整

- sidecar log **必須**記錄 `prompt_tokens`、`completion_tokens`、`reasoning_chars`（若 API 回傳），方便每次 run 診斷。
- smoke 腳本加 **`--model` 參數**，預設仍 `deepseek-v4-pro`；文件說明 latency 與模型選型關係。
- **10s 目標**改為：先以 **非 reasoning 模型** 或 **CTI-only + chat 模型** 做 A/B；不指望 v4-pro + 全量 snapshot 達 10s。

---

## 問題 1：Session 完全隔離

### 現況問題

固定路徑 `/tmp/p040_*.jsonl` 導致多個 pono/sidecar 可同時 append，前次 run 污染後次（已觀測 450 舊行 + 150 新行）。

### 方案

新增 [`scripts/smoke_p040.sh`](../../scripts/smoke_p040.sh)（或 `llm_worker/smoke_e2e.py`）：

```text
RUN_DIR=$(mktemp -d /tmp/pono_smoke_XXXXXX)
  requests.jsonl      ← --llm-req-path
  responses.jsonl     ← --llm-resp-path
  llm_log.jsonl       ← --llm-log
  benchmark_context.json  ← C++ 自動寫在 req 同目錄
  sidecar.log / pono_stdout.log / pono_stderr.log
  manifest.json       ← run_id, pids, cmd, start_ts, paths
```

- 啟動前檢查 `DEEPSEEK_API_KEY`、`build/pono`、benchmark 路徑。
- 結束時依 `manifest.json` 的 pid **只 kill 本 run 程序**。
- 可選 `--keep` 保留 RUN_DIR 供分析；預設保留並印出路徑。

[`scripts/run_benchmarks.py`](../../scripts/run_benchmarks.py) 的 `_run_one_llm` 已用 uuid tmpdir，smoke 腳本與其對齊。

---

## 問題 2：Latency ~10s（不用 max_tokens 截斷）

### 已完成的壓縮

- API user prompt：305 KB indent → **~22 KB** line compact（477 clauses 全量）。
- CTI：~47 KB → **~3.2 KB**。
- JSONL：163 KB → **~101 KB**（非 API 路徑）。

### 進一步壓 input（允許的手段）

| 手段 | 預估 user bytes | 位置 |
|------|-----------------|------|
| `--snapshot-max-clauses 50` | ~5.5 KB | sidecar CLI（已有） |
| `--snapshot-max-clauses 30` | ~3.5 KB | sidecar CLI |
| attempt=1 不送 snapshot（只 CTI） | ~3.6 KB | sidecar `build_user_prompt` 新 flag |
| 縮短 system prompt（範例移出） | system −~1 KB | `ic3_frame_v1.txt` |
| C++ JSONL 只序列化 last N clauses | JSONL 101→~10 KB | `serialize_frame_snapshot_json` + option |

### 明確不做

- **不**為 latency 設定 `max_tokens` 上限（維持現狀 32768 或現有 client 預設）。

### 量測（乾淨 run 必做）

在 sidecar log 新增（不影響 max_tokens）：

- `prompt_tokens` / `completion_tokens`（若 API 回傳 `usage` 細項）
- `user_prompt_bytes` / `system_prompt_bytes`

用於驗證 54k total 是否主要來自 output，以及 snapshot 截斷對 latency 的實際效果。

### 10s 目標說明

僅靠 input 壓到 ~5 KB 仍可能 >10s（模型固定延遲、output 長度）。目標是 **可量測的 latency 下降**；10s 作為 smoke 驗收目標，需乾淨 run 後依 token 分解再調 `--snapshot-max-clauses`。

---

## 問題 3：其餘（accept=0、吞吐）

| 項目 | 方案 |
|------|------|
| rejected=0 假象 | C++ 統計 `lookup_miss` / `attempt_mismatch`；exit 前 final `process_llm_candidates()` |
| sidecar 積壓 | pono request 限流或 in-flight cap（中期） |
| LLM 重述 CTI | prompt 加「block 在 CTI 下須 false」反例 |
| 混用舊 JSON | session 隔離 + 確認 `build/pono` 為新 binary |

---

## 實作順序

1. **`scripts/smoke_p040.sh`** — session 隔離 + manifest（優先）
2. **sidecar log 擴充** — prompt/completion tokens、user/system bytes（不改 max_tokens）
3. **乾淨 smoke** — 預設 `--snapshot-max-clauses 50`，量測 latency
4. **可選** — C++ JSONL snapshot truncate、attempt=1 CTI-only、prompt 強化、stale 統計

---

## 驗收

- 單次 run 的 JSONL 僅一種 request 格式，無舊 run 污染。
- sidecar log 可讀取每 call 的 user bytes 與 prompt/completion tokens。
- 477-clause 場景：user prompt ≤22 KB（全量）或 ≤6 KB（last 50）；latency 較現狀 ~120s 可量化下降。
