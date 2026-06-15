> Archived: 2026-06-15
> Reason: Pre-Stage-0/2 research record (offline lemma-mining / closed-loop / Q-phase era, ~2026-06); runtime path deleted in v1 pivot
> Replacement: none
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime path. See [`ic3_frame_v1_integration.md`](../ic3_frame_v1_integration.md).

# Offline LLM Repair Replay Design

## Goal

Make the LLM useful for IC3/PDR lemma generalization by moving from single-shot candidate acceptance to an offline, solver-checked proposal-and-repair experiment. The first success criterion is practical, not architectural: at least one LLM-generated or LLM-repaired generalized cube must pass `rel_ind_check()` on a real HWMCC benchmark.

## Problem Statement

The current async CTI pipeline can ask the LLM for `keep_literals` / `drop_literals`, but a candidate is useful only if the resulting blocking clause is relative-inductive. In practice the LLM often drops too many literals, so the candidate cube includes a legal one-step successor from `F[k-1]`; `rel_ind_check()` returns SAT and the whole candidate is discarded. That makes the LLM contribution effectively zero even when part of its generalization direction is plausible.

We need a workflow where:

1. The LLM can make aggressive generalized-cube proposals.
2. The SMT solver remains the only soundness authority.
3. SAT witnesses from failed proposals are converted into repair feedback.
4. A second LLM call can add back a small number of dropped literals.
5. The result is replayed and measured before changing the live IC3 loop.

## Scope

This design covers an offline replay MVP, not production live integration.

In scope:

- ID-based CTI literal representation.
- Thin benchmark-level static context (`0A`) for LLM prompts.
- Dynamic CTI/frame context (`0B`) for each proposal.
- Offline proposal generation with the LLM.
- Replay checking inside Pono against the real transition system and current frame sequence.
- SAT witness diff extraction for failed proposals.
- Offline repair generation with the LLM.
- Replay checking of repaired candidates.
- JSONL result files and summary statistics.

Out of scope for the MVP:

- Replacing the existing async sidecar protocol.
- Waiting for the LLM inside the IC3 main loop.
- Using a sliced circuit for soundness checks.
- Full 1M-token raw-circuit dumping.
- Multi-model benchmarking.
- Parallel LLM batching.

## Key Design Constraint: Replay Must Happen Inside a PDR Run

A candidate check needs `F[k-1]`, the transition relation `T`, and the CTI cube terms. Dumped JSON alone is not enough to reconstruct `F[k-1]` in a separate Python process. Therefore offline replay is implemented as repeated deterministic Pono passes:

1. **Collect pass:** Pono runs normally and dumps static context plus CTI contexts.
2. **LLM proposal pass:** Python reads dumped contexts and writes proposal JSONL.
3. **Proposal replay pass:** Pono reruns the benchmark, matches current CTIs by stable `cti_id`, checks available proposals with live `rel_ind_check()`, accepts UNSAT proposals, and writes repair requests for SAT failures.
4. **LLM repair pass:** Python reads repair requests and writes repair JSONL.
5. **Repair replay pass:** Pono reruns the benchmark, applies proposal plus repair data, checks repaired candidates, accepts UNSAT repairs, and writes final results.

This keeps every soundness decision inside the original C++ solver/PDR environment while still allowing LLM calls to happen offline.

## 0A: Static Cached Benchmark Context

`0A` is benchmark-level information that does not change across CTIs. It is safe to place at the front of prompts and benefit from provider prefix caching.

The MVP `static_context.json` contains:

```json
{
  "schema_version": 1,
  "benchmark": "example.btor2",
  "property": {
    "bad_expr": "state76 & ~state5"
  },
  "states": [
    {"name": "state76", "width": 1},
    {"name": "state383", "width": 4}
  ],
  "inputs": [
    {"name": "input4", "width": 1}
  ],
  "state_updates": [
    {
      "target": "state76",
      "expr": "(state5 & input4) | state76",
      "depends_on": ["state5", "input4", "state76"]
    }
  ],
  "bad_dependencies": ["state76", "state5"],
  "notes": [
    "The solver checks every candidate on the full transition system. This context is only heuristic guidance."
  ]
}
```

The static facts are deterministic exports from Pono, not LLM inventions. A later version may ask the LLM to produce a cached “circuit handbook” from these facts, but the MVP can start with deterministic facts only.

## 0B: Dynamic CTI Query Context

`0B` changes per CTI and per repair round. Each CTI is emitted as one JSONL record:

```json
{
  "schema_version": 1,
  "cti_id": "frame4:9b6c1a...",
  "frame": 4,
  "property": "state76 & ~state5",
  "literals": [
    {
      "id": 0,
      "expr": "state76 = true",
      "varname": "state76",
      "value": "true",
      "kind": "state",
      "signals": ["state76"]
    },
    {
      "id": 1,
      "expr": "input4 = true",
      "varname": "input4",
      "value": "true",
      "kind": "input",
      "signals": ["input4"]
    }
  ],
  "local_slice": {
    "signals": ["state76", "input4"],
    "state_updates": [
      {"target": "state76", "expr": "(state5 & input4) | state76"}
    ]
  }
}
```

Literal IDs are stable within a CTI. LLM outputs must reference IDs, not copied expression strings, to avoid string-matching failures between simplified and raw SMT representations.

## LLM Proposal Format

The proposal driver reads `static_context.json` and `cti_contexts.jsonl`, then writes `proposals.jsonl`:

```json
{
  "schema_version": 1,
  "cti_id": "frame4:9b6c1a...",
  "mode": "proposal",
  "keep_ids": [0, 3, 7],
  "drop_ids": [1, 2, 4, 5, 6],
  "confidence": "medium",
  "short_reason": "Keeps control predicates near bad and drops input/encoding details."
}
```

The prompt tells the LLM that it is proposing a generalized cube `g`, not proving soundness. The solver will accept the candidate only when `F[k-1] ∧ T ∧ g'` is UNSAT.

## Proposal Replay and Witness Diff

During replay, Pono matches the current CTI by `cti_id`, converts `keep_ids` into a candidate conjunction `g`, and checks:

```text
F[k-1] ∧ T ∧ g'
```

If UNSAT:

- Insert the corresponding blocking clause `¬g` into the target frame.
- Write `accepted_initial` to `replay_results.jsonl`.

If SAT:

- Do not insert the candidate.
- While the solver model is still available, evaluate each dropped literal `d` in next-state form, `d'`.
- A dropped literal becomes a repair candidate when the model does not satisfy `d'`; adding that literal back would exclude the current reachable witness.
- Write a repair request to `repair_requests.jsonl`.

Example repair request:

```json
{
  "schema_version": 1,
  "cti_id": "frame4:9b6c1a...",
  "frame": 4,
  "failed_keep_ids": [0, 3],
  "failed_drop_ids": [1, 2, 4, 5],
  "sat_witness_diff": [
    {
      "literal_id": 4,
      "cti_literal": "input9 = false",
      "witness_value": "input9' = true",
      "effect": "Adding this literal back excludes the SAT witness."
    }
  ]
}
```

The replay code must use a dedicated helper for proposal checking because existing `rel_ind_check()` pops the solver context before returning. Witness diff extraction must happen before the context is popped.

## LLM Repair Format

The repair driver reads `static_context.json`, the original CTI context, and `repair_requests.jsonl`, then writes `repairs.jsonl`:

```json
{
  "schema_version": 1,
  "cti_id": "frame4:9b6c1a...",
  "mode": "repair",
  "base_keep_ids": [0, 3],
  "add_back_ids": [4],
  "confidence": "medium",
  "short_reason": "input9 gates the transition that created the reachable witness."
}
```

Repair replay checks:

```text
keep_ids := base_keep_ids ∪ add_back_ids
```

A repair is accepted only if the resulting candidate passes the full solver check.

## Files Produced by a Replay Experiment

Each benchmark gets a replay directory:

```text
llm_replay/<benchmark-slug>/
  static_context.json
  cti_contexts.jsonl
  proposals.jsonl
  proposal_replay_results.jsonl
  repair_requests.jsonl
  repairs.jsonl
  repair_replay_results.jsonl
  summary.json
```

`summary.json` includes at least:

```json
{
  "num_ctis": 50,
  "proposal_records": 50,
  "proposal_accepts": 2,
  "proposal_sat_failures": 31,
  "repair_requests": 28,
  "repair_records": 28,
  "repair_accepts": 5,
  "invalid_llm_json": 3,
  "avg_original_cube_size": 19.2,
  "avg_accepted_cube_size": 6.4
}
```

## CLI Shape

The MVP adds offline replay modes to `--llm-gen-mode`:

```text
--llm-gen-mode offline-dump
--llm-gen-mode offline-check
```

and adds a replay directory option:

```text
--llm-replay-dir <path>
```

`offline-dump` writes `static_context.json` and `cti_contexts.jsonl` but does not call the LLM and does not insert LLM lemmas.

`offline-check` reads `proposals.jsonl` and/or `repairs.jsonl` from the replay directory. When matching CTIs appear during the run, it checks candidates, inserts accepted lemmas, writes replay results, and writes repair requests for failed proposals.

Python tools:

```text
python3 llm_worker/offline_repair_driver.py propose --replay-dir <dir> --model <model>
python3 llm_worker/offline_repair_driver.py repair --replay-dir <dir> --model <model>
python3 llm_worker/offline_repair_driver.py summarize --replay-dir <dir>
```

## Expected Experiment Flow

```bash
# 1. Collect CTIs and static context
build/pono -e ic3ia --llm-gen-mode offline-dump \
  --llm-replay-dir llm_replay/foo foo.btor2

# 2. Ask LLM for initial proposals
python3 llm_worker/offline_repair_driver.py propose \
  --replay-dir llm_replay/foo --model deepseek/deepseek-v4-pro

# 3. Replay proposals and dump SAT-witness repair requests
build/pono -e ic3ia --llm-gen-mode offline-check \
  --llm-replay-dir llm_replay/foo foo.btor2

# 4. Ask LLM to repair failed proposals
python3 llm_worker/offline_repair_driver.py repair \
  --replay-dir llm_replay/foo --model deepseek/deepseek-v4-pro

# 5. Replay repairs and summarize
build/pono -e ic3ia --llm-gen-mode offline-check \
  --llm-replay-dir llm_replay/foo foo.btor2
python3 llm_worker/offline_repair_driver.py summarize --replay-dir llm_replay/foo
```

## Correctness and Safety

- LLM context is heuristic only.
- Every accepted candidate is checked against the full transition system and current frame sequence.
- A sliced or summarized circuit is never used as proof evidence.
- If a candidate references invalid literal IDs, it is rejected and logged.
- If no proposal or repair exists for a CTI, Pono continues with baseline IC3 behavior.
- If accepted LLM lemmas alter later CTI order, matching by `cti_id` naturally applies only to CTIs that still occur.

## Testing Strategy

Unit tests:

- Stable CTI ID generation from literal IDs/expressions/values.
- ID-based proposal parsing and validation.
- Conversion from `keep_ids` to candidate conjunction and blocking clause.
- Repair candidate extraction from mocked witness truth values.
- Python prompt builder produces JSON-only proposal and repair prompts.
- Python parser rejects missing or out-of-range literal IDs.

Integration tests:

- Run `offline-dump` on a small sample and confirm `static_context.json` and `cti_contexts.jsonl` are produced.
- Run a fake `proposals.jsonl` with `keep_ids` equal to the full CTI and confirm replay can parse and check it.
- Run a deliberately over-generalized proposal and confirm `repair_requests.jsonl` is written when the solver returns SAT.
- Run `summarize` and confirm counts match JSONL records.

Experiment success metrics:

- `proposal_accepts > 0` or `repair_accepts > 0` on at least one selected benchmark.
- Accepted candidates have smaller average cube size than the original CTI cube.
- No accepted candidate bypasses `rel_ind_check()`.

## Future Work

After the offline MVP proves useful, integrate the same protocol into a live or semi-live sidecar flow. The likely next step is to keep 0A cached per benchmark and let Pono synchronously or asynchronously request repairs for a bounded number of high-value CTIs.
