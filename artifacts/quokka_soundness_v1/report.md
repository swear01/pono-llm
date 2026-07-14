# Result: systematic candidate-purity violation

The pinned public filter accepted all nine frozen side-effect rows. In every
case the original program was `FALSE`, while both transformed queries were
`TRUE` and the pinned aggregate was `TRUE`. The result reproduces across three
program templates and three side-effect mechanisms: direct special-call plus
comma, helper call with a hidden assume, and macro expansion.

This establishes the preregistered `VIOLATION_CONFIRMED` and
`SYSTEMATIC_REPRODUCTION` decisions for arbitrary untrusted candidate strings.
It does not show that any released model produced such a string, that a
published benchmark result is wrong, or that the two-query rule is unsound for
pure predicates.

The independent conservative recognizer accepted all nine pure-control rows
and rejected the assignment control plus all nine attack rows. No
purity-accepted row was false-safe, so `MITIGATION_CONTROL_PASS` holds for the
frozen language and matrix. The recognizer is deliberately incomplete and is
not integrated into upstream Quokka.

Pure controls behaved as expected under the raw two-query rule: `1` and
`x >= 0` did not hide the unsafe final property, while `0` failed its assertion
query. No timeout, alternate verifier, manual candidate repair, or LLM call
contributed to the decisive rows.
