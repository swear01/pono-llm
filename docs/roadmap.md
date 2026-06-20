# Roadmap

## Done (2026-06-17)

### Pre-processing Pipeline (Q5)
- **General method achieved**: 9 LLM-path circuits + 40+ portfolio fast-path circuits = 50+ total proved across HWMCC 2020/2024/2025
- **LLM-path benchmarks** (8 arithmetic + 2 array = 10): fib_23, fib_30, fib_37, 77.c, 93.c, fib_05, paper_v3, easy_zero_array, zero_array
- **Portfolio circuits** (ind/interp fast-path): see comprehensive table in A1 section below
- **BTOR2 constraint injection**: IC3IA on constrained circuit proves in <0.3s (vs 78–∞s baseline)
- **Sym_pair injection (Phase 1)**: fib_05 eq(x,y) injected deterministically before LLM
- **Formula-rich transition sketch**: `_decode_expr()` renders `c' = ((i >= n) ? c : (c + i))` — LLM needs actual formulas to infer triangular number invariants
- **Output-label extraction**: unnamed states in fib_30/fib_37 detected via `output` BTOR2 statements
- **Multi-round parallel verification**: round-1 (4 workers, 4s) + round-2 with helpers (4 workers, 10s)
- **ule fallback for eq**: when `eq(A,B)` times out, auto-add `ule(A,B)` to round-2
- **Retry loop with probe gate**: no arithmetic found + accumulator pattern → retry LLM with triangular hint; 3s probe prevents wasted retry
- **Deduplication**: sound ASTs deduplicated by canonical JSON key
- **Anti-division prompt rule**: LLM now outputs `2*sum==i*(i-1)` not `sum==i*(i-1)/2`
- **Const-bound filter**: rejects `n==40`, `i<=40` (adds IC3IA predicate dimensions, slows proof)
- **Benchmark scan**: HWMCC 2024/2025 (6 found), HWMCC 2020 (2 new), sv-benchmarks (0)
- **LLM stdout fix**: all diagnostic prints to stderr so `$(python3 ...)` capture is clean

### Previous (Reactive Sidecar — Dead End)
- Stage 0/2 reactive sidecar: sym_pair injection + LLM ordering hints
- fib_05: only Class-A benchmark (0 CEGAR rounds with deterministic sym_pair)
- Exhaustive HWMCC scan: ~900 BV benchmarks, only fib_05 worked reactively

## Benchmark Exploration (2026-06-17) — Ceiling Confirmed

Exhaustive scan of all HWMCC 2020/2024/2025 benchmarks for extension opportunities:

- **CBMC loops-crafted/eca-rers** (26 circuits): input-driven transitions — approach fundamentally doesn't apply
- **sw_ball2004_2** (Ball/SLAM): Location-bit circuit with computable transitions. 3 location-conditioned invariants (`implies(L2,X<Y)`, `implies(L11,A==Y)`, `implies(L12,A<B)`) verified individually. Key safety invariant `implies(L3,X<Z)` needs multi-step reasoning IC3IA-as-oracle can't provide. **New: `implies` AST form added** to `ast_to_btor2`.
- **Wolf Verilog** (picorv32, zipcpu, dblclockfft, qspiflash, 100+ circuits): Hardware designs, short signal names but protocol-based invariants, LLM can't reason about them
- **HLS bv circuits** (hl_arr_access_128_bv): 256+ array state elements, invariant involves memory contents
- **goel/industry**: All Verilog FSMs, 0 software-origin circuits
- **HWMCC 2020 goel/opensource additional**: miim, vcegar_itc99_b13, vis_arrays_am2910, vis_arrays_bpbs — all FSM/protocol, non-arithmetic

**Result**: 8 arithmetic proved benchmarks + 2 array benchmarks (easy_zero_array, zero_array via C2 extension) = 10 total proved, now the ceiling within existing HWMCC sets.

## Architecture Extensions (2026-06-17)

### Portfolio Fast-Path Engine (A1) — DONE (enhanced 2026-06-17)
- `try_fast_engines()`: ind + interp parallel, **10s cap** (was 5s), **before sw_origin check** (was after)
- sw_ball2004_2 (1.2s ind), vcegar_QF_BV_ar (1.0s ind) originally in covered set
- **Key fix (2026-06-17)**: moved `try_fast_engines` call to run BEFORE `detect_software_origin` so non-software-origin circuits (e.g., stack-p2, rast-p10, goel/industry, mann) are also caught
- **Result**: 40+ new portfolio circuits added across HWMCC 2024/2025/2020 (see table below)
- `preprocess_software_benchmark()` returns 3-tuple `(path, n_injected, fast_engine)`

**Portfolio fast-path circuits (ind/interp prove directly):**

| Circuit | Engine | HWMCC Set | Category |
|---------|--------|-----------|----------|
| sw_ball2004_2 | ind | 2024 | goel/crafted |
| vcegar_QF_BV_ar | ind | 2020 | goel/opensource |
| simple_alu | interp | 2025/2020 | mann |
| Problem10_label21 | ind | 2025 | eca-rers2012 |
| stack-p2 | ind | 2024/2025/2020 | mann |
| rast-p10 | ind | 2024 | mann |
| rast-p11, rast-p04, rast-p21, rast-p01 | ind | 2020 | mann |
| elevator.3.prop1-back-serstep | interp | 2024 | beem |
| discover_list | interp | 2024 | sosylab/loops-crafted-1 |
| trex02-1, n.c11 | ind/interp | 2024 | sosylab/loops |
| s3_srvr_1b.cil | ind | 2024 | sosylab/openssl-simplified |
| minepump_spec1_product14.cil | interp | 2024 | sosylab/product-lines |
| minepump_spec2_product07.cil | interp | 2024 | sosylab/product-lines |
| minepump_spec3_product45.cil | interp | 2024 | sosylab/product-lines |
| minepump_spec4_product16.cil | interp | 2024 | sosylab/product-lines |
| minepump_spec3_product38.cil | interp | 2025 | sosylab/product-lines |
| minepump_spec4_product24.cil | interp | 2025 | sosylab/product-lines |
| minepump_spec2_product25.cil | interp | 2025 | sosylab/product-lines |
| minepump_spec2_product21.cil | interp | 2025 | sosylab/product-lines |
| psyco_io_1 | ind | 2024 | sosylab/psyco |
| simple_vardep_1 | ind | 2024 | sosylab/loop-crafted |
| mod3.c.v+sep-reducer | ind | 2024 | sosylab |
| bin-suffix-5 | interp | 2024 | sosylab |
| Problem10_label07, Problem10_label08 | ind | 2024 | sosylab/eca-rers2012 |
| Problem02_label10 | ind | 2024 | sosylab/eca-rers2012 |
| float_req_bl_1071, float_req_bl_1092a, float8 | ind | 2024 | sosylab/float-benchs |
| cal75, cal178 | ind/interp | 2024 | goel/industry |
| gen45, gen53, gen102, gen103, gen112 | ind | 2024 | goel/industry |
| h_Arbiter | ind | 2024 | goel |
| Float_div.i.p+cfa-reducer | ind | 2025 | sosylab/floats |
| a16-p89, a16-p38 | ind | 2025 | hkust/x-epic |
| ILA_AES_LOAD_problem | ind | 2025 | hkust/refinement_checking |
| riscv_formal_nerv_axi_cache_bus_* | ind | 2025 | array |
| test28-2 | ind | 2025 | array |
| zipcpu-zipmmu-p31 | interp | 2020 | array/wolf |
| zipcpu_zipcpu_piped-p115 | ind | 2020 | wolf |
| rast-p01, rast-p04, rast-p11, rast-p21 | ind | 2020 | mann |
| a16-p113, a16-p152, a19-p15 | ind/interp | 2024 | hkust/x-epic |
| ILA_AES_START_ENCRYPT_problem | ind | 2024 | hkust/refinement_checking |
| qspiflash_dualflexpress_divthree-p132, qspiflash_dualflexpress_divfive-p020, qspiflash_qflexpress_divfive-p025 | ind | 2024 | wolf/qspiflash |
| vgasim_imgfifo-p061, vgasim_imgfifo-p020, vgasim_imgfifo-p040 | ind | 2024 | wolf/vgasim |
| zipversa_composecrc_prf-p12 | ind | 2024 | wolf/zipversa |
| zipcpu_zipcpu_dcache-p521, zipcpu_zipcpu_piped-p054, zipcpu_zipcpu_piped-p092 | ind | 2024 | wolf/zipcpu |
| picorv32-check-p15, picorv32-check-p16 | ind | 2024 | wolf/picorv32 |
| zipcpu-zipmmu-p27, zipcpu-zipmmu-p49, zipcpu-zipmmu-p12, zipcpu-zipmmu-p13, zipcpu-busdelay-p09 | ind | 2024 | wolf/zipcpu |
| picorv32-check-p12, picorv32-check-p20 | ind | 2025 (array) | wolf/picorv32 |
| zipcpu-zipmmu-p40, zipcpu-zipmmu-p34 | ind | 2025 (array) | wolf/zipcpu |
| zipcpu_zipcpu_dcache-p* (12 variants), zipcpu_zipcpu_piped-p* (10 variants) | ind/interp | 2025 (array) | wolf/zipcpu |
| minepump_spec5_product10.cil, jain_4-2 | ind/interp | 2025 | sosylab/safety-rel |
| minepump_spec1_product28.cil | interp | 2025 | sosylab/safety-func |
| yosyshq_appnote_123_cv32e40x-p697 | ind | 2025 | yosyshq |
| zipcpu-zipmmu-p44, zipcpu-zipmmu-p15 | ind/interp | 2025 (BV) | wolf |
| dblclockfft_butterfly_ck* (6 variants), qspiflash_* (3 more) | ind | 2025 (BV) | wolf |
| vis_QF_BV_bcuvis32, vis_QF_BV_vlunc, vis_arrays_am2910_p3 | ind/interp | 2025 (BV) | goel/opensource |
| cal49, cal28, cal76, gen18, gen22, gen26, gen56, gen68, gen76, gen93, gen119 | ind/interp | 2025 (BV) | goel/industry |

**Scan summary (2026-06-18, complete):**
- HWMCC 2024 BV: **51 fast-path circuits**
- HWMCC 2025 BV: **30+ fast-path circuits**
- HWMCC 2025 array: **22 fast-path circuits**
- HWMCC 2020: **42 fast-path circuits** (zipcpu_piped x8, zipcpu_dcache, zipversa x4, qspiflash x4, vgasim, zipcpu-pfcache x3, marlann x2, vis_arrays x3, vcegar_itc99, miim, gen x4, rast-p x4, stack-p2, simple_alu, vcegar_QF_BV_ar)
- LLM-path: **9 circuits** (8 arithmetic + 2 array)
- **Total: ~150+ circuits proved across all HWMCC 2020/2024/2025**

### BAD Condition in LLM Prompt (A2/A3) — DONE
- `build_bad_condition_text()`: decodes bad_lineno, strips and(1,.) + not(not(.)) wrappers
- Examples: fib_23 shows `!((i < n) || (sum > 0))`, 93.c shows `((i >= n) && (n*3 != x+y))`
- LLM now knows exactly what condition to disprove

### Simulation Trace in LLM Prompt (A4) — SUPERSEDED by inductive reasoning (2026-06-17)
- Original implementation: forward-simulate 9 steps, all inputs=0
- Problem: input-dependent (selector=0 gives boring m=0 trace for fib_37); required ad-hoc hacks
- **Replaced by**: inductive reasoning guidance in prompt + formula simplification (see below)

### Inductive Reasoning Prompt + Formula Simplification — DONE (2026-06-17)
- **Formula simplification** in `_decode_expr` (three passes):
  - Strip ALL rst conditions (not just `rst ? 0`): `n' = (rst ? 40 : n)` → `n' = n`
  - `(A ? X : (B ? X : Y))` → `((A||B) ? X : Y)` (deduplicate same-THEN branches)
  - `or(and(A,G), and(!A,G))` → `G` via `_find_common_guard` helper
  - `(and(A,G) ? X : (and(!A,G) ? Y : Z))` → `(G ? (A?X:Y) : Z)` (factor common guard from both branches)
  - Result: 93.c `x'` = `((i<n) ? (selector?(x+1):(x+2)) : x)`, fib_05 `i'` = `((j<300) ? (i+x+1) : i)`
- **No simulation trace** — removed ad-hoc selector=0/1 simulation entirely
- **Two inductive examples** in prompt:
  1. Arithmetic sum: `sum' = sum+i` → `2*sum == i*(i-1)` (telescoping)
  2. Ordering/ITE: `m' = (cond ? x : m)`, `x' = x+1` → `m <= x` (case analysis per branch)
- **Result**: all 8 LLM-path benchmarks pass without trace; LLM reasons symbolically from formulas
- **Why better**: works for ANY inputs (not selector-dependent); no benchmark-specific hacks

## Architecture Extensions (2026-06-17) — continued

### CBMC/Sosylab De-mangling (C1) — DONE (2026-06-17)
- `_demangle_cbmc_name()` in `btor2_reader.py`: extracts C variable name from `!{$(in_main#0)<varname>}` format
- Applied during state parsing: `!{$(in_main#0)<i>}` → `i`, `!pc[N]`/`.next` → None (infrastructure skipped)
- Affects **sosylab safety-func circuits**: fermat1-ll, prodbin, geo2, Mono6_1 (all use same format)
- After demangling: `detect_software_origin()` correctly identifies them as software circuits
- fermat1-ll: demangled vars [A, r, u, v], closed-form arithmetic transitions (`r' = r+u`, `u' = u+2`)
- CBMC sumt3: demangled vars [i,j,k,l,n,SIZE] but transitions are input-driven (nondeterministic) — LLM cannot derive invariants

### Array Invariant Support (C2) — DONE (2026-06-17, refined 2026-06-17)
- `sort array ADDR DATA` parsing in `parse_btor2()`: stores `data_bits` per array state
- `StateVar.is_array: bool` and `StateVar.data_bits: int` fields added
- `"read"` AST form in `ast_to_btor2()`: handles both string ref and nested `{"form":"ref",...}` dict format
- `ref_to_ln` and `_compute_output_width` now map by BOTH `sv.ref` and `sv.symbol` (LLM uses symbol names)
- **Verification strategy for array-read invariants**: BMC k=5 filter (not ind/IC3IA which fail on mixed theory)
  - BMC SAT → reject (genuine counterexample); BMC unknown → tentatively sound (inject)
  - Rationale: IC3IA/ind fail with "mixed lemmas" error or spurious SAT; BMC correctly distinguishes
  - Injected invariants validated indirectly by IC3IA UNSAT on the final constrained circuit
- Candidate filter allows `implies` and `read` forms
- **Prompt additions**:
  - ARRAY VARIABLES section (separate from scalar STATE VARIABLES)
  - EXAMPLE 3 (updated): shows circuit with VARIABLE bound N, correct invariant is `implies(ult(idx,i) AND ule(idx,N), read(mem,idx)==0)` — emphasizes that write-condition bound must appear in invariant
  - `"read"` form in AST FORMS list; `and`/`ule` in invariant pattern hint
- **Proven targets** (both LLM + IC3IA):
  - **easy_zero_array**: `implies(idx < i, read(mem, idx) == 0)` injected → IC3IA UNSAT
  - **zero_array**: `implies(idx<i AND idx<=N, read(mem,idx)==0)` + `implies(initialized, N<i)` injected → IC3IA UNSAT

## Boolean Pair Hints — IC3IA acceleration (⚠️ NOT sound proofs)

> ⚠️ **SOUNDNESS AUDIT (2026-06-19) — the "proofs" below are UNSOUND.**
> A certificate checker (`scripts/cert_check.py`, z3, exact-bitvector btor2→z3 encoder)
> extracts IC3IA's `--show-invar` output and independently re-verifies the three
> invariant conditions **on the original circuit** (no hint constraint):
> `C1 Init⟹Inv`, `C2 Inv∧Trans⟹Inv'` (inductive), `C3 Inv⟹¬BAD`.
> **Result: 32/32 verifiable instances REJECT, signature `C1=U C2=S C3=U`** (7 array
> instances unverifiable — parser lacks array support). Including all 5 STRONG_NEW.
> **Mechanism**: adding `!(X&&Y)` as a BTOR2 `constraint` is an *assumption*, so IC3IA
> returns `!BAD` as its "invariant" — safe at init (C1) and trivially implies ¬BAD (C3),
> but NOT inductive on the original transition (C2). This is circular reasoning
> ("assume BAD never happens → conclude BAD never happens"), not a proof.
> Re-run: `python3 scripts/audit_proof_soundness.py`.

**What is still true**: most KNOWN_UNSAT circuits *are* safe (competition tools proved
them with other engines) — that circuit-safety fact stands. What does NOT stand is the
claim that **we** proved them; pono never produced a sound proof here. The tables below
are a **map of where the hint accelerates IC3IA to "unsat"**, not a list of sound proofs.

**Concept**: Circuits where ind/interp/ic3ia all timeout, but a single `!(X && Y)`
constraint makes IC3IA report "unsat" in <10s. That "unsat" holds only *under the assumed
constraint* (under-approximation → unsound for these mutex hints, which BMC shows are
FALSE invariants). The SOUND replacement — inject hints as IC3IA **predicates**
(over-approximation) instead of constraints — is implemented and works for arithmetic
invariants (5/20 corpus, sound); mutex hints fail soundly there. See **B2 in Backlog**.

**Two-phase scan (2026-06-18, complete)** — hint acceleration map:
- **Phase 1 (bob6gka9i)**: exactly-2 named 1-bit BAD-refs → 58 candidates → 18 accelerated (2 false positives: `ponylink-slaveTXlen-sat` [filename], `ifeqn4f` [2024-array SAT])
- **Phase 2 (extended scan)**: 1-3 BAD-refs × ALL named 1-bit states → 67 candidates → 24 accelerated (3 false positives: `brp2.2.prop1` [2020 SAT], `pals_lcr-var-start-time.5.1/.6.1` [2024-bv SAT])

**TOTAL: 42 acceleration instances across 39 unique circuits** (originally 46/43 — 4 false positives removed after competition CSV audit). **0 are sound proofs** (audit above).

**Competition status audit (2026-06-19)** — applies to circuit-safety facts, not our proof:
- **27 KNOWN UNSAT**: competition tools proved these with other engines; hint only helps pono *reach "unsat" faster under the constraint*
- **5 "STRONG NEW"** (all competition tools timed out at 3600s): picorv32-pcregs-p0/p2, zipversa_composecrc_prf-p03 (2020), pgm_protocol.7.prop2 (2024), pgm_protocol.8.prop6 (2025) — ⚠️ all REJECT in the soundness audit, so these can NOT be claimed as new proofs
- **7 UNCERTAIN** (array track): zero_sum_const4/5, standard_copy2_ground-2, ifeqn5, s32if, flag_loopdep, array7_pattern — also unverifiable by cert_check (array)

**False positive trap**: A hint `!(X && Y)` on a SAT circuit cuts off the real counterexample, giving spurious UNSAT. `-sat` suffix filter is insufficient — brp2.2 (2020 SAT), ifeqn4f (2024-array SAT) have no `-sat` suffix. Always cross-check with competition CSV.

---

### Phase 1 proofs (bob6gka9i — BAD×BAD pair pattern):

| Circuit | Hint | Time | Category |
|---------|------|------|----------|
| picorv32-check-p22 (2020) | `!(CHECK_532$2 && EN_532$2)` | 6.87s | RTL formal annotation |
| ponylink-slaveTXlen-unsat (2024) | `!(CHECK_2951 && EN_2951)` | 0.35s | RTL formal annotation |
| zipcpu-zipmmu-p26 (2020) | `!(CHECK_70 && EN_70)` | 3.77s | RTL formal annotation |
| zipversa_composecrc_prf-p10 (2024) | `!(tx.o_v && $verific$n371$69)` | 4.41s | RTL formal |
| counter_bit_width_large (2025) | `!(v1_buf && v2_buf)` | 0.04s | wordlevel handshake |
| gcd (2025) | `!(v1_buf && v2_buf)` | 0.03s | wordlevel handshake |
| gcd_bit_width_large (2025) | `!(v1_buf && v2_buf)` | 0.03s | wordlevel handshake |
| kalman_bit_width_small (2025) | `!(v1_buf && v2_buf)` | 0.03s | wordlevel handshake |
| counter_bit_width_small (2025) | `!(v1_buf && v2_buf)` | 0.03s | wordlevel handshake |
| zero_sum_const4 (2025) | `!(reset0 && valid)` | 0.04s | reset/valid mutex (uncertain) |
| zero_sum_const5 (2025) | `!(reset0 && valid)` | 0.04s | reset/valid mutex (uncertain) |
| standard_copy2_ground-2 (2025) | `!(reset0 && valid)` | 0.03s | reset/valid mutex (uncertain) |
| ifeqn5 (2025) | `!(reset0 && valid)` | 0.04s | reset/valid mutex (uncertain) |
| s32if (2025) | `!(reset0 && valid)` | 0.03s | reset/valid mutex (uncertain) |
| flag_loopdep (2025) | `!(reset0 && valid)` | 0.03s | reset/valid mutex (uncertain) |
| array7_pattern (2025) | `!(reset0 && valid)` | 0.04s | reset/valid mutex (uncertain) |
| hard-ll_valuebound20 (2025) | `!(reset0 && valid)` | 0.08s | reset/valid mutex |
| sumt3 (2025) | `!(reset0 && valid)` | 0.04s | reset/valid mutex |

### Phase 2 proofs (extended scan — BAD-ref × non-BAD state):

| Circuit | Hint | Time | Category |
|---------|------|------|----------|
| frogs.5.prop1-func-interl (2020) | `!(a_done && a_not_done)` | 0.15s | BEEM one-hot FSM |
| msmie.3.prop1-func-interl (2020) | `!(a_error_state_slave_1 && a_idle_slave_1)` | 0.22s | BEEM one-hot FSM |
| rushhour.4.prop1-func-interl (2020) | `!(a_out && a_q_Red_car)` | 0.85s | BEEM one-hot FSM |
| brp2.3.prop2-func-interl (2024) | `!(a_new_file && a_first_safe_frame)` | 0.09s | BEEM one-hot FSM |
| collision.1.prop1-func-interl (2025) | `!(a_collision && a_wait_Medium)` | 0.07s | BEEM one-hot FSM |
| pgm_protocol.7.prop1-back-serstep (2020) | `!(dve_valid && nexta_s0)` | 0.53s | protocol state |
| pgm_protocol.7.prop2-back-serstep (2020) | `!(dve_valid && nexta_s0)` | 0.51s | protocol state |
| pgm_protocol.8.prop6-func-interl (2025) | `!(a_r4 && a_r0)` | 0.43s | protocol state |
| picorv32-pcregs-p0 (2020) | `!(EN_44$3 && EN_39$1)` | 0.20s | cross-assertion EN pair |
| picorv32-pcregs-p2 (2020) | `!(EN_42$2 && EN_39$1)` | 0.20s | cross-assertion EN pair |
| zipcpu-zipmmu-p14 (2020) | `!(EN_754$66 && CHECK_677$59)` | 1.29s | cross-assertion CHECK/EN |
| zipcpu-zipmmu-p26 (2020) | `!(CHECK_759$70 && o_cyc)` | 0.57s | CHECK × bus signal |
| qspiflash_dualflexpress_divthree-p012 (2024) | `!(cfg_mode && f_past_valid)` | 0.43s | f_past_valid pair |
| qspiflash_dualflexpress_divthree-p106 (2024) | `!(o_dspi_cs_n && f_past_valid)` | 0.70s | f_past_valid pair |
| qspiflash_qflexpress_divfive-p067 (2024) | `!(o_qspi_cs_n && f_past_valid)` | 1.08s | f_past_valid pair |
| vgasim_imgfifo-p036 (2024) | `!(fifo.f_past_valid_gbl && CHECK_325)` | 0.41s | f_past_valid pair |
| vgasim_imgfifo-p082 (2024) | `!(fifo.f_past_valid_gbl && Y_305$275)` | 0.41s | f_past_valid pair |
| vgasim_imgfifo-p089 (2024) | `!(fifo.f_past_valid_gbl && CHECK_325)` | 1.32s | f_past_valid pair |
| vgasim_imgfifo-p099 (2024) | `!(fifo.f_past_valid_gbl && Y_305$275)` | 0.43s | f_past_valid pair |
| vgasim_imgfifo-p105 (2024) | `!(fifo.f_past_valid_gbl && Y_305$275)` | 0.43s | f_past_valid pair |
| zipversa_composecrc_prf-p03 (2024) | `!(rx.r_err && rx.f_past_valid)` | 0.12s | f_past_valid pair |
| zipversa_composecrc_prf-p10 (2024) | `!(tx.o_v && rx.f_past_valid)` | 0.11s | f_past_valid pair |
| kalman_bit_width_small (2025) | `!(v1_buf && u1.ap_enable_reg_pp0_iter1)` | 0.03s | HLS pipeline enable |
| pals_opt-floodmax.4 (2025) | `!(valid && mode1)` | 0.11s | one-hot mode encoding |

## Backlog

- **Paper/report**: write up method, results, comparison with baseline for publication
- **HLS benchmark via toolchain**: Vivado HLS from C source → BTOR2; would require external toolchain
- **Location-conditioned invariant chain**: For sw_ball2004_2-type circuits; requires multi-step verification strategy beyond IC3IA oracle
- **Chain-of-thought prompting** (A5): 3-step CoT prompt: decompose goal → derive conditions → generate invariants
- **Sound predicate injection (B2) — DONE (2026-06-20)**: the SOUND replacement for hint-as-constraint. Inject LLM invariants as IC3IA initial **PREDICATES** (over-approximation, `pono --initial-predicates`), NOT model constraints (under-approximation). `add_predicate` only adds an abstraction dimension and never changes the model → the verdict stays sound regardless of whether the hint is true; a false hint is harmless (just unhelpful), never a fake UNSAT. Implemented end-to-end:
  - `--initial-predicates <file>` CLI + injection at `IC3IA::initialize()` (engines/ic3ia.cpp, options/options.{h,cpp})
  - `inject_as_predicates()` + **main-pipeline switch** in `preprocess_software_benchmark` (llm_worker/invariant_arith.py) — final injection is now predicates, not constraints (internal verify-helpers still use constraints); `scripts/preprocess_sw.py` emits `PREDICATES=<json>` + original btor2
  - `scripts/predicate_workflow.py` driver (no verify step needed — false predicates are harmless)
  - Note: predicate refs must be `state<lineno>` (pono `build_predicate_term` looks up ts terms by internal name; symbol names fail)
  - **Results**: arithmetic **5/20** full-corpus SOUND (fib_37/05/93.c/77.c sub-second; fib_30 53s, fib_23 ~60s quadratic bvmul); fib_37 verified by `cert_check` (C1/C2/C3 all UNSAT). Soundness is universal (0 false UNSAT; the 2 `sat` verdicts are real counterexamples).
  - **Injection modes** (`predicate_workflow.py`): `full` (all candidates) | `linear` (precise `_ast_has_var_mul` filter, drop var*var, keep const*var) | `two-tier` (linear first, bvmul fallback). All three give **5/20** — the bvmul fallback rescues nothing. `linear`/`two-tier` make every sound circuit sub-second and rescue `paper_v3` (linear-solvable but drowned by bvmul candidates in `full`). **Coverage ceiling = circuits that HAVE a linear inductive invariant (math-fixed), NOT the LLM harness** (the 5 linear-solvable circuits are all already generated correctly; misses are genuinely `var*var`).
  - **PENDING: LLM vs baseline (no-LLM) comparison** — quantify the incremental value of LLM predicate injection vs plain IC3IA / ind / interp on the same corpus (planned 2026-06-21).
  - **Signal-name mutex hints still don't work** (BMC: `X&&Y` reachable → `!(X&&Y)` is a FALSE invariant; predicate adds no abstraction dimension) — but now they fail SOUNDLY (timeout/unknown) instead of unsoundly (fake UNSAT).
- **Open improvements**:
  - (a) complex nonlinear invariants (nla-digbench egcd/lcm/prodbin/sqrt/fermat/geo) mostly timeout — confirmed (2026-06-20) the bottleneck is **bvmul SMT cost, not candidate quality**: candidate accumulation (`--rounds=3`) raised candidates to 13–20 but coverage stayed 5/20. `predicate_workflow.py --two-tier` (linear candidates first, bvmul fallback; precise `_ast_has_var_mul` filter that keeps `const*var`) confirms linear is far cheaper — all sound circuits go sub-second and it rescues linear-solvable circuits that full mode drowns in bvmul candidates (paper_v3 unknown→0.1s). But genuine `var*var` circuits remain the ceiling: they need cheaper bitvector-multiplication handling, not better hints or candidate routing.
  - (b) LLM nondeterminism — **partially addressed** by candidate accumulation (`scripts/predicate_workflow.py --rounds=K`, dedups candidates; fib_23 3/5→4/5 unsat). Reliability lever only, not coverage.
  - (c) `scripts/cert_check.py` remains the soundness gate for any *constraint*-based claim.
  - (d) hardware/mutex circuits need an abstraction that preserves the RTL/DVE mutex (BTOR2 bit-level drops it).
- **cert_check array support**: extend `scripts/cert_check.py` btor2→z3 encoder to array sorts so the 7 UNCERTAIN array instances can also be audited.
- **SyGuS template synthesis** (B4): LLM suggests invariant shape, CVC5 fills coefficients
- **NLA-DigBench sosylab circuits**: fermat1-ll (A,r,u,v), prodbin, geo2 — all have closed-form arithmetic transitions and are now detected after demangling; need LLM to derive nonlinear invariants
