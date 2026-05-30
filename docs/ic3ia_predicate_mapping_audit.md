# IC3IA Predicate Mapping Audit

## Summary

IC3IA uses boolean predicate abstraction. Each concrete predicate (e.g.,
`state2002 = 1`) is assigned a boolean label. The mapping is bidirectional:

- `lbl2pred_[label]` → predicate term (e.g., `(= state2002 #b1)`)
- `labels_[pred]` → label term (e.g., `assump_HASH_0`)

**Key finding**: CTI cubes from `get_model_ic3formula()` already contain the
REAL predicate expressions (from `lbl2pred_.at(p)`), NOT the labels. This
means `simplify_cti_literal()` operates on predicate terms that may contain
`stateNN` substrings. However, frame clauses use the boolean labels themselves.

## Relevant Data Structures

| Structure | Type | Location | Meaning | Dumpable? |
|---|---|---|---|---|
| `lbl2pred_` | `UnorderedTermMap` | `ic3ia.h:88` | label → predicate term | Yes — iterate and dump |
| `labels_` | `UnorderedTermMap` | `ic3base.h:234` | predicate → label term | Yes — iterate and dump |
| `predlbls_` | `UnorderedTermSet` | `ic3ia.h:89` | Set of all predicate labels | Yes — iterate |
| `predset_` | `UnorderedTermSet` | `ic3ia.h:70` | Set of all predicate terms | Yes — iterate |

## Label Format

Labels use the format `assump_{hash}_{counter}` where `hash` is from
`term->hash()` and `counter` is an incrementing disambiguation index.
Labels are **not stable across runs** because hashes depend on internal
SMT solver term IDs.

**Exception**: When the predicate is a Boolean symbolic constant (e.g.,
a state variable like `state2002`), `label()` returns the term itself
as its own label. These ARE stable.

## Candidate Dump Locations

| Location | File:Line | Pros | Cons |
|---|---|---|---|
| `add_predicate()` | `ic3ia.cpp:437` | Captures every predicate as it's created | Called many times, needs append mode |
| Post-initialize dump | `ic3ia.cpp:210` | All predicates known, one-shot dump | Misses predicates added during refinement |
| `reset_solver()` | `ic3ia.cpp:372` | All predicates re-asserted here | Ephemeral, may miss some |
| Custom dump method | New function | Controllable, clean | Needs header change + recompile |

## Recommended Minimal Dump

Add a dump function to `LLMGeneralizer` (or IC3IA directly) that iterates
`lbl2pred_` and writes one JSONL line per predicate. Call it once after
IC3IA initialization and after significant predicate additions.

Env var opt-in: `PONO_LLM_DUMP_IC3IA=1`

### For bit-level IC3

CTI cubes already use state variables directly (`term->to_string()` returns
`state_2002`). No predicate mapping needed — variable names are embedded in
the terms. Frame clauses also use the same state variables.

### For IC3IA

- **CTI cubes**: `get_model_ic3formula()` produces actual predicate terms.
  `simplify_cti_literal()` on these may contain stateNN substrings.
- **Frame clauses**: use boolean labels. Need `lbl2pred_` mapping to resolve.
- **Predicate map**: dump `lbl2pred_` as JSONL for the analyzer.

## Risks / Unknowns

1. **Label instability**: `assump_HASH_0` names change between runs. The
   mapping is only valid within a single Pono execution.
2. **Boolean state variables**: If `state2002` is used as a precise predicate,
   its label IS `state2002` — no mapping needed.
3. **Frame clause format**: IC3IA frame clauses use the boolean labels.
   Without the mapping, they appear as `assump_1234_0` rather than
   `(state2002 = 1)`.
4. **Recompilation risk**: Adding dump code requires recompiling Pono and
   may affect the existing LLM integration if not carefully isolated.
