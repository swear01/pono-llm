> **ACTIVE for v1 (2026-06-03)** — Symbol shortlist / Verilog mapping notes for harness Layer 2.  
> Spec: [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md)

# Mapping Spike for Solver-Validation Shortlist

## Summary

| Candidate | Mapping Status | Reason |
|---|---|---|
| 1: `state1536=10 => state790=0` | mapping_partial | All vars identified; init checks work; transitions failed to translate |
| 2: `state1536=0 => state1558=0` | mapping_partial | All vars identified; init checks work; transitions failed to translate |
| 3: `state2002=1 => state1536=0` | mapping_partial | All vars identified; init checks work; transitions failed to translate |
| 4: `!(state1536=10 && state79=1)` | mapping_partial | All vars identified; init checks work; transitions failed to translate |
| 5: `state1536=11 => i_wb_data[12]=1` | mapping_partial | Input var mapped; bit extraction unsupported |

**BTOR2 source**: `~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/qspiflash_dualflexpress_divfive-p040.btor2` (3102 lines, 249 states, 11 inputs)

**Key finding**: `stateNN` names ARE BTOR2 node IDs. `state1536` = BTOR2 line 1536. This mapping is deterministic and works for ALL state variables in any BTOR2 file.

## Candidate 1: state1536=10 => state790=0

### Variable Mapping

| Variable | Found? | Bitwidth | Kind | Verilog Symbol | Init | Current Expr | Next Expr | BTOR2 Node | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| state1536 | yes | 4 | state | `o_dspi_mod` | 0 | state1536 | L2968 (complex ite) | 1536 | high |
| state790 | yes | 1 | state | `o_wb_stall` | 1 | state790 | L2676 (complex ite) | 790 | high |

### Query Feasibility

| Query | Feasible? | Reason |
|---|---|---|
| Init check | feasible | Both vars have known init values (state1536=0, state790=1) |
| One-step check | blocked | Next-state expressions for both vars fail Python BTOR2-to-SMT translation |
| Self-induction | blocked | Same as one-step |

### Conclusion
Mapping success for variable identification and init check. Transition-level queries blocked by incomplete Python BTOR2 opcode support (slice/uext with out-of-range indices).

## Candidate 2: state1536=0 => state1558=0

### Variable Mapping

| Variable | Found? | Bitwidth | Kind | Verilog Symbol | Init | Current Expr | Next Expr | BTOR2 Node | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| state1536 | yes | 4 | state | `o_dspi_mod` | 0 | state1536 | L2968 | 1536 | high |
| state1558 | yes | 1 | state | `cfg_speed` | 0 | state1558 | L2970 | 1558 | high |

### Query Feasibility

Same as Candidate 1: init feasible, one-step/induction blocked.

## Candidate 3: state2002=1 => state1536=0

### Variable Mapping

| Variable | Found? | Bitwidth | Kind | Verilog Symbol | Init | Current Expr | Next Expr | BTOR2 Node | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| state2002 | yes | 1 | state | `OPT_PIPE_BLOCK.r_pipe_req` | 0 | state2002 | L3213 | 2002 | high |
| state1536 | yes | 4 | state | `o_dspi_mod` | 0 | state1536 | L2968 | 1536 | high |

### Query Feasibility

Same as Candidate 1.

## Candidate 4: !(state1536=10 && state79=1)

### Variable Mapping

| Variable | Found? | Bitwidth | Kind | Verilog Symbol | Init | Current Expr | Next Expr | BTOR2 Node | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| state1536 | yes | 4 | state | `o_dspi_mod` | 0 | state1536 | L2968 | 1536 | high |
| state79 | yes | 1 | state | `cfg_mode` | 0 | state79 | L2172 | 79 | high |

### Query Feasibility

Same as Candidate 1.

## Candidate 5: state1536=11 => i_wb_data[12]=1

### Variable Mapping

| Variable | Found? | Bitwidth | Kind | Verilog Symbol | Init | Current Expr | Next Expr | BTOR2 Node | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| state1536 | yes | 4 | state | `o_dspi_mod` | 0 | state1536 | L2968 | 1536 | high |
| i_wb_data | yes | 10 | input | `i_wb_data` | N/A | i_wb_data | N/A | 11 | high |

### Query Feasibility

| Query | Feasible? | Reason |
|---|---|---|
| Init check | blocked | i_wb_data is a primary input — no init value. Lemma constrains input, may be invalid state invariant without environment assumptions. |
| One-step check | blocked | Same as Candidate 1 plus bit extraction (bit 12 from 10-bit input = out-of-range). |

### Concern

`i_wb_data` is a 10-bit primary input. The lemma extracts bit 12 (out of range) and encodes a guard on `state1536=11`. Without environment assumptions constraining `i_wb_data`, this is unlikely to be a valid state invariant.

## Root Cause: Transition Translation Failure

127 of 247 next-state lines (52%) fail Python BTOR2-to-SMT translation. All 5 target state transitions fail. Common issues:

1. **Out-of-range slice indices**: BTOR2 `slice` op references bits beyond source width (e.g., `slice 1 11 10 10` for a 10-bit input). The BTOR2 parser allows this syntactically but Python Bitwuzla's `BV_EXTRACT` rejects it.

2. **Sort mismatches**: `uext` and `concat` produce terms with widths that don't match expectations in the parent expression.

3. **Unsupported ops**: 25 BTOR2 operator types total; smt_checker.py now supports 18 (const, state, input, zero, ones, not, and, or, xor, xnor, eq, neq, ult, ulte, add, sub, srl, ite, slice, concat, redor, redand, uext). Still missing: `sll`, `sra`, `rol`, `ror`, `sext`, `inc`, `dec`, etc. (rare in qspiflash).

## smt_checker.py Fixes Applied

| Fix | Description |
|---|---|
| Init parsing | Changed `p[2] in state_sorts` to `f"state{p[2]}" in state_sorts` |
| Input width | Changed from hardcoded 1-bit to BTOR2-declared width |
| const value parsing | Handle binary `00` format via base-2 conversion |
| 12 new ops | slice, concat, redor, redand, xor, xnor, add, sub, ult, ulte, neq, srl |
| ite condition | Added `_as_bool()` helper to convert 1-bit BV→Boolean for ITE |
| Error tolerance | Transition constraints skip failed lines instead of bailing entirely |
| lemma_to_smt | Regex parser with width-aware constant creation for S-expression lemmas |
