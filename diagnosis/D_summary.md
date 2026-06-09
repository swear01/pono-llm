# Accept diagnosis summary

Archive: `bench_results/hwmcc_baseline_20260607/runs/20260609_032251_phase_a`

## D1 Funnel

- accept/request: **1.745%** (20/1146)
- accept/candidate: **2.008%**
- rejected_initial/request: **0.735**
- induction_fail/request: **0.105**

### By tier

| tier | cases | accept% | rejected_initial |
|------|-------|---------|------------------|
| ila | 35 | 1.0% | 156 |
| microban | 1 | 14.706% | 20 |
| other | 45 | 0.662% | 439 |
| qspiflash | 1 | 5.128% | 24 |
| riscv | 14 | 1.227% | 123 |
| zipcpu | 8 | 4.717% | 80 |

## D2 Positive vs contrast

- **S+ accept cases**: mean single-disjunct 74.5%, MIC top-1 shape 0.0%
- **S0 high-fail contrast**: mean single-disjunct 79.8%, MIC top-1 shape 0.0%
- **S* p040**: mean single-disjunct 85.4%, MIC top-1 shape 0.0%

## D3 Failure taxonomy (feedback)

- rejected_initial: **83.4%**
- induction_failed: **15.0%**
- empty_block_clause: **1.1%**
- vocab_fail: **0.3%**
- predicate_rejected: **0.1%**
- predicate_parse_fail: **0.1%**

## D3b Init semantics (rejected_initial detail)

- B2_single_witness_lit_false_at_witness: **64.6%**
- C2_multi_or_other_disjunct_at_init: **34.9%**
- B1_single_witness_lit_true_at_init: **0.5%**
- C1_multi_witness_lit_true_at_init: **0.1%**
- 34.9% — reduce OR width; max_block_clauses=1; single disjunct from digest top-1
- 0.5% — clause equals init (e.g. state=0 when init=0); add explicit anti-init examples
- 64.6% — single disjunct looks CTI-shaped but init witness differs (top: init0 + eq 1)
- 56 entries (6.4%)
- Init witness tags: `{'init0': 530, 'init1': 198, 'init_wide': 147}`

## D4 40% go/no-go

- Current: **1.745%** → target **40.0%** (gap 38.3 pts)
- Verdict: **mixed**
- Note: Mixed clause shapes across tiers; pursue tier-split targets and Q2 prompt fixes on high rejected_initial subset before full expressiveness expansion.

## D5 Next interventions

- P1: Q2.4 + narrow OR: max_block_clauses=1; ban unrelated refs in same clause (high — C2 OR-bloat 34.9%)
- P1: Q2.1/Q2.3: ban init-true literals; force single-disjunct / negate digest top-1 (high on rejected_initial)
- P1: Q2.1 init-aware: init0 forbid pol=true,rhs=1; require witness ref init check (high — B2 CTI/init mismatch 64.6%)
- P2: Q2.4: max_block_clauses=1 A/B (medium — reduce redundant wide clauses)
- P3: Q2.2: full disjuncts in rejected_json feedback (medium — improve retry on attempt 2/3)
