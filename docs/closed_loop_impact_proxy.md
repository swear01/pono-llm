> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Closed-Loop Impact Proxy

## Lemma

```
(=> (= state2002 1) (= state790 1))
r_pipe_req => o_wb_stall
```

## CTI/CE Blocking Proxy

### Sample Coverage

| Metric | Count |
|---|---|
| Total historical samples (reachable + CE) | 17 |
| Samples covering both state2002 & state790 | 1 (init_state) |
| Lemma holds on covered sample | 1/1 |
| Lemma violated | 0 |

The init sample has state2002=0, state790=1. The lemma holds (antecedent false →
vacuously true). No historical counterexample covers both variables simultaneously.

### Original 30 Yield Analysis

| Metric | Count |
|---|---|
| Candidates using state2002 | 3 |
| Candidates using state790 | 3 |
| Candidates using BOTH | **0** |

The lemma `state2002⇒state790` is a **novel relation** — no candidate in the
original batch of 30 proposed an implication or relation joining these two
variables. All previous candidates paired state2002 or state790 with other
variables (state1536, state79, state1558).

### Failed Candidate Relation

The lemma does not directly "explain" or "block" any prior failed candidate
because:
- Prior candidates used different variable pairs
- The lemma's variables (state2002, state790) appear separately in prior
  candidates but never together

The lemma is a **newly discovered invariant**, not a repair or generalization
of an existing candidate.

## Clause/Frame Relevance Proxy

IC3IA trace data (frame clauses, CTI snapshots) is **not available** for the
qspiflash_divfive-p040 benchmark. The project's current pipeline runs offline
Bitwuzla validation on candidates proposed from batch generation and
counterexample-directed synthesis — it does not have access to IC3IA frame
data.

### Missing Artifact

To estimate clause impact, a minimal Pono C++ dump would need:

```json
{
  "benchmark": "qspiflash_dualflexpress_divfive-p040",
  "frames": [
    {
      "frame_idx": 0,
      "clauses": [
        {
          "clause": "(OR (NOT state2002) state790 ...)",
          "predicates": ["state2002", "state790", ...]
        }
      ]
    }
  ]
}
```

The dump should export IC3IA frame clauses with predicate labels that match
the BTOR2 node IDs used in this project.

Without this data, clause subsumption impact cannot be estimated.

## Conclusion

The lemma `r_pipe_req ⇒ o_wb_stall` is:
- **Consistent with all 17 historical samples** (0 violations)
- **A novel relation** — no prior candidate proposed it
- **Validated across 6 qspiflash variants** (all pass)
- **IC3IA clause impact unknown** — frame data not available

The lemma is formally verified but its impact on IC3IA proof search cannot
be measured without Pono frame clause data.
