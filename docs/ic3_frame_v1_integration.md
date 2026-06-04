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
| 1 | benchmark static (property, init summary) | Fixed per `.btor2` |
| 2 | `symbol_registry` ( **Verilog required** , btor2_line, width) | Fixed per circuit |
| 3 | `frame_snapshot` (frontier OR clauses) | Changes per frame / as proof adds clauses |
| 4 | `cti` + `feedback` + `sample_id` | Unique per API call |

Layers 0–2 are stable → provider prefix cache. Layer 3–4 change each request; sidecar renders them as **compact line text** in the API user prompt (JSONL on disk stays JSON).

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
  "max_attempts": 2,
  "parallel_group": "cti_000123_a1",
  "parallel_samples": 3,
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
- Sidecar reads `benchmark_context_path` for benchmark name, property, and symbol registry.
- LLM must cite symbols only as `ref` (`stateNN`, `inputN`); Verilog is semantic hint only.
- C++ writes `benchmark_context.json` (layers 1–2) once at startup; sidecar caches it.
- Request JSON uses minimal fields: literals `{atom:{ref,rhs},polarity}`, clauses `{disjuncts:[...]}`.

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

- At most **one** `block` action (multiple `disjuncts` allowed inside the OR clause).
- At most **one** optional `refine_predicate` action (IC3IA only).
- **No** multiple independent `block` actions per response; use parallel sampling instead.

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

Same request (layers 0–3 identical) → **K parallel** API calls (`--llm-parallel-samples`, default 3).

Sidecar concurrency (two levels):

1. **Within one request:** K sample API calls run in parallel (`ThreadPoolExecutor`).
2. **Across requests:** up to `--max-inflight-requests` (default 4) request lines processed concurrently; responses may arrive out of order (C++ groups by `source_cti_id`).

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
| `temperature` | `0` serial repair; `0.7–0.9` parallel sampling |
| Logging | `latency_ms`, `cached_tokens`, `prompt_hash`, `sample_id` |

### Environment (sidecar)

| Variable | Required | Description |
|----------|----------|-------------|
| `DEEPSEEK_API_KEY` | yes | DeepSeek API key; read by [`llm_worker/sidecar.py`](../llm_worker/sidecar.py) at runtime |

Python deps: `pip install -r llm_worker/requirements.txt` — uses the `openai` package as HTTP client for DeepSeek's OpenAI-compatible API (not OpenAI models).

Endpoint: `https://api.deepseek.com/v1`, default model `deepseek-v4-pro` (override via sidecar `--model`).

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
| `--llm-parallel-samples` | `3` | Parallel API calls per request |
| `--llm-max-attempts` | `2` | Feedback retry rounds per CTI |
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
