# Notes

> Tacit knowledge an agent can't infer from reading code.

## Boolean Pair Hints — Scan Findings (2026-06-18) — ⚠️ NOT sound proofs

> ⚠️ **SOUNDNESS AUDIT (2026-06-19): these are NOT sound proofs.** `scripts/cert_check.py`
> (z3 certificate checker) re-verifies IC3IA's invariant on the *original* circuit (no hint
> constraint): **32/32 verifiable instances REJECT** (signature `C1=U C2=S C3=U`; 7 array
> unverifiable), including all 5 "STRONG NEW". Reason: a hint added as a BTOR2 `constraint`
> is an *assumption* → IC3IA returns `!BAD` (safe at init, implies ¬BAD, but not inductive
> on the original transition) = circular reasoning. Re-run `scripts/audit_proof_soundness.py`.
> **Even hint-as-lemma can NOT fix these** (2026-06-19 BMC check): `X&&Y` is reachable
> from init in 5/5 categories tested (frogs.5/gcd/sumt3/pals_floodmax/picorv32-pcregs-p0)
> → `!(X&&Y)` is a FALSE invariant in BTOR2 (bit-level doesn't preserve the RTL/DVE mutex),
> so any lemma form is dropped by IC3's push / rejected by check_intersects_initial. The
> signal-name mutex-hint method cannot yield sound proofs at the BTOR2 level. To be sound,
> work at an abstraction that preserves the mutex (RTL/DVE), or derive hints from the actual
> BTOR2 transition rather than signal names.

**Pattern**: Circuits where ALL standard engines (ind, interp, ic3ia) timeout, but adding a single boolean pair constraint `!(X && Y)` makes IC3IA report "unsat" in <10s — *under the assumed constraint*. Useful as an **acceleration map**, not as proofs.

**Count: 42 acceleration instances across 39 unique circuits** (after removing 4 confirmed false positives per competition CSV audit 2026-06-19). **0 are sound proofs.**
- 27 KNOWN UNSAT: competition proved them with other engines (circuit IS safe); hint only speeds pono's constrained "unsat"
- 5 "STRONG NEW": all competition tools timed out at 3600s — but all REJECT in the soundness audit, so NOT claimable as new proofs
- 7 UNCERTAIN (array circuits): competition also failed; also unverifiable by cert_check (no array support)

**Six hint pattern categories:**

1. **BEEM one-hot FSM** (`!(state_A && state_B)` — mutually exclusive protocol states): brp2.2, frogs.5, msmie.3, rushhour.4, brp2.3, collision.1. Signal names like `a_idle`, `a_error`, `a_done` carry clear semantic mutex.

2. **Protocol state exclusion** (`!(dve_valid && nexta_s0)`, `!(a_r4 && a_r0)`): pgm_protocol.7 (2 props), pgm_protocol.8. Named transition variables expose next-state exclusion.

3. **RTL formal annotation** — three subtypes:
   - `!(CHECK && EN)` (same assertion): picorv32-check-p22, ponylink-slaveTXlen-unsat. BAD = `CHECK && EN`, hint is the pair itself.
   - **Cross-assertion pairs** (`!(EN_line1 && EN_line2)` or `!(EN && CHECK_other)`): picorv32-pcregs-p0/p2 (`!(EN_44$3 && EN_39$1)`), zipcpu-zipmmu-p14 (`!(EN_754$66 && CHECK_677$59)`), zipcpu-zipmmu-p26 (`!(CHECK_759$70 && o_cyc)`).
   - **f_past_valid pairs**: qspiflash (3 circuits), vgasim_imgfifo (5 circuits), zipversa-p03/p10. f_past_valid is almost always mutex with assertion-check signals at time 0.

4. **Wordlevel HLS handshake** (`!(v1_buf && v2_buf)`, `!(v1_buf && ap_enable...)`): counter, gcd, kalman circuits. Two output-valid buffers can't simultaneously fire; also: output-valid vs pipeline-enable stage flag.

5. **Reset/validity mutex** (`!(reset0 && valid)`): zero_sum_const4/5, standard_copy2_ground-2, ifeqn4f/5, s32if, flag_loopdep, array7_pattern, hard-ll_valuebound20, sumt3. Control signals that are structurally mutex but require arithmetic reasoning to prove invariant globally.

6. **One-hot mode encoding** (`!(valid && modeN)`): pals_lcr-var-start-time.5.1/6.1, pals_opt-floodmax.4. PALS protocol circuits where valid and a specific one-hot mode bit cannot both be set.

**LLM relevance**: ALL six patterns are LLM-natural — signal names (`error`, `idle`, `CHECK`, `EN`, `reset0`, `valid`, `f_past_valid`, `mode`) carry enough semantics for an LLM to suggest `!(A && B)`.

**CRITICAL: SAT-circuit false positive**: Adding `!(X && Y)` to a SAT circuit cuts off the real counterexample and gives spurious UNSAT. `-sat` suffix filter is insufficient — brp2.2.prop1 (2020 SAT, no `-sat` suffix), ifeqn4f (2024-array SAT, no `-sat` suffix) are confirmed false positives. Always cross-check with HWMCC competition CSV before claiming a proof. 4 confirmed false positives removed from final count: brp2.2.prop1, ifeqn4f, pals_lcr-var-start-time.5.1/.6.1.

**Scan methodology** (scripts/sweep2.py, `/tmp/extended_scan.py`):
- Phase 1 (bob6gka9i): exactly 2 named 1-bit state refs in BAD → test BAD×BAD pair → 18 accelerated (19 found, 1 false positive removed) — NOT sound proofs, see audit above
- Phase 2 (extended scan): 1-3 BAD refs, test BAD-ref × ALL named 1-bit states → 24 accelerated (27 found, 3 false positives removed) — NOT sound proofs
- Baseline: ind(6s) + interp(6s) both timeout
- Verify: ic3ia alone (without hint) also times out
- False positive guard: skip `-sat` suffix AND cross-check HWMCC competition CSVs for SAT status

## Gotchas

- **Never restore per-CTI blocking code.** Q2/Q3/Q4 all reached 0% accept rate: per-CTI reactive LLM querying is a dead abstraction. The replacement is BTOR2 constraint pre-processing.
- **Do not restore deleted files**: `ic3_frame_v1.txt`, `ab_q*` scripts, old harness_preprocess, old per-CTI prompt_format.
- **smt-switch uses shared_ptr everywhere.** Use `->` not `.` for solver/term accesses.
- **Reactive predicate injection does NOT work for arithmetic invariants**: IC3IA accepts arithmetic predicates (x+y==3*i) but still can't close proof — refinement adds bit-extraction predicates. Pre-processing is the only working approach.
- **BTOR2 sort IDs are line numbers, not bit widths.** When building BTOR2, always use `Btor2Builder.get_sort(width)` to get the correct sort line number.
- **pono exit codes**: TRUE=1 (safe, UNSAT), FALSE=0 (unsafe, SAT), UNKNOWN=-1 (shell 255), ERROR=2.
- **preprocess_sw.py output contract** (changed 2026-06-20): stdout = the ORIGINAL btor2 path (predicate injection never modifies it); stderr carries `PREDICATES=<json>` (and `FAST_ENGINE=<engine>`). Run: `BTOR=$(python3 scripts/preprocess_sw.py file.btor2 2>/tmp/sw.log)`, then `pono --initial-predicates "$(grep PREDICATES= /tmp/sw.log|sed 's/.*=//')" "$BTOR"`. LLM `[llm]` messages also go to stderr.
- **Quadratic equality `2*x==i*(i-1)` can never be verified standalone** — IC3IA times out. The inequality `2*x<=i*(i-1)` verifies in <0.1s with `i<=n` as helper. The ule fallback is auto-applied.
- **fib_30/fib_37 state names come from output labels** not state labels — `output 7 c` gives state7 the name 'c'. Now handled by `parse_btor2()`.
- **BTOR2 deps for uext/sext/slice do NOT include sort**: parser saves only `parts[3]` (the data expr). For all other ops, `deps[0]` is the sort. `_decode_expr()` handles this correctly.
- **hint-as-constraint is UNSOUND** (2026-06-19): adding `!(X&&Y)` as a BTOR2 `constraint` only proves the property *under that assumption* — circular. Verify any constraint-assisted "proof" with `scripts/cert_check.py` (re-checks IC3IA's `--show-invar` invariant on the original circuit via z3: C1 init, C2 inductive, C3 ⟹¬BAD). pono's own `--check-invar` is NOT enough — it checks against the constrained model. cert_check limits: no array sorts; handles negative-ref (bitwise-not) and input-bearing invariants (next-step inputs → fresh).
- **Candidate accumulation for reliability (2026-06-20)**: `scripts/predicate_workflow.py --rounds=K` runs the LLM K times and dedups all candidates by canonical JSON (predicate injection is sound, so extra/false candidates are harmless — no verify needed, cap=20 to avoid abstraction blow-up). Effect: improves reliability vs LLM nondeterminism (fib_23 rounds=1 3/5 unsat → rounds=3 4/5; sometimes finds a faster predicate combo, 3.1s vs 52s). Does NOT raise coverage (5/20 either way) — complex nonlinear circuits time out on `bvmul` SMT cost regardless of candidate count. **Accumulation is a reliability lever, not a coverage lever; the coverage ceiling is SMT (bvmul) cost, not candidate quality.** Not forced into the main pipeline (which already has verify + a conditional retry loop); it's a `predicate_workflow.py` option.
- **Two-tier / linear-first injection (2026-06-20)**: `predicate_workflow.py --two-tier` runs linear-only candidates first (no `var*var` → cheap SMT), falls back to full (with bvmul) on miss. Precise filter `_ast_has_var_mul` allows `mul(const,var)` coefficients (`3*i`, `2*sum`), blocks only `mul(var,var)`. Measured: **linear is far cheaper** — all sound circuits prove sub-second via tier1 vs fib_23's 52s quadratic. Rescues linear-solvable circuits that full-mode drowns in bvmul candidates (paper_v3 unknown→0.1s) and keeps `const*var` (93.c, killed by a coarse "block all mul" filter). Coverage 5–6/20 (fib_23 quadratic via tier2 is LLM-nondeterministic). Ceiling unchanged: genuine `var*var` circuits (egcd/lcm/prodbin/sqrt/fermat) still time out — linear is fast but can't express a quadratic invariant.
- **linear-only (miss=give up) vs two-tier — where the bottleneck really is (2026-06-20)**: `--linear` (precise filter, NO bvmul fallback) gives the SAME 5/20 as two-tier — the bvmul fallback rescues nothing (genuine `var*var` circuits time out either way). Speed: fib_23/30 give up in ~1s, BUT complex nonlinear (egcd/lcm/prodbin/fermat) still time out 70s — injecting linear predicates does NOT stop IC3IA's own refinement from chasing bvmul (interpolant), so "miss=give up" only truly gives up where IC3IA can't refine either; otherwise it still burns the timeout (真正秒級放棄需禁 IC3IA refinement, 另一個開關). **Key: with bvmul dropped, the coverage ceiling is "circuits that HAVE a linear inductive invariant" (math-fixed), NOT the LLM harness.** The 5 linear-solvable ones (paper_v3/93.c/fib_37/77.c/fib_05) are already all generated correctly; the misses are genuinely nonlinear (gcd/lcm/product/sqrt/fermat need `var*var`; fib_23/30 linear blocked by overflow), so harness improvement (better prompt / more rounds) has ~no room on this corpus. To raise coverage: change benchmark (more linear-solvable circuits) or tackle `var*var` at the SMT level.
- **Sound predicate injection — the FIX for hint-as-constraint (2026-06-20)**: inject LLM invariants as IC3IA abstraction PREDICATES (`pono --initial-predicates <json> <btor2>`), not model constraints. `add_predicate` never changes the model → sound regardless of hint truth (false hint = unhelpful, never a fake UNSAT; over-approximation vs constraint's under-approximation). The main pipeline (`preprocess_software_benchmark` / `scripts/preprocess_sw.py`) now does this: stdout = original btor2, stderr `PREDICATES=<json>` → run `pono --initial-predicates`. Gotchas: (1) predicate refs MUST be `state<lineno>`, not symbol names — `build_predicate_term` looks up ts terms by internal name; (2) `--show-invar` prints INVAR to **stderr** (capture `2>&1`); (3) no verify step needed (unlike constraints); (4) rebuild pono with `make pono-bin` (no `pono` target). Coverage: arithmetic 5/20 corpus sound, mostly sub-second (fib_23/30 ~60s = quadratic bvmul cost); mutex hints fail soundly (timeout, not fake UNSAT). Demo predicate file: `scripts/initial_predicates_fib23.example.json`.

## Decisions

- **Pre-processing over reactive injection**: Compute invariants BEFORE pono runs (not per-CTI). Inject them as IC3IA **predicates** (sound over-approximation, `--initial-predicates`); the earlier path injected them as BTOR2 constraints (unsound under-approximation — retired 2026-06-20, see roadmap B2).
- **Multi-round parallel verification**: Round-1 (4s timeout, parallel up to 4 workers) finds easy invariants. Round-2 with helpers finds complex ones. ThreadPoolExecutor over `subprocess.run` — each pono process is independent, safe to parallelize. Gives 25-57% speedup.
- **Retry loop with probe gate**: If no arithmetic invariants found AND `_has_accumulator_pattern()` detects a variable accumulating another sw var, retry LLM with explicit triangular-sum hint. Probe gate (`_is_proof_fast`, 3s timeout) skips retry when current constraints already prove the circuit (prevents wasted retry on fib_05 which is solved by sym_pair alone).
- **Python sidecar, not in-process**: LLM calls are async; out-of-process prevents blocking IC3's main loop.
- **Formula-rich transition sketch**: Show `c' = (i>=n ? c : c+i)` not `c' depends on states: i, n` — LLM needs the actual formula to infer triangular number invariants.
