# Pono IC3IA Dump Audit

## Summary

IC3IA frames, clauses, CTIs, and proof obligations are all accessible via
existing C++ data structures. The main challenge is that IC3IA uses
**boolean predicate abstraction** — state-level comparisons like
`state2002 = 1` are abstracted to boolean predicates (e.g., `pred_N`).
This means a frame/CTI dump would output predicate labels, not directly
`state2002` / `state790` variable names.

## Candidate Dump Points

| Data | File | Function | Pros | Cons |
|---|---|---|---|---|
| CTI cubes | `ic3base.cpp:1335` | `capture_cti_context()` | Already has CTILiteral extraction, existing JSONL writer | IC3IA predicates are boolean vars, not stateNN |
| CTI literals | `ic3base.cpp:1259` | `collect_cti_literals()` | varname + value extraction works | Predicate labels may not correspond to raw state names |
| Frame clauses | `ic3base.h:226` | `frames_` member | Accessible as `vector<IC3Formula>`, children are sorted | IC3IA clauses use boolean predicates |
| Frame index | `ic3base.cpp` | Iteration over `frames_` | Exact frame numbers available | Terms only stored at highest frame they hold |

## Available Data Structures

| Structure | Meaning | Fields Available | Can Dump? |
|---|---|---|---|
| `IC3Formula` | Frame clause or CTI cube | `term` (full SMT), `children` (sorted literals), `disjunction` (bool) | Yes — extract children as SMT strings |
| `CTILiteral` | One literal from CTI cube | `varname`, `expr`, `value`, `kind`, `signals`, `term` | Yes — already extracted by `collect_cti_literals()` |
| `CTIContext` | Full CTI capture | `frame_idx`, `literals`, `property_name`, `cti_id` | Yes — already built in `capture_cti_context()` |
| `frames_` | All IC3 frames | `vector[frame][clause]` where clause is `IC3Formula` | Yes — iterate and dump |

## IC3IA Predicate Abstraction Challenge

IC3IA works by abstracting concrete predicates (like `state2002 = 1`) to
boolean variables. The mapping is stored in:
- `lbl2pred_`: label term → predicate term (at `ic3ia.h:~107`)
- `predlbls_`: set of all predicate label symbols

To match dumped data against `state2002` and `state790`, the dump must:
1. Include the `lbl2pred_` mapping (label → concrete predicate expression)
2. OR use `simplify_cti_literal()` which may preserve stateNN names in its output
3. OR parse the SMT terms for stateNN substrings

## Recommended Minimal Dump Location

### CTI Dump

Add in `capture_cti_context()` at `ic3base.cpp:1371` (or in `IC3IA::get_model_ic3formula()`):

```cpp
// After building CTIContext and before dispatching:
if (std::getenv("PONO_LLM_DUMP_IC3IA")) {
    dump_ic3ia_cti(ctx, cube);
}
```

The dump function writes a JSONL line with:
- frame index, literals as strings, variable names extracted

### Frame Clause Dump

Add in `constrain_frame()` at `ic3base.cpp:856` (when a clause is added to a frame):

```cpp
if (std::getenv("PONO_LLM_DUMP_IC3IA")) {
    dump_ic3ia_clause(frame_idx, clause);
}
```

### Predicate Label Mapping

Add in `IC3IA::add_predicate()` at `ic3ia.cpp:437`:

```cpp
if (std::getenv("PONO_LLM_DUMP_IC3IA")) {
    dump_ic3ia_predicate(label, predicate);
}
```

This exports `lbl2pred_` as JSONL so the analyzer can map predicate labels
back to state variable expressions.

## Risks / Unknowns

1. **Predicate labels are boolean vars**: `pred_N` not `state2002`
   → Analyzer must parse predicate expressions for stateNN substrings
2. **Recompilation may break existing LLM integration**: the build already
   works for LLM sidecar. Adding dump code should be safe if guard-checked.
3. **Performance**: dump is opt-in via env var; zero overhead when not set.
4. **SMT string size**: clause terms can be very large (hundreds of chars).
   Dump should truncate or use simplified expressions.
