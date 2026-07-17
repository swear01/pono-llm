# Final Technical Report

The archival paper is:

- source: [`main.tex`](main.tex)
- bibliography: [`references.bib`](references.bib)
- compiled report: [`pono_llm_final_report.pdf`](pono_llm_final_report.pdf)

It reports only the closed Pono-LLM `soundness-audit` research program. It does
not include later cross-tool or unrelated project work.

## Build

```bash
cd paper
pdflatex -interaction=nonstopmode -halt-on-error main.tex
bibtex main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
cp main.pdf pono_llm_final_report.pdf
```

The evidence boundary is commit
`6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c` and tag
`soundness-audit-final-v1`. The paper is archival packaging: it introduces no
new experiment, threshold change, or LLM/API call.
