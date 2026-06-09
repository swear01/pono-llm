# IC3 Frame v1 — Online LLM Integration Spec

**Status:** Canonical integration spec (2026-06-03)  
**Replaces:** `cube_subset`, `qf_smt`, `LLMCandidateLanguage`, Path 1 `PONO_LLM_ASSERT_LIFTED_LEMMAS`, offline lemma mining as runtime path

Legacy runtime code and prompts listed in [§ Legacy deletion](#legacy-deletion) **will be deleted** (not deprecated).

---

## Goal

LLM runs **online** during IC3/IC3IA proof: watches CTIs and frame context, proposes **frame-native** blocking clauses (and optional IC3IA predicates), validated only by Pono (`rel_ind_check` → `constrain_frame` / `add_predicate`). No free-form SMT parser. No offline assert injection as proof loop.

---

## Architecture

```text
IC3IA main loop
  capture_cti → ic3_frame_request (JSONL)
  sidecar: layered prompt + parallel K API calls (reasoning_effort=none)
  ic3_frame_response (JSONL) × K
  process_frame_responses: first accept wins
  rel_ind_check → constrain_frame / add_predicate
  reject → feedback → retry (max attempts)
```

See also [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Prompt layers (cache-friendly)

| Layer | Content | Same circuit run |
|-------|---------|------------------|
| 0 | system + ic3_frame schema rules | Fixed (global) |
| 1 | benchmark path only (see note below) | Fixed per `.btor2` |
| 2 | `symbol_registry` ( **Verilog required** , btor2_line, width) | Fixed per circuit |
| 3 | `frame_snapshot` (frontier OR clauses) | Changes per frame / as proof adds clauses |
| 4 | `cti` + `feedback` + `sample_id` | Unique per API call |

Layers 0–2 are stable → provider prefix cache. Layer 3–4 change each request; sidecar renders them as **compact line text** in the API user prompt (JSONL on disk stays JSON).

**`bad_property` omitted from API prompts (2026-06, temporary):** C++ still writes the full bad-state BTOR expression to `benchmark_context.json` (`write_benchmark_context` in `llm_generalizer.cpp`). Sidecar **does not** include it in the user prompt sent to the LLM. On ILA-scale designs the serialized `bad_property` can exceed 1MB per request and dominated input tokens without helping blocking (CTI digest + frame digest already describe the bad region). Re-enable only after a bounded summary (e.g. truncated `property_name` or a few root literals), not the full formula tree.

### Sidecar compact serialization (Layer 3–4)

C++ writes compact JSON to JSONL; sidecar converts Layer 3–4 to line text before the API call:

| Source (JSONL) | API user prompt |
|----------------|-----------------|
| `cti.cube.literals[]` with `{atom:{ref,rhs},polarity}` | `!state15=0` one per line |
| `frame_snapshot.clauses[]` with `{disjuncts:[...]}` | `!state538=0 \| state93=1` one per line |
| `feedback[]` | JSON (small, structured) |

**`symbol_registry`** is written once to `benchmark_context.json` (Layer 2), **not** duplicated in each request line.

Sidecar flag `--snapshot-max-clauses N` (default `0` = all clauses): when `N>0`, only the last N clauses are shown in the prompt.

---

## Request: `ic3_frame_request` v1

```json
{
  "schema_version": 1,
  "type": "ic3_frame_request",
  "frame_idx": 12,
  "cti_id": "cti_000123",
  "attempt": 1,
  "max_attempts": 3,
  "parallel_group": "cti_000123_a1",
  "parallel_samples": 1,
  "benchmark_context_path": "/tmp/pono_benchmark_context.json",
  "cti": {
    "cube": {
      "literals": [
        {
          "atom": { "ref": "state1536", "rhs": "10" },
          "polarity": true
        }
      ]
    }
  },
  "frame_snapshot": {
    "frame_idx": 12,
    "clauses": [
      {
        "disjuncts": [
          {
            "atom": { "ref": "state93", "rhs": "1" },
            "polarity": true
          }
        ]
      }
    ]
  },
  "feedback": []
}
```

**Rules:**

- `frame_idx` is authoritative; response has **no** `frame_hint`.
- `symbol_registry` lives in `benchmark_context.json` (Layer 2), not per request.
- Sidecar reads `benchmark_context_path` for benchmark name and symbol registry (`bad_property` on disk only; not sent to the API — see Prompt layers).
- LLM must cite symbols only as `ref` (`stateNN`, `inputN`); Verilog is semantic hint only.
- C++ writes `benchmark_context.json` (layers 1–2) once at startup; sidecar caches it.
- Request JSON uses minimal fields: literals `{atom:{ref,rhs},polarity}`, clauses `{disjuncts:[...]}`.

---

## Request: `ic3_frame_batch_request` v1 (default)

After each `block_all` phase, Pono flushes **one** batch line containing all CTIs buffered for that frame. The LLM returns **1–N** independent `block_clauses` per sample (default N=3; `--llm-max-block-clauses`). C++ accepts the **first** clause that passes init + induction and stops. Response `source_cti_id` is the `batch_id` (e.g. `batch_f2_a1`), not per-CTI ids.

| Field | Notes |
|-------|--------|
| `batch_id` | `batch_f{frame}_a{attempt}` |
| `cti_entries[]` | Full mode: `{cti_id, cti}`. Digest mode: `{cti_id, literals[]}` (compact strings) |
| `cti_digest` | Optional: `{cti_total, literal_stats[], ...}` when batch is large |
| `frame_snapshot` | May include `clauses_total` when C++ caps clauses |
| `temperature` | `0.5` in request; sidecar uses it for API calls |
| `parallel_samples` | K (default 1) |
| `max_block_clauses` | N independent OR-clauses per response (default 3); first valid wins |
| `model` | Default `deepseek-v4-pro` if `--llm-model` unset |

### CTI digest (large batches)

When the serialized batch line exceeds `--llm-batch-max-json-bytes` (default **500000**), C++ enables digest (if `--llm-cti-digest` is on, default):

- **`cti_digest`:** `cti_total` + top `literal_stats` (frequency across all cubes in the round).
- **`cti_entries`:** representative sample cubes only, with `literals[]` instead of full `cti.cube` JSON.
- **`batch_store_`:** still holds **all** CTIs for C++ meta / retry; only the JSONL line is slim.
- Shrink loop: if still over budget, halve `--llm-cti-digest-max-cubes` (down to 1) and retry.

Disable with `--no-llm-cti-digest`. Sidecar renders digest via `format_cti_batch_digest` in the API user prompt; `llm_log.jsonl` `cti_total` uses `cti_digest.cti_total` when present.

### JSONL reliability

- C++ serializes each request to a string buffer, then writes **one line + `\n` + `flush`** (atomic append).
- Sidecar [`jsonl_protocol.read_requests_batch`](../llm_worker/jsonl_protocol.py): if a line has **no trailing `\n`**, treat as in-progress and **do not** advance `last_position`.

### Frame snapshot cap (C++ JSONL)

`--llm-snapshot-max-clauses N` (default **50**): only the **last N** clauses are written into `frame_snapshot` in the request JSON, with `clauses_total` set when truncated. Sidecar `--snapshot-max-clauses` should match for consistent prompt text.

**Execution modes (only two supported):**

| Mode | Flags | Behavior |
|------|-------|----------|
| **Full sync (default)** | (none) | After flush, pono waits for K responses then ingests; stats reliable |
| **Full async** | `--no-llm-sync-after-flush` | Same batch request; no wait; rely on poll + sidecar drain at end |

`--no-llm-batch-cti` (legacy per-CTI, ~N requests per flush) is **debug-only**, not used in smoke/benchmarks.

**Pono LLM flags (batch):**

| Flag | Default | Purpose |
|------|---------|---------|
| `--llm-batch-wait-sec` | 120 | Sync wait timeout after flush (smoke uses 300) |
| `--llm-snapshot-max-clauses` | 50 | Cap clauses in JSONL `frame_snapshot` |
| `--llm-batch-max-json-bytes` | 500000 | Trigger CTI digest when batch JSON exceeds N bytes |
| `--llm-cti-digest-max-cubes` | 16 | Max sample cubes when digest on |
| `--llm-cti-digest-top-lits` | 40 | Max literal stats rows in digest |
| `--no-llm-cti-digest` | off | Send full `cti_entries` always |
| `--llm-model` | (empty → `deepseek-v4-pro`) | Model name in request JSON |

**Feedback:** keyed by `batch_f{frame}` so attempt 2 (`batch_f2_a2`) still sees failures from attempt 1. Sidecar formats witness fields in the user prompt.

**Accept semantics:** one `rel_ind_check` per accepted sample; batch accept does **not** mark individual `cti_id` entries as accepted (they may be buffered again in later rounds).

### Verification: channel vs quality

| Check | Smoke / channel | Research / quality |
|-------|-----------------|---------------------|
| `responses == requests × K` | required (`STRICT=1`) | required |
| `batch_timeouts == 0` | required | required |
| JSONL parse errors | required | required |
| `accepted >= 1` | not required | goal for LLM usefulness |
| `rejected_initial`, `induction_fail` | logged in `manifest.json` | analyze prompt / digest |

See [`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) for staged benchmark workflow.

---

## Response: `ic3_frame_response` v1

```json
{
  "schema_version": 1,
  "type": "ic3_frame_response",
  "source_cti_id": "cti_000123",
  "sample_id": 0,
  "actions": [
    {
      "kind": "block",
      "clause": {
        "form": "or",
        "disjuncts": [
          {
            "form": "literal",
            "atom": { "ref": "state93", "op": "eq", "rhs": "1" },
            "polarity": true
          }
        ]
      },
      "operator": "literal_deletion"
    }
  ],
  "symbols_used": ["state93"],
  "rationale": "..."
}
```

**Limits (v1):**

- Up to **N** independent `block_clauses` per response (default N=3 via `--llm-max-block-clauses`); each clause is one OR of literals (≤8 disjuncts).
- Legacy single `block_disjuncts` still accepted (treated as one clause).
- C++ accepts the **first** clause passing init + induction; remaining clauses in that response are skipped.
- At most **one** optional `refine_predicate` action (IC3IA only).

Optional `refine_predicate`:

```json
{
  "kind": "refine_predicate",
  "predicate": {
    "form": "eq",
    "args": [
      { "form": "bvand", "args": [ { "ref": "state1536" }, { "const": "2", "width": 4 } ] },
      { "const": "0", "width": 4 }
    ]
  }
}
```

---

## Atom AST (closed op whitelist)

**Literals:** `eq`, `ne`, `ult`, `ule`, `ugt`, `uge`, `slt`, `sle`, `sgt`, `sge`  
**Connectives:** `and`, `or`, `not`, `implies`, `bvand`, `bvor`, `bvxor`, `bvnot`, `concat`, `extract`  
**Leaves:** `{ "ref": "stateNN" | "inputN" }`, `{ "const": "...", "width": N }`

**Not supported:** quantifiers, SMT-LIB strings, Verilog names as refs, arbitrary functions.

Implementation: `engines/ic3_frame_ast.{h,cpp}` (planned).

---

## LLM call strategy

### Parallel breadth

**Default:** `K=1` (one API call per batch flush). Optional: `--llm-parallel-samples K` with `K>1` runs K parallel API calls (layers 0–3 identical; layer 4 `sample_id` hint differs).

**Per-response breadth:** each API response may include up to **N** independent `block_clauses` (`--llm-max-block-clauses`, default **3**). C++ tries clauses in order; first valid wins. Candidate budget per flush ≈ **K × N** (default **3**, not 9).

Sidecar concurrency (three levels):

1. **Within one request:** K sample API calls run in parallel (`ThreadPoolExecutor`).
2. **Within one sidecar:** up to `--max-inflight-requests` (default **8**) request lines processed concurrently; responses may arrive out of order (C++ groups by `source_cti_id`).
3. **Across benchmarks (`run_benchmarks.py`):** default **`--parallel 8`** — each worker spawns its **own** pono + sidecar pair with isolated JSONL paths (not one shared sidecar). See [`plans/experiment_parallel_policy.md`](plans/experiment_parallel_policy.md).

- Diversity: `temperature` > 0 in parallel mode, or `sample_id` in layer 4.
- C++ validates all responses; **first** passing `rel_ind_check` is accepted.

### Feedback retry

If all K samples fail → increment `attempt`, attach `feedback[]` (reason + optional witness) → another K parallel calls until `max_attempts`.

Each feedback entry includes:

- `reason`: e.g. `induction_failed`, `rejected_initial`
- `rejected_json`: escaped summary of the rejected response
- `witness` (optional): `{ "ref": "stateNN", "next_value": "..." }`
  - `induction_failed`: `next_value` is the model value of `next(ref)` in the SAT counterexample
  - `rejected_initial`: `next_value` holds the current-state model value of `ref` at initial

Parallel = breadth; retry = depth. Both are used together.

---

## API settings

| Setting | Value |
|---------|--------|
| `reasoning_effort` | **`none`** (default, required for latency) |
| `thinking` | **DeepSeek direct:** `extra_body.thinking.type=disabled`. **OpenRouter:** `extra_body.reasoning.effort=none` + `exclude=true`. Omitting `reasoning_effort` does **not** disable thinking. |
| `temperature` | `0` serial repair; `0.7–0.9` parallel sampling |
| Logging | Sidecar `llm_log.jsonl`: `latency_ms`, `prompt_tokens`, …; C++ stderr: `LLM_BATCH_WAIT batch_id=… wait_ms=…` per sync wait; summary `LLM_STATS batch_waits batch_wait_ms_total batch_wait_ms_max` |

### Latency (measured 2026-06-04, `deepseek-v4-pro`, thinking disabled)

| Prompt shape | user bytes | latency (typical) |
|--------------|------------|-------------------|
| full frame (~477 clauses) | ~22 KB | ~4–6 s |
| last 50 clauses | ~5.5 KB | ~4–5 s |
| CTI only | ~3.6 KB | ~4 s |

With thinking enabled, the same prompts take **~90–220 s** (hidden `reasoning_content` dominates completion tokens). Target **~10 s/call** is met via `thinking.disabled`, not via `max_tokens` truncation.

### Environment (sidecar)

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | if provider=deepseek | In `.env` (secrets only) |
| `OPENROUTER_API_KEY` | if provider=openrouter | In `.env` (secrets only) |

Python deps: `pip install -r llm_worker/requirements.txt` — uses the `openai` package as HTTP client for DeepSeek's OpenAI-compatible API (not OpenAI models).

Copy `.env.sample` → `.env` (gitignored). Sidecar and `run_benchmarks.py` load it via `python-dotenv`.

| Provider | Endpoint | Default model |
|----------|----------|---------------|
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-v4-pro` |
| `openrouter` | `https://openrouter.ai/api/v1` | `deepseek/deepseek-chat` |

Override model: Pono `--llm-model`, sidecar `--model`, or per-request JSON `model` field (not in `.env`).

CLI: sidecar `--provider {deepseek,openrouter}`; benchmarks `--llm-provider`. The `openai` Python package is only the HTTP client.

---

## Validation pipeline

For each `block` action:

1. JSON schema + registry vocab (`ts_.lookup(ref)`)
2. Build `IC3Formula` (`disjunction=true`, `only_curr`)
3. `check_intersects_initial`
4. `rel_ind_check(frame_idx, ...)`
5. `constrain_frame(frame_idx, blocking)`

For each `refine_predicate` (IC3IA):

1. AST → `Term`
2. `ic3formula_check_valid` + initial check
3. `IC3IA::add_predicate`

---

## CLI (planned)

| Flag | Default | Description |
|------|---------|-------------|
| `--llm-gen-mode` | `none` | `async-cti` enables online integration |
| `--llm-parallel-samples` | `1` | Parallel API calls per batch flush (optional K>1) |
| `--llm-max-block-clauses` | `3` | Independent OR-clauses per response; first valid wins |
| `--llm-max-attempts` | `3` | Feedback retry rounds per batch |
| `--llm-reasoning-effort` | `none` | Passed to API |
| `--llm-temperature` | mode-dependent | Parallel vs retry |
| `--llm-req-path` / `--llm-resp-path` | `/tmp/pono_llm_*.jsonl` | JSONL IPC |

Removed flags (with code): `--llm-candidate-language`, `cube-subset`, `qf-smt`, `predicate-relation`.

---

## Legacy deletion

The following **will be removed** when v1 lands:

### C++ / options

- `LLMCandidate` fields: `keep_literals`, `drop_literals`, `formula`, `CUBE_SUBSET`, `QF_SMT`, `PREDICATE_RELATION`
- `cube_subset_to_blocking`, qf-smt skip branch messaging as permanent path
- `PONO_LLM_ASSERT_LIFTED_LEMMAS` + text lemma list loader in `ic3ia.cpp::reset_solver`
- `--llm-candidate-language` CLI

### Python

- `llm_worker/prompts/cube_subset.txt`
- `llm_worker/prompts/qf_smt.txt`
- Sidecar branches: `build_cube_subset_prompt`, `build_multi_cti_prompt` (replaced by v1 builder)
- Runtime dependence on offline mining scripts (`run_closed_loop_synthesis.py`, etc.) as proof loop — **removed** from `llm_worker/` (see [`llm_worker/README.md`](../llm_worker/README.md))

### Docs superseded by this file

See [`DOC_INDEX.md`](DOC_INDEX.md). Historical injection audits remain as research archive; they do not describe the runtime path after v1.

---

## Implementation checklist

- [x] `docs/ic3_frame_v1_integration.md` (this file)
- [x] JSON schema + `llm_worker/ic3_frame_schema.py` validator
- [x] `engines/ic3_frame_ast.{h,cpp}`
- [x] Harness: `benchmark_context.json`, live `frame_snapshot`, Verilog registry
- [x] Sidecar: layered prompt, parallel K, retry, `reasoning_effort=none`
- [x] Delete legacy code paths listed above
- [x] `refine_predicate` → IC3IA `add_predicate` (Phase 2)
- [ ] E2E: qspiflash p040, accept rate + latency/cached_tokens stats (benchmark phase)

---

## Historical research (not runtime)

Offline Bitwuzla closed-loop, clause lifting, reset_solver injection experiments are documented under `docs/` with **HISTORICAL** banners. They informed v1 design but are **not** carried forward as runtime integration.
