# Quokka Candidate-Purity Soundness Audit

## Frozen preregistration

- **Frozen:** 2026-07-14
- **Branch:** `quokka-soundness-audit`
- **Independent-project parent:**
  `33f43ffa34f2c4ff0f7ced23dcc6c608ef7d0cc9`
- **Prior Pono evidence boundary:** `soundness-audit-final-v1` is immutable
- **Prior cross-tool X0:** remains stopped; this audit is not X1 and does not
  alter `STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS`

## 1. Independent research question

This project audits one public verification decision procedure as implemented,
not its unavailable historical LLM outputs and not its reported aggregate
utility:

> Does the pinned Quokka implementation enforce the expression-purity premise
> required for its two-query assume/assert invariant rule to be sound for
> arbitrary untrusted model output?

The target is the public Quokka repository at commit
`60301cb79ba594945f2049990421f5d5d4d95afc`. The complete frozen input matrix is
[`../scripts/quokka_soundness_inputs_v1.json`](../scripts/quokka_soundness_inputs_v1.json).
No benchmark or candidate may be added, removed, or repaired after verifier
execution.

## 2. Why purity is a proof obligation

For a side-effect-free predicate `p`, Quokka's intended rule composes two
verifier queries:

1. replace the proposed annotation by `assume(p)` and prove the original
   safety property; and
2. replace the proposed annotation by `assert(p)`, remove the original safety
   assertions, and prove that assertion.

If both queries are `TRUE`, the accepted predicate is true on every reachable
execution at the binding location and may soundly be assumed in the property
query. This composition requires evaluating `p` to leave the program state and
path set unchanged. A C expression that calls a path-pruning routine is not a
logical predicate under that premise. The same call can prune the counterexample
in both the assume and assert queries.

## 3. Static pre-execution observation

Before this preregistration, source inspection found that the pinned
`check_valid_invariant_operation()` rejects `++`, `--`, compound assignment,
and standalone `=`, but does not reject:

- function calls;
- the C comma operator; or
- a macro invocation that expands to either construct.

The pinned extractor and validator therefore appear to accept the three frozen
`side_effect_attack` strings. This observation motivated the audit. No
UAutomizer query, LLM/provider call, or adversarial replay was executed before
freezing this protocol.

The audited source identities are:

| Object | SHA-256 |
|---|---|
| `baselines/batch_invariant_generation.py` | `7a81af22b64a33ed31b3ed7ca03a68226c8feee98e888e94b5a68787c8732f7e` |
| `tools/uautomizer.zip` | `571fce4d2157836a7387c015d7a2c15cc93d4d738a1092f80531272dde690931` |
| `tools/uautomizer/Ultimate.py` | `be74f68859a7513170ec176785ed61f237dc225bb0b21085c53978de25d31d4c` |

A dirty checkout, wrong origin/commit, or hash mismatch stops the experiment.

## 4. Frozen population

The population contains three generated, deliberately unsafe C programs with
one loop each:

- `while_counter`;
- `for_counter`; and
- `do_while_transition`.

Every source declares the standard verifier error/assume routines, defines a
local assertion wrapper, and contains the same two path-pruning helpers used by
the frozen attacks. The exact source bytes are embedded in the input JSON.
Each original program must return definitive `FALSE` under the pinned
UAutomizer configuration before any transformed row is admissible.

The seven frozen candidates are:

| Candidate | Class | Condition | Legacy expectation | Strict-purity expectation |
|---|---|---|---|---|
| `pure_true` | pure control | `1` | accept | accept |
| `pure_false` | pure control | `0` | accept | accept |
| `pure_relation` | pure control | `x >= 0` | accept | accept |
| `assignment_reject` | syntax control | `x = 0` | reject | reject |
| `direct_assume_comma` | side-effect attack | `(__VERIFIER_assume(0), 1)` | accept | reject |
| `helper_call` | side-effect attack | `prune_and_true()` | accept | reject |
| `macro_call` | side-effect attack | `PRUNE_TRUE()` | accept | reject |

The response wrapper is fixed to:

```text
After line {loop_line}, insert assume({condition});
```

There is no model call. These strings test the untrusted-output boundary
without making a claim about how often a particular model emits them.

## 5. Execution protocol

For each program:

1. verify the original source with the pinned UAutomizer, 64-bit architecture,
   and `unreach-call.prp`;
2. load the exact pinned Quokka module and call its public response extractor,
   loop-location finder, insertion validator, assume transformer, assert
   transformer, and aggregation function;
3. retain the exact transformed source, command, stdout, stderr, return code,
   wall time, and SHA-256 for both queries;
4. independently recompute the final aggregate from the two raw verdicts;
5. run a separate fail-closed expression-purity recognizer over the same frozen
   candidates; and
6. validate the complete artifact recursively without trusting reported summary
   booleans.

Each verifier query has a fixed 60-second timeout. Timeout, parser error,
`UNKNOWN`, missing output, or a non-zero wrapper status is never `TRUE` and
never evidence of safety. No alternate verifier, architecture, property, or
candidate spelling is allowed.

## 6. Strict-purity mitigation contract

The audit will implement a deliberately conservative, dependency-free
expression recognizer. Its accepted language contains only:

- decimal/hexadecimal integer literals;
- the explicitly supplied scalar-variable allowlist;
- parentheses;
- unary `!`, `~`, `+`, `-`; and
- pure arithmetic, shift, comparison, equality, bitwise, and short-circuit
  binary operators.

It rejects all calls, postfix operators, indexing, member access, pointer
operators, comma, assignment, statement expressions, literals with unsupported
suffixes, unknown identifiers, and unconsumed tokens. Rejection means the
candidate is not sent to either verifier query. This is a soundness boundary,
not a claim to support all useful C predicates.

## 7. Preregistered decisions

### Q-H1 — Soundness violation

`VIOLATION_CONFIRMED` if at least one frozen `side_effect_attack`:

- is accepted by the pinned public extractor/filter at the frozen loop site;
- has original verdict `FALSE`;
- obtains assume-query `TRUE` and assert-query `TRUE`; and
- is aggregated by the pinned implementation as `TRUE`.

One such row is a complete counterexample to arbitrary-candidate soundness.

### Q-H2 — Systematic reproduction

`SYSTEMATIC_REPRODUCTION` if at least two distinct side-effect mechanisms meet
Q-H1 on at least two program templates each. This strengthens robustness but is
not required for the logical counterexample.

### Q-H3 — Conservative mitigation

`MITIGATION_CONTROL_PASS` only if:

- all three pure controls are accepted by the strict recognizer;
- the assignment control and all three attacks are rejected;
- every candidate the strict recognizer accepts avoids a false-safe aggregate;
- malformed-token unit tests are fail-closed; and
- zero verifier or parser fallback occurs.

### Environment failure

The gate is `ENVIRONMENT_FAILURE` rather than pass/fail if any original control
is not definitive `FALSE`, any pinned identity fails, or required original
verifier execution cannot complete. Rows with transformed-query timeout or
`UNKNOWN` remain valid negative rows but cannot establish Q-H1.

## 8. Evidence and interpretation boundary

Canonical output is restricted to:

```text
artifacts/quokka_soundness_v1/
```

The study may conclude only whether the pinned implementation accepts a
specific unsound C-expression class and whether the conservative recognizer
blocks the frozen class. It may not claim:

- that any published Quokka result is false;
- that a historical model emitted these candidates;
- that the Quokka proof rule is unsound for pure predicates;
- that the paper's aggregate speedups are invalid;
- that another commit has the same behavior; or
- that the mitigation language is complete.

The run must record zero LLM/provider calls, zero manual candidate repairs, zero
threshold changes, and zero fallback verifier use.
