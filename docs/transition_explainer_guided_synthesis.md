> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Transition-Explainer-Guided Synthesis

## Transition Slice Audit

The existing `transition_slice.py` provides `explain_btor_expr()` which
recursively expands BTOR2 expressions into pseudo-Verilog with a depth
limit of 10.

### Slice Quality

| Variable | Symbol | Width | Deps | Readability | Summary |
|---|---:|---|---|---|---|
| state1536 | o_dspi_mod | 4 | 15 | poor | 667 chars, 23 opaque `<L>` refs. Deeply nested ITE. |
| state790 | o_wb_stall | 1 | 13 | poor | 380 chars, 10 opaque refs. Complex OR/ITE. |
| state1558 | cfg_speed | 1 | 5 | good | 77 chars. Simple ITE on config strobe. |
| state2002 | r_pipe_req | 1 | 11 | medium | 162 chars. Partially readable ITE. |
| state79 | cfg_mode | 1 | 7 | good | 100 chars. Simple ITE on config strobe. |

### Limitations

- **Depth limit (10)** causes leaf subexpressions to become `<LN op=X>` refs
- state1536 and state790 are central to most lemma candidates but have the
  least readable transition logic
- Dependency lists are comprehensive but don't capture causal direction
- The explainer doesn't simplify common patterns (e.g., "reset → 0")

### What works for LLM prompting

- **Dependency summaries**: listing which state vars and inputs each variable
  depends on gives LLM structural context even when formulas are opaque
- **Readable variables**: state1558 and state79 have simple, understandable
  transition logic useful for reasoning about config-strobe-driven behavior
- **Semantic annotations**: human-authored notes about what each variable
  represents help ground the transition context

## Failure Analysis Using Transition Slices

### C1: `state1536=10 => state790=0`

Counterexample: state1536=10, state790=1
Transition analysis: state1536 next depends on 15 signals including state790.
state790 next depends on 13 signals including state2002 and state85 (clk counter).
Both depend on bus signals (i_wb_*) but in different sub-expressions.
No direct causal link: state1536=10 does not force state790 to any value.

### rsyn_001: `state1536=15 => state2002=1`

Counterexample: state1536=15, state2002=1 (both true — lemma passes on this CE
but fails on other transitions where state1536=15 & state2002=0)
Transition: state2002 dependency list includes state85, state1789, and address
matching logic. state1536=15 is reachable without state2002=1 via different
transition paths.

### rsyn_002: `!(state1536=15 && state2002=0)`

Same as rsyn_001 — state1536=15 and state2002=0 CAN co-occur.

## Transition-Aware Synthesis

Prompt included:
1. Transition summaries with dependency lists for all 5 target variables
2. Semantic notes about each variable's meaning
3. Known reachable samples
4. Failed lemma analysis with transition-based explanations

Result: 3 candidates, all pass reachable+nontrivial+init, all fail one-step.

## Conclusion

Transition context helps the LLM produce better-structured candidates
(novel `or` consequent pattern) but is insufficient for synthesizing
inductive lemmas. The LLM needs closed-loop solver feedback — after each
candidate proposal, run one-step check and feed back the counterexample
to refine the lemma, analogous to the qspiflash repair loop but for
synthesis rather than repair.
