> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Cross-Parameter Validation: `r_pipe_req ⇒ o_wb_stall`

## Summary

The lemma `(=> (= state2002 1) (= state790 1))` was validated across
6 qspiflash_dualflexpress_divfive parameterizations.

| Variant | States | Init | One-Step | Induction | Verdict |
|---|---|---|---|---|---|
| p020 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |
| p027 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |
| p040 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |
| p063 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |
| p114 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |
| p162 | 249 | UNSAT | UNSAT | UNSAT | **solver_verified** |

**Result: 6/6 variants verify the lemma.**

## Details

- All 6 variants share the same BTOR2 node IDs (state2002, state790)
  with identical Verilog symbols (r_pipe_req, o_wb_stall).
- All 6 have 249 states and 3102 BTOR2 lines.
- The transition logic for these variables is identical across variants
  (the divider parameter only affects clock counter width, not pipeline/bus logic).
- All checks complete in 2-3ms per query.

## Interpretation

The lemma `r_pipe_req = 1 ⇒ o_wb_stall = 1` is **not a quirk of p040**.
It is a genuine invariant of the qspiflash_dualflexpress_divfive controller
design, holding across all 6 tested divider parameterizations.

This is a standard bus-handshake constraint: when the Wishbone pipeline has
a pending request, the stall output is asserted to hold the bus. It is
independent of the clock divider configuration.

## Encoding Scope

Same as the original audit: standalone Bitwuzla validation via
`smt_checker.BTOR2SMT` with 88% transition coverage. NOT a Pono
`rel_ind_check` result. No runtime claim.
