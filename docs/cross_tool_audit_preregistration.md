# Cross-Tool Soundness and Matched-Baseline Audit

## Gate X0 preregistration: public artifact availability

**Frozen:** 2026-07-14

**Branch:** `cross-tool-audit`

**Parent packaging commit:**
`8e5e050b6898f06a01e82108950925996eedcbcb`

**Prior research boundary:** `soundness-audit-final-v1` remains immutable

## 1. Independent research question

This project is not Gate 6 of `soundness-audit` and does not attempt to recover
Pono-LLM coverage. It asks:

> Which reported benefits of LLM-assisted formal verification survive
> original-verifier replay, explicit trust-boundary analysis, matched
> deterministic baselines, frozen outputs, and end-to-end cost accounting?

The unit of analysis is a released system/artifact pair, not an individual LLM
answer. The old Pono populations, success cases, failed candidates, and gate
thresholds are ineligible as target-selection criteria.

## 2. Research questions

- **X-RQ1 — Artifact sufficiency:** Can the published result be reconstructed
  from an immutable public release without contacting authors or repairing
  files?
- **X-RQ2 — Soundness boundary:** What does the final trusted verifier check,
  and can an invalid proposal ever be promoted through assumptions, bounded
  checks, hidden edits, or UNKNOWN handling?
- **X-RQ3 — Matched marginality:** Does the reported LLM gain remain after a
  deterministic baseline receives the same candidate/proof language, verifier
  feedback, search budget, and acceptance test?
- **X-RQ4 — Cost:** Does any surviving gain remain after generation, retries,
  verifier time, failed candidates, and API cost are included?

Gate X0 tests only X-RQ1. X-RQ2--X-RQ4 are unauthorized unless X0 passes.

## 3. Candidate freeze

The immutable candidate input is
[`../scripts/cross_tool_candidate_catalog_v1.json`](../scripts/cross_tool_candidate_catalog_v1.json).
It contains five systems spanning three verification settings:

| ID | Setting class | Specific setting | System |
|---|---|---|---|
| `cill` | model checking | transition-system / RTL model checking | CIll |
| `loris` | source-program verification | C loop-invariant synthesis | LORIS |
| `quokka` | source-program verification | C invariant acceleration benchmark | Quokka / InvBench |
| `autoverus` | deductive proof synthesis | Verus proof synthesis and repair | AutoVerus |
| `exverus` | deductive proof synthesis | counterexample-guided Verus proof repair | ExVerus |

No candidate may be removed, replaced, or supplemented after repository-level
inspection. Multiple systems from one setting class do not satisfy the
cross-setting threshold; in particular, LORIS plus Quokka or AutoVerus plus
ExVerus alone is insufficient.

### 3.1 Selection rule

Candidates were selected before local cloning or benchmark/result-file
inspection using the following fixed strata:

1. the directly relevant 2026 CTI-guided model-checking system;
2. the two recent verifier-backed C invariant systems already motivating the
   cross-tool question;
3. the public Verus synthesis baseline and its 2026 counterexample-guided
   repair successor.

The literature cutoff is 2026-07-14. Artifact discovery may follow only:

- a code/data URL declared by the paper or official project page;
- the exact repository URL frozen in the catalog; or
- an exact-title GitHub repository search when no artifact URL is declared.

Search failure is evidence of unavailability. It does not authorize a broader
keyword search or replacement system.

### 3.2 Prior-knowledge disclosure

This is not a blind artifact study. Before the freeze:

- the closed Pono project had already recorded that one public Quokka/InvBench
  derivative lacked exact predicates, insertion locations, verifier
  configuration, and a release hash manifest;
- top-level abstracts or repository landing pages had been seen for all five
  systems;
- the AutoVerus landing page disclosed a public repository, benchmarks,
  generated results, Docker instructions, and a pinned Verus revision;
- no candidate repository had been locally cloned for this gate, and no
  benchmark, generated proof, result table, or replay command had been audited.

These priors remain part of the evidence and cannot be erased by the X0 result.

## 4. Gate X0 eligibility contract

Each candidate is evaluated fail-closed against fourteen required fields:

1. `immutable_revision`: a public commit, tag, release, or content digest;
2. `license`: terms permit independent artifact inspection and replay;
3. `implementation`: executable source for the evaluated system;
4. `benchmark_inputs`: exact evaluated program/design bytes and stable IDs;
5. `frozen_llm_outputs`: all candidate invariants/proofs used by the reported
   replay, not only aggregate scores or a few examples;
6. `binding_locations`: exact source locations, assertion sites, or patches
   connecting each output to its verification obligation;
7. `expected_verdicts`: per-instance final verifier outcomes;
8. `verifier_identity`: verifier name and exact version/revision;
9. `verifier_build`: binary, container, or deterministic build recipe;
10. `offline_replay`: a command that checks frozen outputs without an API call;
11. `generation_config`: model, prompt, sampling/retry policy, and budget;
12. `per_instance_timing`: generation and verifier timing at instance/trial
    granularity;
13. `result_provenance`: a machine-readable mapping from benchmark and output
    hashes to reported rows;
14. `no_manual_repair`: replay does not require undocumented human edits.

The allowed field states are:

- `available`: public bytes or an exact public command establish the field;
- `missing`: the inspected release does not provide it;
- `blocked`: the declared public source cannot be retrieved;
- `ambiguous`: relevant material exists but cannot be mapped to the reported
  experiment without inference.

Only fourteen `available` fields make a candidate `full-audit-eligible`.
UNKNOWN, a landing-page claim, a paper aggregate, or a generator that requires
fresh LLM calls does not satisfy a field.

## 5. Census protocol

For every candidate, Gate X0 will:

1. resolve and freeze public repository revisions before file inspection;
2. record retrieval time, URL, revision, and archive/hash identity;
3. inventory repository paths without executing the system;
4. inspect only README, artifact instructions, manifests, benchmark/result
   indexes, containers, lockfiles, and referenced configuration files;
5. record one evidence path/URL and a concise finding for every field;
6. compute a candidate decision from the fourteen field states;
7. validate the final bundle recursively and independently.

Gate X0 does not build a verifier, execute a proof, call a model, download
model-generated replacements, or infer missing outputs from aggregate tables.

## 6. Preregistered decision

`GO_X1` requires all of the following:

- at least two `full-audit-eligible` candidates;
- those candidates span at least two verification settings;
- both expose frozen outputs and offline final-verifier replay;
- both expose per-instance generation and verification costs;
- zero provenance/hash ambiguity in the selected releases.

Otherwise the decision is `STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS`.

There is no limited GO, candidate substitution, author-contact repair,
best-effort replay, or lowering of the fourteen-field contract. A STOP means
the proposed cross-tool confirmatory audit is blocked by public artifact
sufficiency; it does not claim that a system is unsound or ineffective.

## 7. If and only if X0 passes

X1 will preregister a fixed replay population from the eligible releases and
classify, for every output:

- proposal bytes and insertion/binding;
- bounded versus inductive checking;
- assumptions, axioms, and trusted edits;
- final verifier verdict and UNKNOWN policy;
- exact proof artifact retained by the release.

Only after X1 independently reproduces the final-verifier boundary may X2
construct matched deterministic baselines. No LLM call is authorized by X0 or
X1.

## 8. Canonical output contract

Gate X0 will write only under:

```text
artifacts/cross_tool_x0_v1/
```

The directory must contain the frozen catalog, retrieval manifest, one strict
candidate report per system, a summary, provenance, and recursive integrity
manifest. Every report must preserve missing and blocked fields; no runner may
silently omit a candidate or field.
