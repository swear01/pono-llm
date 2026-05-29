# Lemma Impact Proxy Plan

## Motivation

The lemma `r_pipe_req ⇒ o_wb_stall` is audited, cross-parameter validated,
and repeatably discoverable. However, its relevance to IC3IA proof search
is unknown. Before integrating with Pono's `rel_ind_check`, we need to
estimate whether this lemma would actually help IC3IA converge faster.

This document specifies the minimal infrastructure needed to answer that
question — without doing full Pono frame injection.

## Current State

- Lemma validated under offline Bitwuzla pipeline (88% transition coverage)
- 6/6 qspiflash variants pass
- 5/8 closed-loop trials discover the lemma
- IC3IA frame clauses, CTI cubes, and proof obligations are NOT available

## Minimal Pono Dump Needed

### Frame Clause Dump

```
logs/pono_frame_dump/qspiflash_p040_frames.jsonl
```

```json
{
  "type": "clause",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "frame": 8,
  "clause_id": "F8_C123",
  "literals": ["state2002=0", "state790=1", "state1536=10"],
  "variables": ["state2002", "state790", "state1536"],
  "raw_smt": "(or (not (= state2002 #b1)) (= state790 #b1) (not (= state1536 #x0a)))"
}
```

### CTI Cube Dump

```
logs/pono_frame_dump/qspiflash_p040_ctis.jsonl
```

```json
{
  "type": "cti",
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "frame": 12,
  "cube": ["state2002=1", "state790=0", "state1536=15"],
  "variables": ["state2002", "state790", "state1536"],
  "violates_lemma": true
}
```

### Predicate Label Mapping

Pono's IC3IA uses predicate labels that MAY differ from BTOR2 node IDs.
The dump must include either:
- A mapping file: `stateNN` → BTOR2 node → Verilog symbol
- Or inline BTOR2 node IDs in each clause/CTI record

This project already confirmed that `stateNN` names ARE BTOR2 node IDs for
qspiflash. If this holds for other benchmarks, no additional mapping is needed.

## Planned Analyzer

```
llm_worker/analyze_lemma_impact.py
```

### Inputs
- `logs/pono_frame_dump/qspiflash_p040_frames.jsonl`
- `logs/pono_frame_dump/qspiflash_p040_ctis.jsonl`
- Validated lemma: `(=> (= state2002 1) (= state790 1))`

### What it computes

1. **Variable occurrence**: count frame clauses and CTI cubes that mention
   `state2002` or `state790`

2. **Lemma violation**: count CTI cubes that directly violate the lemma
   (state2002=1 AND state790=0)

3. **Clause subsumption proxy**: for each frame clause C, check if the lemma
   implies C. If so, C could potentially be removed or strengthened.

4. **Frame distribution**: identify the highest frame where state2002/state790
   appear. Lemmas are most useful at mid-to-high frames where proof obligations
   accumulate.

5. **Repeated CTI patterns**: identify recurring CTI cube patterns involving
   state2002/state790 that the lemma would block.

### Outputs

```
docs/lemma_impact_proxy.md
logs/formal_yield/lemma_impact_proxy.json
```

## Metrics

| Metric | What it measures |
|---|---|
| `clauses_with_var` | Number of frame clauses mentioning state2002 or state790 |
| `clauses_subsumeable` | Clauses potentially strengthened by the lemma |
| `ctis_with_var` | CTI cubes involving state2002 or state790 |
| `ctis_violating_lemma` | CTI cubes with state2002=1 AND state790=0 |
| `highest_frame_with_var` | Frame where these variables still appear in CTIs |
| `lemma_impact_score` | Heuristic score (clauses_subsumeable / total_clauses) |

## Interpretation

- **High impact**: lemma subsumes many clauses or blocks many CTIs
  → proceed to `rel_ind_check` integration
- **Low impact**: lemma covers few clauses or CTIs
  → search for additional useful lemmas, broader variable context
- **No data**: frame/CTI dump not available
  → blocker: implement minimal Pono C++ dump

## Non-Claims

- This is NOT runtime speedup measurement
- This is NOT benchmark unlock
- This is NOT full Pono integration
- This is a **proof relevance proxy** — an estimate, not a measurement

## Implementation Location

The minimal dump should be added to Pono's IC3IA loop:

- `engines/ic3ia.cpp`: after CTI capture, write to JSONL
- `engines/ic3base.cpp`: after frame clause generation, write to JSONL
- `frontends/btor2_encoder.cpp`: write symbol_map_ to JSON

The dump is read-only (does not modify IC3IA behavior) and can be disabled
via a CLI flag (`--llm-dump-frames-path <dir>`).
