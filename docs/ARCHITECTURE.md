# Pono + LLM 架構說明 (IC3 Frame v1)

> **Canonical spec:** [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)  
> Legacy `cube_subset` / `qf_smt` / Path 1 assert injection **will be deleted** (not deprecated).

## 整體流程

```text
pono (C++)                         sidecar (Python)                 LLM API
─────────                          ────────────────                 ───────
IC3/IC3IA 執行中
  │
  ├─ reaches_bad() → CTI cube
  │   └─ capture_cti_context()
  │       └─ serialize ic3_frame_request v1
  │           (benchmark_context w/ symbol_registry + compact frame_snapshot)
  │       └─ JSONL ──────────────────→  sidecar poll
  │                                        │
  │                                   Layer 0–3 cached prefix
  │                                   K parallel calls (reasoning_effort=none)
  │                                        │
  │                                   ── HTTP POST × K ──→  API
  │                                   ←── JSON × K ───────
  │                                        │
  │                                   ic3_frame_response v1 × K
  │       ← JSONL ────────────────────────┘
  │
  ├─ process_frame_responses()
  │   ├─ poll → parse ic3_frame_response
  │   ├─ ast → IC3Formula / Term
  │   ├─ rel_ind_check(frame_idx from request)
  │   ├─ first accept → constrain_frame / add_predicate
  │   └─ all reject → write feedback → retry (max_attempts)
  │
  └─ 繼續 IC3 主迴圈
```

## 檔案架構 (v1 target)

```text
pono-llm/
├── engines/
│   ├── ic3_frame_ast.cpp/h     ← JSON AST → Term / IC3Formula (planned)
│   ├── llm_generalizer.cpp/h   ← JSONL IPC, parallel response poll
│   ├── ic3base.cpp/h           ← CTI capture, validate, constrain_frame
│   └── ic3ia.cpp               ← add_predicate hook
├── llm_worker/
│   ├── sidecar.py              ← layered prompt, parallel K, retry
│   ├── deepseek_client.py      ← reasoning_effort=none, temperature modes
│   ├── ic3_frame_schema.py     ← JSON validator (planned)
│   └── prompts/
│       └── ic3_frame_v1.txt    ← single prompt template (planned)
├── frontends/btor2_encoder.cpp ← symbol_map_ → Verilog registry
└── docs/
    ├── ic3_frame_v1_integration.md
    └── ARCHITECTURE.md         ← 本文件
```

**Deleted with v1:** `llm_worker/prompts/cube_subset.txt`, `llm_worker/prompts/qf_smt.txt`, `--llm-candidate-language`, `PONO_LLM_ASSERT_LIFTED_LEMMAS`.

## Prompt 分層 (cache-friendly)

| Layer | 內容 | 同 circuit |
|-------|------|------------|
| 0 | system + schema | 固定 |
| 1 | benchmark static | 固定 |
| 2 | symbol_registry + **Verilog** | 固定 |
| 3 | frame_snapshot | 隨 frame / proof 變 |
| 4 | cti + feedback + sample_id | 每 call 唯一 |

## Request / Response

Full schemas: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md).

- Request 權威欄位：`frame_idx`, `cti_id`, `cti`, `frame_snapshot`（`symbol_registry` 在 `benchmark_context.json`）
- Response：最多 1× `block` + 0~1× `refine_predicate`；無 `frame_hint`
- 符號引用：`ref: stateNN` only；Verilog 為語意提示

## 驗證管線

```text
parallel K responses
  → schema + ts_.lookup(ref)
  → IC3Formula (disjunction=true)
  → check_intersects_initial
  → rel_ind_check(frame_idx)
  → constrain_frame / add_predicate
  → first accept wins
  → else feedback → retry
```

## CLI (v1 target)

| 參數 | 預設 | 說明 |
|------|------|------|
| `--llm-gen-mode` | `none` | `async-cti` 啟用線上整合 |
| `--llm-parallel-samples` | `3` | 每 request 平行 API 次數 |
| `--llm-max-attempts` | `2` | feedback retry 輪數 |
| `--llm-reasoning-effort` | `none` | API reasoning 控制 |
| `--llm-accepted-budget` | `50` | 最多接受幾個 frame actions |
| `--llm-req-path` / `--llm-resp-path` | `/tmp/pono_llm_*.jsonl` | JSONL 路徑 |

## BTOR2 / Verilog mapping

| Layer | Name | Source |
|-------|------|--------|
| Runtime ref | `state1536` | `ts_.lookup` |
| BTOR2 | line 1536 | `.btor2` file |
| Verilog | `o_dspi_mod` | `symbol_map_` in `btor2_encoder.cpp` |

Harness **must** include `verilog` in `symbol_registry` when mapping exists.

## Stats

```text
LLM_STATS accepted=... rejected=... parallel_samples=... attempts=... cached_tokens=... latency_ms=...
```

## Offline research (not runtime)

Historical offline-dump / closed-loop / reset_solver injection docs remain under `docs/` with **HISTORICAL** tags. They are **not** part of v1 runtime. See [`DOC_INDEX.md`](DOC_INDEX.md).
