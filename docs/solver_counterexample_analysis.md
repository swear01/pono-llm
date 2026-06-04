> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Solver Counterexample Analysis

## Summary

All 4 state-only candidates pass init (hold at reset) but fail one-step transition
checks. SAT counterexample models were extracted for all 8 checks (4 one-step +
4 induction). Each failure provides concrete evidence for the repair loop.

| Candidate | One-step | Induction | Failure Class | Repairability |
|---|---|---|---|---|
| C1: state1536=10=>state790=0 | SAT | SAT | overstrong_implication | medium |
| C2: state1536=0=>state1558=0 | SAT | SAT | overstrong_implication | medium |
| C3: state2002=1=>state1536=0 | SAT | SAT | overstrong_implication | medium |
| C4: !(state1536=10&&state79=1) | SAT | SAT | reachable_forbidden_mode | low/reject |

---

## Candidate Details

### Candidate 1: state1536=10 => state790=0

- **Init**: pass (both init to 0)
- **One-step**: SAT
- **Induction**: SAT
- **Failure class**: overstrong_implication

**Counterexample (one-step):**
| Field | Current | Next |
|---|---|---|
| state1536 (o_dspi_mod) | 0 | 10 |
| state790 (o_wb_stall) | 0 | 1 |
| i_reset | 0 | — |
| i_wb_*, i_cfg_stb | wb write active | — |

**Interpretation**: When o_dspi_mod transitions to 10, o_wb_stall transitions to 1
(stall active). The lemma says stall should be 0 at mode=10, but the system says
stall=1 at mode=10. The consequent is **wrong** — stall IS active in this mode.

**Suggested repair direction**:
- Reverse implication: `(=> (= state790 1) (= state1536 10))` (if stall, then mode=10)
- Weak consequent: `(=> (= state1536 10) (= state790 1))` (stall=1 when mode=10 — maybe true?)
- Add guard: add i_reset or other condition to limit when implication holds
- Schema change: could be a mode encoding constraint, not implication

### Candidate 2: state1536=0 => state1558=0

- **Init**: pass (both init to 0)
- **One-step**: SAT
- **Induction**: SAT
- **Failure class**: overstrong_implication

**Counterexample (one-step):**
| Field | Current | Next |
|---|---|---|
| state1536 (o_dspi_mod) | 0 | 0 |
| state1558 (cfg_speed) | 0 | 1 |
| i_cfg_stb | 0 | 1 (config strobe!) |

**Interpretation**: cfg_speed can become 1 even when mode stays at 0 (IDLE).
The config strobe (i_cfg_stb=1) triggers cfg_speed change while mode remains
0. This is an overstrong relation — cfg_speed is independently controlled.

**Suggested repair direction**:
- Add guard: `(=> (and (= state1536 0) (= i_cfg_stb 0)) (= state1558 0))`
  (cfg_speed only 0 when mode=0 AND no config strobe)
- Reject: if cfg_speed is truly independent, this lemma is misleading

### Candidate 3: state2002=1 => state1536=0

- **Init**: pass (both init to 0)
- **One-step**: SAT
- **Induction**: SAT
- **Failure class**: overstrong_implication

**Counterexample (one-step):**
| Field | Current | Next |
|---|---|---|
| state2002 (r_pipe_req) | 0 | 1 |
| state1536 (o_dspi_mod) | 0 | 15 |

**Interpretation**: When r_pipe_req becomes 1 (request active), mode transitions
to 15 (not 0). The lemma says mode should be 0, but mode becomes 15. The
consequent value is wrong — mode is NOT 0 when request is active.

**Suggested repair direction**:
- Reverse: `(=> (= state2002 1) (!= state1536 0))` (mode != 0 when request active)
- Mode range: `(=> (= state2002 1) (and (>= state1536 10) (<= state1536 15)))`
- Reject if correlation is coincidental

### Candidate 4: !(state1536=10 && state79=1)

- **Init**: pass (both init to 0)
- **One-step**: SAT
- **Induction**: SAT
- **Failure class**: reachable_forbidden_mode

**Counterexample (one-step):**
| Field | Current | Next |
|---|---|---|
| state1536 (o_dspi_mod) | 0 | 10 |
| state79 (cfg_mode) | 0 | 1 |
| i_cfg_stb | 0 | 1 |

**Interpretation**: Both mode=10 and cfg_mode=1 are reachable simultaneously via
a config strobe transition. This mutex is simply false in the real design.

**Suggested repair direction**:
- **Reject**: the two states CAN co-occur
- Could the relation hold with a different guard? Unlikely — both are independently
  settable via configuration

---

## Repair Prompt Notes

For candidates 1-3, the failure pattern is consistent: **antecedent holds but
consequent is wrong**. This is a "too strong" implication where the LLM guessed a
consequent value that doesn't match actual system behavior.

Candidate 4 is a reachable co-occurrence — the mutex is false. Best classified as `reject`.

All counterexamples come from the qspiflash_dualflexpress_divfive-p040 benchmark.
The variable Verilog symbols help ground the interpretation:
- state1536 = o_dspi_mod (DSPI mode register)
- state790 = o_wb_stall (Wishbone stall output)
- state1558 = cfg_speed (config speed setting)
- state2002 = OPT_PIPE_BLOCK.r_pipe_req (pipeline request flag)
- state79 = cfg_mode (config mode setting)
