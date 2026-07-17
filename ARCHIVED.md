# Repository Archived

**Status:** final, read-only research archive

**Archived:** 2026-07-18

**Final archive tag:** `pono-llm-archived-v1`

This repository preserves the completed Pono-LLM `soundness-audit` research
program. No Gate 6, replacement benchmark population, new LLM capture, or new
Pono mechanism is authorized in this archive.

## Scientific boundary

- Frozen evidence commit:
  `6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c`
- Frozen evidence tag: `soundness-audit-final-v1`
- Closure packaging commit:
  `8e5e050b6898f06a01e82108950925996eedcbcb`
- Machine-readable closure:
  [`artifacts/final_research_summary_v1.json`](artifacts/final_research_summary_v1.json)
- Authoritative claim ledger:
  [`docs/final_claim_ledger.md`](docs/final_claim_ledger.md)

The final report packages existing evidence and introduces no new experiment,
threshold change, or LLM/API call:

- [**Predicates, Not Assumptions: A Soundness and Matched-Baseline Audit of
  LLM-Guided IC3IA**](paper/pono_llm_final_report.pdf)
- [LaTeX source and build instructions](paper/README.md)

## Final scoped conclusion

Under original-model certification, matched deterministic expressiveness,
frozen replay, end-to-end accounting, and preregistered stopping rules, the
evaluated Pono-LLM populations retain no defensible LLM-specific solved-set or
search-efficiency advantage.

Two positive results remain:

1. LLM formulas can be integrated soundly as IC3IA abstraction predicates
   rather than concrete-model assumptions.
2. The released audit methodology separates apparent acceleration, candidate
   validity, abstraction guidance, inductive certification, and actual
   marginal LLM value.

Future work must begin as an independent project with a new research question,
population, and preregistration. It must not retroactively modify this
archive's claims or thresholds.
