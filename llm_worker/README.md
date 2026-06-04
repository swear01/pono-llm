# LLM Worker (IC3 Frame v1)

Online LLM sidecar for Pono IC3IA proof loop. **No offline research scripts** — v1 runtime only.

## Runtime entry point

**唯一 proof-loop 入口：** [`sidecar.py`](sidecar.py)

```bash
python3 llm_worker/sidecar.py \
  --req-path /tmp/pono_llm_requests.jsonl \
  --resp-path /tmp/pono_llm_responses.jsonl \
  --log-path /tmp/pono_llm_log.jsonl \
  --prompt-dir llm_worker/prompts/ \
  --max-inflight-requests 4 \
  --snapshot-max-clauses 0
```

Pono 端（主力 engine：**IC3IA**）：

```bash
./build/pono -e ic3ia --llm-gen-mode async-cti \
  --llm-req-path /tmp/pono_llm_requests.jsonl \
  --llm-resp-path /tmp/pono_llm_responses.jsonl \
  design.btor2
```

## Files

| File | Role |
|------|------|
| [`sidecar.py`](sidecar.py) | Poll Frame v1 requests (single-CTI or batch-all-CTI), call LLM (parallel K, default temp=0.5 for batch), write `ic3_frame_response` |
| [`prompt_format.py`](prompt_format.py) | Compact line formats for CTI / frame snapshot in API user prompt |
| [`deepseek_client.py`](deepseek_client.py) | DeepSeek API client (`https://api.deepseek.com/v1`) |
| [`jsonl_protocol.py`](jsonl_protocol.py) | JSONL read/write |
| [`ic3_frame_schema.py`](ic3_frame_schema.py) | Request/response validation |
| [`prompts/ic3_frame_v1.txt`](prompts/ic3_frame_v1.txt) | Layer 0 system prompt |
| [`tests/test_ic3_frame_schema.py`](tests/test_ic3_frame_schema.py) | Schema unit tests (no API) |
| [`tests/test_prompt_format.py`](tests/test_prompt_format.py) | Compact prompt formatting tests (no API) |

## Spec

See [`docs/ic3_frame_v1_integration.md`](../docs/ic3_frame_v1_integration.md).

## Environment

**API key（必填）：**

```bash
export DEEPSEEK_API_KEY=sk-...
```

Sidecar 只讀 `DEEPSEEK_API_KEY`（shell 環境變數，不寫入 repo）。

**Python 依賴：**

```bash
pip install -r llm_worker/requirements.txt
```

`requirements.txt` 含 `openai` 套件 — 這是 **HTTP client library**（OpenAI-compatible SDK），用來呼叫 DeepSeek API，**不是**使用 OpenAI 的模型。DeepSeek 提供與 OpenAI Chat Completions 相同格式的 REST API，官方建議用此 SDK 連線。

## Thinking mode (latency)

`reasoning_effort=none` (default from pono and sidecar) maps to DeepSeek API `thinking.type=disabled` in [`deepseek_client.py`](deepseek_client.py). Single-call latency on `deepseek-v4-pro` is typically **4–6 s** with compact prompts; with thinking enabled, calls often exceed **90 s** despite short visible JSON.

Do **not** rely on omitting `reasoning_effort` to disable thinking.

## Smoke (p040, isolated session)

```bash
export DEEPSEEK_API_KEY=sk-...
chmod +x scripts/smoke_p040.sh

# Uses mktemp under /tmp/pono_smoke_* — never shared /tmp/p040_*
SNAPSHOT_MAX=50 PONO_TIMEOUT=600 ./scripts/smoke_p040.sh
```

Each run writes `requests.jsonl`, `responses.jsonl`, `llm_log.jsonl`, and `manifest.json` under a unique `RUN_DIR`. API usage scales with how long pono runs (many CTI requests); cost is acceptable for validation.

Env overrides: `BTOR`, `SNAPSHOT_MAX`, `PONO_TIMEOUT`, `PARALLEL_SAMPLES`.

## Tests

```bash
# 無 API
python3 llm_worker/tests/test_ic3_frame_schema.py
python3 llm_worker/tests/test_prompt_format.py
python3 llm_worker/tests/test_deepseek_thinking.py
python3 llm_worker/tests/test_sidecar_concurrency.py

# 含 API（需 DEEPSEEK_API_KEY）
python3 test_sidecar.py --client-only

# 或一次跑內建 test phase
python3 scripts/run_benchmarks.py --phase test
```
