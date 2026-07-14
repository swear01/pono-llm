# Quokka Candidate-Purity Audit Result

**Completed:** 2026-07-14
**Decision:** `VIOLATION_CONFIRMED`, `SYSTEMATIC_REPRODUCTION`,
`MITIGATION_CONTROL_PASS`

The frozen public implementation accepted every side-effect candidate in the
3-program by 3-mechanism attack matrix. Each original program was definitively
`FALSE`; each accepted attack produced raw assume-query `TRUE`, raw
assert-query `TRUE`, and pinned aggregate `TRUE`. Thus all nine attack rows
were false-safe under the arbitrary-string candidate boundary.

The mechanisms were:

1. direct `__VERIFIER_assume(0)` plus comma;
2. a helper call containing the same path-pruning operation; and
3. a macro expanding to that operation.

All three reproduced on `while`, `for`, and `do-while` templates. The public
filter rejected the assignment syntax control but accepted the three call/comma
forms at the exact loop site. No LLM call, alternate verifier, timeout, manual
candidate repair, or fallback contributed to a decisive row.

The independent conservative purity recognizer accepted the three frozen pure
controls on all programs and rejected the assignment control and all attacks.
No recognizer-accepted row was false-safe. This is a mitigation control only;
the recognizer is deliberately incomplete and is not integrated upstream.

## Claim boundary

The result is a counterexample to the pinned implementation's soundness for
arbitrary untrusted candidate expressions. It does not establish that a
historical model emitted such an expression, invalidate a published benchmark
row, apply to another commit, or challenge the two-query rule for pure
predicates.

## Reproduction

```sh
python3 scripts/run_quokka_soundness_audit.py \
  --upstream /home/swear01/quokka-r1 \
  --java /home/swear01/.local/bin/java11
python3 scripts/validate_quokka_soundness_audit.py
pytest -q scripts/tests/test_quokka_expression_purity.py
```

Canonical evidence is `artifacts/quokka_soundness_v1/`.


## Chronology limitation

The preregistration and machine-readable input existed before the verifier run
in the execution session, but the branch did not commit those bytes before the
result was produced. The final commit binds both, and the provenance reports
this limitation explicitly; Git history alone cannot prove the preregistration
chronology. The raw counterexample remains independently checkable, but this
weakens any claim of commit-verifiable prospective ordering.
