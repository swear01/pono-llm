# Modular Algebraic Certificate Gate 4B0

This is the canonical deterministic Gate 4B0 artifact generated on 2026-07-13
from implementation commit `9e7e677507ad2baf9f357bc4ace52f80a457908d`.
The preregistration is commit
`cc7df688b6eb13ef33bab0ff9cdc3badc6b39527`. No LLM/API call was made.

## Decision

**STOP Gate 4B0.** The preregistered official translated population contains
no task eligible for the v1 kernel, so H5a cannot be evaluated and H5b is not
authorized. This is neither an H5a success nor evidence that modular
certificates work on natural families.

The structural census covers all 267 frozen Gate 3 tasks:

- 39 require arrays;
- 221 contain no v1-supported nonlinear update SCC;
- 7 tasks contain 9 nonlinear SCCs, but every SCC exceeds the frozen eight-
  branch cap;
- 0 tasks remain eligible, so no primary expected-safe or expected-unsafe
  population was selected.

The seven branch-cap near misses are `egcd2-ll`, `egcd3-ll`, `prod4br-ll`, and
`ps3-ll` through `ps6-ll`. The cap and v1 operator/width contract were not
changed after observing this result.

The next preregistered research gate is the known-map certified-transport
oracle. It was not started here.

## Development controls only

`fib_23` and `fib_30` validate exact wraparound normalization, complete branch
extraction, C1/kernel-C2/C3 composition, and solver agreement. They never count
toward H5a.

| Configuration | `fib_23` | `fib_30` |
|---|---:|---:|
| pinned Z3 4.13.1 integer blasting, C2 | UNSAT 5/5, 0.0287s | UNSAT 5/5, 0.0226s |
| local Z3 4.15.4 integer blasting, C2 | UNSAT 5/5, 0.0638s | UNSAT 5/5, 0.0478s |
| modular kernel core C2 | accepted 5/5, 0.00118s | accepted 5/5, 0.00117s |
| complete C1 + kernel C2 + C3 | accepted 5/5, 0.0116s | accepted 5/5, 0.0141s |
| plain IC3IA/Bitwuzla, original model | UNKNOWN 5/5, 1.07s median | UNKNOWN 5/5, 1.34s median |
| certified-basis IC3IA/Bitwuzla | UNSAT 5/5, 9.95s | UNSAT 5/5, 16.12s |

Times are median wall seconds. Kernel core timing is in-process and is not
directly equated with solver process wall time. Python Z3 4.16.0, local CLI Z3
default, pinned Z3 default, and pinned PolySAT each returned UNKNOWN 5/5 per
control at the 20-second solver limit. The pinned PolySAT checkout is clean at
`16fb86b636047fd79ad5827f768b6f26d8812948`; a separate activation probe
produced `:polysat-*` statistics before the matrix was accepted.

The Pono binary is the local ASan-instrumented build and is bound by version and
SHA-256 in `pono_matrix/matrix.json`. Pono safety time is reported separately
from generic C2 query time.

## Soundness result

- both development certificates pass original-model C1/C2/C3;
- the 20-case malformed/unsafe suite rejects 20/20 at the expected stage;
- the false-initial case reaches C1 SAT;
- the unsafe case reaches C3 SAT;
- wrong multipliers reach algebraic C2 rejection;
- bad hashes, provenance tampering, missing branches/substitutions, unsupported
  operators, and missing next functions fail closed;
- primary H5c was not run because there is no primary population.

## Contents

- `development_controls/`: strict certificates and checker reports;
- `c2_queries/`: immutable generic-C2 SMT2 corpus and hashes;
- `solver_matrix.json`: six exact Z3 configurations, five trials per control;
- `kernel_matrix.json`: kernel-only and full-certificate timings;
- `pono_matrix/`: plain and certified-basis original-model IC3IA runs;
- `population.json`: complete structural eligibility decision and near misses;
- `negative_suite/`: malformed, unsupported, false-initial, and unsafe controls;
- `provenance.json`: commits, frozen input hashes, host, and exact commands;
- `summary.json`: machine-readable H5a/H5b/H5c decisions;
- `integrity.json`: SHA-256 of every artifact file except itself.

## Reproduction

Run the commands in `provenance.json` sequentially from implementation commit
`9e7e677`. The local paths are environment-specific; benchmark IDs and model
hashes inside the manifests are portable. The final summary command refuses to
overwrite an existing summary or integrity manifest.
