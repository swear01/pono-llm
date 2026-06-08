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
| [`tests/test_jsonl_protocol.py`](tests/test_jsonl_protocol.py) | JSONL partial-line / corrupt-line reader tests |
| [`tests/test_sidecar_batch.py`](tests/test_sidecar_batch.py) | Mock batch request → K responses |
| [`tests/test_cti_digest.py`](tests/test_cti_digest.py) | Digest schema + prompt size |
| [`tests/test_prompt_format.py`](tests/test_prompt_format.py) | Compact prompt formatting tests (no API) |

## Spec

See [`docs/ic3_frame_v1_integration.md`](../docs/ic3_frame_v1_integration.md).

**Prompt cost note:** `benchmark_context.json` may contain a large `bad_property` string (C++ writes the full bad-state expr). Sidecar currently sends only `benchmark` path in the API user prompt — not `bad_property` — to avoid MB-scale input on ILA designs. CTI/frame digest is the actionable blocking context.

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

## Build note (PonoOptions / ABI)

After changing [`options/options.h`](../options/options.h), rebuild **both** the library and the `pono` executable:

```bash
cd build && make -j4 pono-bin
```

Rebuilding only `libpono.so` without `pono-bin` can cause `malloc` crashes in `LLMGeneralizer` (stale `PonoOptions` layout).

## Model

Default **`deepseek-v4-pro`** ([`deepseek_client.py`](deepseek_client.py), C++ request JSON, `run_benchmarks.py --llm-model`). Override with `--llm-model` (pono) or `--model` (sidecar). Endpoint: `https://api.deepseek.com/v1` only.

## Smoke (p040, isolated session)

```bash
export DEEPSEEK_API_KEY=sk-...
chmod +x scripts/smoke_p040.sh
cd build && touch ../pono.cpp && make -j4 pono-bin && cd ..

# Uses mktemp under /tmp/pono_smoke_* — never shared /tmp/p040_*
SNAPSHOT_MAX=0 BATCH_WAIT_SEC=300 PONO_TIMEOUT=600 ./scripts/smoke_p040.sh
```

Each run writes `requests.jsonl`, `responses.jsonl`, `llm_log.jsonl`, and `manifest.json` under a unique `RUN_DIR`.

**Channel checks (`STRICT=1` default):** `responses = requests × PARALLEL_SAMPLES`, `batch_timeouts = 0`, no sidecar JSONL parse errors, max request line under 500KB. **`accepted > 0` is not required** (quality is separate).

Env overrides: `BTOR`, `SNAPSHOT_MAX`, `PONO_TIMEOUT`, `PARALLEL_SAMPLES`, `BATCH_WAIT_SEC`, `STRICT`, `MAX_INFLIGHT`, `DRAIN_SEC`.

## Tests

```bash
# 無 API（建議一次跑完）
python3 -m pytest llm_worker/tests/ -q
cd build && ./tests/test_ic3_frame_ast

# 或個別
python3 llm_worker/tests/test_ic3_frame_schema.py
python3 llm_worker/tests/test_jsonl_protocol.py
python3 llm_worker/tests/test_sidecar_batch.py
python3 llm_worker/tests/test_cti_digest.py

# 含 API（需 DEEPSEEK_API_KEY）
python3 test_sidecar.py --client-only

# 或 C++ + 部分 schema（不含全部 llm_worker pytest）
python3 scripts/run_benchmarks.py --phase test
```

## HWMCC experiments

Staged workflow (smoke → find-solvable → llm subset → full pipeline): [`docs/hwmcc_experiment_tiers.md`](../docs/hwmcc_experiment_tiers.md).

**Parallel policy (batch runs):** default **8 workers** (`--parallel 8`), each with its own sidecar instance. Standard flags: `--memory-limit 14 --snapshot-max-clauses 0 --llm-drain-sec 300`. Details: [`docs/plans/experiment_parallel_policy.md`](../docs/plans/experiment_parallel_policy.md).

```bash
python3 scripts/run_benchmarks.py --phase llm \
  --hwmcc-dir ~/hwmcc_benchmarks --limit 50 \
  --parallel 8 --memory-limit 14 --snapshot-max-clauses 0
```
