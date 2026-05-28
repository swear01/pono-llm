# Solver Validation Candidate Shortlist

## Summary

- Candidates considered: 30
- Viable (promising + needs_solver): 28
- Shortlisted: 5

**Selection criteria**: Multi-variable, state-only, concise, belongs to useful schema
family (guarded_implication, mutual_exclusion, bitslice_disequality, mode_exclusion).

## Selected Candidates

| Rank | Candidate ID | Cluster | Schema | Lemma | Verdict | Why selected | Mapping risk |
|---|---|---|---|---|---|---|---|
| 1 | cand_007 | C000 | guarded_implication | (=> (= state1536 10) (= state790 0)) | needs_solver | State-only guarded relation; highest generalization potential | low (simple pattern) |
| 2 | cand_008 | C000 | guarded_implication | (=> (= state1536 0) (= state1558 0)) | needs_solver | State-only guarded relation; highest generalization potential | low (simple pattern) |
| 3 | cand_004 | C000 | guarded_implication | (=> (= state2002 1) (= state1536 0)) | needs_solver | State-only guarded relation; highest generalization potential | low (simple pattern) |
| 4 | cand_005 | C000 | mutual_exclusion | (! (and (= state1536 10) (= state79 1))) | promising | Multi-var relational pattern; same family as qspiflash breakthrough case | low (simple pattern) |
| 5 | cand_007 | C000 | guarded_implication | (=> (= state1536 11) (= ((_ extract 12 12) i_wb_data) 1)) | needs_solver | State-only guarded relation; highest generalization potential | low (simple pattern) |

## Notes

This shortlist selects candidates for the next feasibility step: solver-backed
validation using either Bitwuzla (namespace-aligned benchmarks) or Pono C++ mapping
(real IC3IA traces). No solver validation has been performed yet.

The candidates were selected from existing batch generation output (v1 strict prompt
and v2 semantic lemma prompt). No new LLM calls were made for this selection.

**Not claimed**: runtime speedup, benchmark unlock, full Pono integration.
