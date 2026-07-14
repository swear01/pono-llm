# Quokka candidate-purity soundness audit v1

This bundle applies the frozen audit in
`docs/quokka_soundness_preregistration.md` to
`Anjiang-Wei/Quokka@60301cb79ba594945f2049990421f5d5d4d95afc`.

The original programs, exact assume/assert transformations, raw UAutomizer
stdout/stderr, per-row JSON, aggregate raw results, summary, and recursive
integrity manifest are retained. No LLM or alternate verifier was used.

Recheck with:

```sh
python3 scripts/validate_quokka_soundness_audit.py
```
