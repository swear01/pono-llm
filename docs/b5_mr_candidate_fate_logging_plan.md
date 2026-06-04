> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# B5-MR Candidate Fate Logging Plan

## Goal

Add per-candidate JSONL logging to B5-MR so failure reasons can be classified.

## Candidate Fate Schema

```json
{
  "candidate_id": "b5mr_001",
  "context_dump_id": "dump_001",
  "raw_predicate": "(=> (state469 = 0) (state15 = 0))",
  "normalized_predicate": "...",
  "location": "context_dump_001_candidate_001",
  "variables": ["state469", "state15"],
  "parse_status": "ok",
  "type_status": "ok",
  "duplicate_status": "new",
  "path_implied": true,
  "solver_status": "accepted",
  "rejection_reason": "",
  "added_to_cpa": true
}
```

## Fields

| Field | Type | Description |
|---|---|---|
| candidate_id | string | Unique ID per candidate |
| context_dump_id | string | Which context dump produced this candidate |
| raw_predicate | string | LLM raw output |
| normalized_predicate | string | After whitespace/format normalization |
| parse_status | enum | ok / failed |
| type_status | enum | ok / failed / skipped |
| duplicate_status | enum | new / duplicate_bootstrap / duplicate_interpolant / duplicate_candidate |
| path_implied | bool | True if the spurious trace implies the predicate |
| solver_status | enum | accepted / rejected / skipped |
| rejection_reason | string | Human-readable rejection reason |
| added_to_cpa | bool | Whether added to CPAchecker predicate set |

## Logging Points

In the B5-MR pipeline:

```text
1. LLM candidate generation → record raw_predicate
2. Parse → record parse_status
3. Type check → record type_status
4. Duplicate check → record duplicate_status
5. Path implication → record path_implied
6. Solver validation → record solver_status, rejection_reason
7. Injection → record added_to_cpa
```

## Output

```text
logs/context_unlock/b5_mr_candidate_fates.jsonl
```

One line per candidate. If no candidates generated, write a summary line.

## Implementation Location

In the CPAchecker fork (external repo), find the B5-MR candidate processing
loop and add JSONL writes using the schema above.
