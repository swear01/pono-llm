> **ACTIVE for v1 harness (2026-06-03)** — Dump format reused for live `frame_snapshot` (Layer 3).  
> Spec: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

# Pono IC3IA Frame / CTI Dump Format

## Opt-in

```bash
PONO_LLM_DUMP_IC3IA=1
PONO_LLM_DUMP_DIR=logs/pono_frame_dump
```

Zero overhead when env var is not set.

## Output Files

```
logs/pono_frame_dump/<benchmark>_ctis.jsonl
logs/pono_frame_dump/<benchmark>_frames.jsonl
logs/pono_frame_dump/<benchmark>_obligations.jsonl  (optional)
logs/pono_frame_dump/<benchmark>_predicates.jsonl   (optional, for label mapping)
```

## CTI Cube Dump

One JSONL line per CTI counterexample:

```json
{
  "type": "cti",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "frame": 12,
  "cti_id": "cti_000123",
  "cube": [
    {"varname": "state2002", "expr": "state2002 = 1", "value": "1", "kind": "state"},
    {"varname": "state790", "expr": "state790 = 0", "value": "0", "kind": "state"},
    {"varname": "state1536", "expr": "state1536 = 15", "value": "15", "kind": "state"}
  ],
  "variables": ["state2002", "state790", "state1536"],
  "violates_target_lemma": null,
  "raw_smt": "(and (= state2002 #b1) (= state790 #b0) (= state1536 #x0f))"
}
```

Fields:
- `cube[].varname`: simplified variable name from `simplify_cti_literal()`
- `cube[].expr`: human-readable expression
- `cube[].value`: "true"/"false" or numeric value
- `cube[].kind`: "state"/"input"/"unknown"
- `violates_target_lemma`: `null` (computed by analyzer, not in dump)

## Frame Clause Dump

One JSONL line per clause added to a frame:

```json
{
  "type": "clause",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "frame": 8,
  "clause_id": "F8_C123",
  "literals": [
    {"varname": "state2002", "polarity": "negated", "raw": "(not (= state2002 #b1))"},
    {"varname": "state790", "polarity": "positive", "raw": "(= state790 #b1)"}
  ],
  "variables": ["state2002", "state790"],
  "is_disjunction": true,
  "literal_count": 2,
  "raw_smt": "(or (not (= state2002 #b1)) (= state790 #b1))"
}
```

Fields:
- `literals[].varname`: extracted variable name
- `literals[].polarity`: "positive" or "negated"
- `is_disjunction`: always true for blocking clauses
- `literal_count`: number of literals in the clause

## Predicate Label Mapping (IC3IA-specific, optional)

```json
{
  "type": "predicate",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "label": "pred_42",
  "predicate_expr": "(= state2002 #b1)",
  "variables": ["state2002"]
}
```

## Predicate Label Mapping Dump (IC3IA-specific)

One JSONL line per predicate, written when predicates are added via
`IC3IA::add_predicate()`.

```json
{
  "type": "predicate_map",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "predicate_id": 17,
  "label": "pred_17",
  "raw_expr": "(= state2002 #b1)",
  "pretty_expr": "state2002 = 1",
  "variables": ["state2002"],
  "state_values": {
    "state2002": "1"
  },
  "polarity_note": "label is true iff raw_expr is true"
}
```

### Resolving Frame Clause Literals via Predicate Map

Frame clauses in IC3IA reference predicates by label:

```json
{
  "type": "clause",
  "frame": 8,
  "literals": [
    {"label": "pred_17", "polarity": true, "resolved_expr": "state2002 = 1"},
    {"label": "pred_42", "polarity": false, "resolved_expr": "state790 = 1"}
  ]
}
```

Polarity semantics:
- `polarity=true` → the predicate expression holds in the model
- `polarity=false` → the predicate expression does NOT hold

When `pred_42 = (state790 = 1)` and `polarity=false`, the analyzer infers
`state790 = 0`. This inference is only valid when the predicate is a
simple Boolean equality over a 1-bit variable.

### Label Format

IC3IA uses the format `assump_{hash}_{counter}` (e.g., `assump_39827134_0`).
Labels are NOT stable across runs. The mapping is only valid within a single
Pono execution.

Exception: Boolean state variables used as precise predicates reuse their
own symbolic names as labels (e.g., `state2002`). These ARE stable.

## Implementation Notes

1. **No external JSON library needed**: follow existing `std::ostringstream` pattern.
2. **Dump only when env var is set**: check `std::getenv("PONO_LLM_DUMP_IC3IA")`.
3. **For IC3IA**: include predicate label mapping to resolve `pred_N` → `state2002 = 1`.
4. **For bit-level IC3**: variable names are already stateNN in the terms.
5. **raw_smt is optional**: use `term->to_string()` for SMT-LIB2 representation.
