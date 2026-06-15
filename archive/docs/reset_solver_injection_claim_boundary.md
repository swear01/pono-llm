> Archived: 2026-06-15
> Reason: Path 1 per-CTI lemma injection abandoned (0% accept across Q2/Q3/Q4); superseded by Stage 0/2 semantic invariant injection
> Replacement: docs/plans/semantic_invariant_injection_v1_plan.md
> Status: historical only; do not use as active truth.

> **HISTORICAL / RESEARCH RECORD (2026-06-03)** — Not the active runtime integration path. Legacy code **will be deleted** with IC3 Frame v1. See [`ic3_frame_v1_integration.md`](ic3_frame_v1_integration.md) and [`DOC_INDEX.md`](DOC_INDEX.md).

# Reset-Solver Injection Claim Boundary

## Safe Claims (Supported by Data)

1. **Dynamic loader works**: Lemma text files are loaded and logged at reset_solver().
2. **Injection is opt-in**: No behavior change without `PONO_LLM_ASSERT_LIFTED_LEMMAS=1`.
3. **Lifted lemmas are solver-verified**: 26/30 pass offline Bitwuzla (init, step, induction).
4. **Cross-variant validation**: 15/15 lifted lemmas pass on p020-p063.
5. **Top-ranked lemmas identified**: Scoring by #pairs, state15-consequent priority, variable frequency.

## Claims NOT Supported (Must NOT Be Made)

1. **No runtime speedup**: Runtime is within noise (181s vs 191s). Repeated runs show pono runtime varies 5-8 minutes at k=5 regardless of injection.
2. **No benchmark unlock**: qspiflash p040 was not proved (IC3IA returns "unknown").
3. **No artifact reduction proven**: Baseline counts vary 779-1175 CTIs between identical runs. The observed -31.8% reduction was not reproducible — runs show +2.8% increase in the most recent test.
4. **No full Pono integration**: Injection is a research prototype, not a production feature.

## Why Artifact Reduction Is Unreliable

IC3IA at k=5 is intrinsically nondeterministic:
- Run 1: 935 CTIs, 1934 frames
- Run 2: 1175 CTIs, 2936 frames
- Run 3: 779 CTIs, 1271 frames

A claimed -31.8% reduction (1175→801) could be entirely within the random
variation of IC3IA's search path. The same config showed +2.8% increase
(779→801) in a later run.

## Required for a Real Claim

1. **5-10 repeated runs** per configuration with mean/median/stdev artifact counts.
2. **Fixed random seed** if possible.
3. **Higher-bound testing** (k=10+) where IC3IA explores more thoroughly.
4. **Statistical test** (t-test or Mann-Whitney) to distinguish signal from noise.
5. **Convergence measurement**: does injection help IC3IA reach higher k or prove the property?
