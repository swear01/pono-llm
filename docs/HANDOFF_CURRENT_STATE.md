# Handoff: Current State

**Last updated:** 2026-06-07  
**Branch:** `main` (pono-llm research fork)

## Active direction

**Online frame-native LLM integration — IC3 Frame v1**

Canonical spec: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)  
Doc index: [`DOC_INDEX.md`](DOC_INDEX.md)

LLM runs **online** during IC3IA proof: CTI → structured JSON → `rel_ind_check` → `constrain_frame` / `add_predicate`. No SMT string parser. No Path 1 reset_solver injection at runtime.

**Legacy runtime (`cube_subset`, `qf_smt`, `PONO_LLM_ASSERT_LIFTED_LEMMAS`) will be deleted** when v1 lands — not deprecated.

---

## v1 design summary

| Topic | Decision |
|-------|----------|
| I/O | `ic3_frame_request` / `ic3_frame_response` v1 only |
| Block | 1 OR clause per response (multi-disjunct OK) |
| Multi-block per response | **Yes** — up to N `block_clauses` per response (default 3), first valid wins |
| Parallel samples | K API calls per batch flush (default **1**); optional `--llm-parallel-samples K>1` |
| Retry | Feedback + witness, max attempts (default 3 rounds) |
| Cache | Prompt layers 0–2 fixed per circuit; log cached_tokens |
| API | `reasoning_effort=none` default |
| Verilog | Required in `symbol_registry` when mapped |
| Frame | `frame_idx` from request only (no `frame_hint`) |

---

## Key files (current → v1)

### Keep / extend

| Path | Role |
|------|------|
| `engines/ic3base.cpp` | CTI capture, validation, `constrain_frame` |
| `engines/llm_generalizer.cpp` | JSONL IPC |
| `engines/ic3ia.cpp` | `add_predicate` |
| `frontends/btor2_encoder.cpp` | `symbol_map_` → Verilog registry |
| `llm_worker/sidecar.py` | Rewrite for v1 prompt + parallel + retry |
| `llm_worker/deepseek_client.py` | Add `reasoning_effort`, temperature modes |

### Planned new

| Path | Role |
|------|------|
| `engines/ic3_frame_ast.{h,cpp}` | AST → Term / IC3Formula |
| `llm_worker/ic3_frame_schema.py` | JSON schema validator |
| `llm_worker/prompts/ic3_frame_v1.txt` | Single prompt template |

### Delete with v1

| Path | Reason |
|------|--------|
| `llm_worker/prompts/cube_subset.txt` | Replaced by v1 |
| `llm_worker/prompts/qf_smt.txt` | Replaced by v1 |
| `LLMCandidate` cube_subset/qf_smt fields | Replaced by `IC3FrameResponse` |
| `ic3ia.cpp` `PONO_LLM_ASSERT_LIFTED_LEMMAS` block | Path 1 removed |
| `--llm-candidate-language` | Removed |

---

## Historical research (archived docs)

Offline closed-loop found `r_pipe_req ⇒ o_wb_stall` (Bitwuzla standalone). Clause lifting 26/30 verified. Injection prototype existed (25/26 injectable). These informed v1 but are **not** the runtime path.

See tagged **HISTORICAL** files in [`DOC_INDEX.md`](DOC_INDEX.md).

---

## HWMCC baseline 實驗狀態（2026-06-07）

| 項目 | 狀態 |
|------|------|
| Output dir | `bench_results/hwmcc_baseline_20260607` |
| 首輪 baseline | 已 suspend（~168 案在 `nohup.log`） |
| Harness 修正 | `_parse_pono_stdout`；`baseline-patch`；`--skip-partial` |
| 進行中 | `baseline-patch` → `results_baseline_partial.csv` |
| 下一步 | `baseline --skip-partial` resume → `results_baseline.csv`（1052 案） |

SOP：[`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) § 中斷恢復。

---

## Immediate next task

1. 完成 `baseline-patch` + `baseline --skip-partial` → 全量 `results_baseline.csv`
2. `--phase report` + `find-solvable` → `candidates.json`
3. Phase E LLM 子集（candidates ∩ baseline 解出 + p040）
4. Rewrite sidecar (layers, parallel K, retry, reasoning_effort=none)
5. Delete legacy paths listed above
6. E2E qspiflash p040

---

## Do not do

- Do not extend `cube_subset` / qf_smt / text lemma grammar
- Do not treat Path 1 injection as production integration
- Do not add free-form SMT parser
- Do not use `reasoning_effort` > none for latency-sensitive online path
