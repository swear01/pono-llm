# Cross-Tool Gate X0 Result

- **Completed:** 2026-07-14
- **Branch:** `cross-tool-audit`
- **Preregistration commit:**
  `4d17851b746e30467b7c01e48bfce8b678a8955b`
- **Decision:** `STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS`
- **X1 authorized:** no

## 1. Scope

Gate X0 asked only whether a confirmatory cross-tool audit could be executed
from immutable public artifacts. It did not test the soundness, effectiveness,
or reported coverage of any candidate system.

The frozen population contained five systems in three verification-setting
classes:

| Candidate | Setting class | Frozen repository revision |
|---|---|---|
| CIll | model checking | `gipsyh/rIC3@7149d568785b039134f0b2baa58358c8af63e70d` and `gipsyh/cill-exp@a61258b1b6abe1d2bdd6966e09485977777f901b` |
| LORIS | source-program verification | `ltcRandomwalk/LORIS@315809c0685d11206840da3944b5e6a323178663` |
| Quokka / InvBench | source-program verification | `Anjiang-Wei/Quokka@60301cb79ba594945f2049990421f5d5d4d95afc` |
| AutoVerus | deductive proof synthesis | `microsoft/verus-proof-synthesis@2f9aff36b4e287e41b1bc167f7888a5cddac4cdd` |
| ExVerus | deductive proof synthesis | `claudeyj/exverus@3619935559f12e4be31abb0b9ff87fab5d293b8e` |

The catalog, search boundary, required fields, and decision rule were committed
before repository-file inspection. No candidate was removed, replaced, or
added after inspection.

## 2. Frozen decision rule

Each candidate had to expose all fourteen fields as `available`:

1. immutable revision;
2. license;
3. implementation;
4. benchmark inputs;
5. frozen LLM outputs;
6. binding locations;
7. expected verdicts;
8. verifier identity;
9. verifier build;
10. offline replay;
11. generation configuration;
12. per-instance timing;
13. result provenance; and
14. evidence of no undocumented manual repair.

`GO_X1` required at least two 14/14 candidates spanning at least two setting
classes. Any `missing`, `blocked`, or `ambiguous` field made that candidate
ineligible. There was no partial GO, author-contact repair, candidate
substitution, or threshold revision.

## 3. Result

| Candidate | Available | Missing | Ambiguous | Fully eligible |
|---|---:|---:|---:|---|
| AutoVerus | 10 | 1 | 3 | no |
| CIll | 8 | 3 | 3 | no |
| LORIS | 7 | 3 | 4 | no |
| Quokka / InvBench | 7 | 7 | 0 | no |
| ExVerus | 4 | 8 | 2 | no |
| **Total field states** | **36** | **22** | **12** | **0 candidates** |

There were no `blocked` fields: all declared repositories were retrieved. The
gate stopped because none of the five frozen releases supplied a complete
14-field chain from benchmark bytes and generated output to offline final-
verifier replay, per-instance cost, and hash-bound reported-result provenance.

### 3.1 Candidate-level blockers

**AutoVerus** was the closest release at 10/14. It includes implementation,
benchmarks, generated outputs, binding information, expected verdicts, a
license, verifier identity/build information, and generation configuration.
The release did not provide a machine-readable benchmark/output-hash mapping to
reported rows. Its offline replay contract, separate per-instance generation
and verifier timing, and no-manual-repair status remained ambiguous under the
fail-closed contract.

**CIll** exposed frozen outputs, bindings, verdicts, and verifier build
information across its rIC3 and experiment repositories. The experiment
repository did not carry a license, no frozen-output offline replay command was
available, and result provenance was missing. Generation policy, separated
timing, and undocumented-edit status remained ambiguous.

**LORIS** included benchmarks, a large frozen result archive, per-run verdicts,
and verifier information. It lacked a repository license, an offline command
that rechecks the frozen outputs through the verifier, and a hash-bound result
manifest. Binding locations, complete run configuration, separated timing, and
no-manual-repair status required inference and were therefore ambiguous.

**Quokka / InvBench** included source, benchmarks, verifier configuration, and
generation configuration, but the resolved release did not contain the
evaluated LLM result JSON files. Consequently frozen outputs, output bindings,
expected LLM verdicts, offline replay, LLM-run timing, provenance, and
no-manual-repair evidence were missing.

**ExVerus** documented how fresh repair experiments would run, but its resolved
commit did not contain the described paper-run results directory. Frozen
outputs, bindings, verdicts, offline replay, timing, provenance, and
no-manual-repair evidence were therefore absent; the repository also lacked a
root license. Verifier-build determinism and the exact paper-run generation
configuration remained ambiguous.

The authoritative field-by-field findings and evidence objects are the five
JSON reports under
[`../artifacts/cross_tool_x0_v1/reports/`](../artifacts/cross_tool_x0_v1/reports/).

## 4. Scientific interpretation

The result supports the following narrow claim:

> Under the preregistered 14-field contract, the five frozen public releases
> do not provide the minimum artifact population required for the proposed
> confirmatory cross-tool soundness and matched-baseline audit.

It does **not** support any of the following claims:

- that an evaluated system is unsound;
- that its paper result is false;
- that its authors cannot reproduce it in their original environment;
- that a fresh-generation replication would fail;
- that LLM-assisted verification has no value; or
- that a weaker artifact contract would be inappropriate for another study.

Artifact absence and scientific invalidity are different propositions. Gate X0
was deliberately designed to stop before verifier execution rather than infer
trust-boundary or utility results from incomplete public evidence.

## 5. Execution boundary

The canonical provenance records:

- new LLM/provider API calls: **0**;
- verifier executions: **0**;
- freshly generated candidate outputs: **0**;
- author contacts: **0**;
- threshold changes: **false**; and
- amendment of `soundness-audit`: **false**.

The inspection was limited to immutable Git metadata, repository inventories,
README/artifact instructions, manifests, benchmark/result indexes, containers,
lockfiles, referenced configuration, and frozen result objects. External source
tree blobs were not copied into the artifact; cited files are represented by
their commit, Git object, byte count, and SHA-256 identities. Raw GitHub API
retrieval payloads were validated against the pre-inspection freeze while
building the artifact, but are not bundled because commit responses can contain
diff patches and public author metadata. Their SHA-256 identities remain in the
immutable retrieval manifest, and the provenance records these distinctions.
Consequently, bundle-only validation proves the manifest and derived checkout
identities, but cannot by itself reconstruct the omitted API response bytes.

## 6. Artifact and validation

The canonical bundle is
[`../artifacts/cross_tool_x0_v1/`](../artifacts/cross_tool_x0_v1/). Its entry
points are:

- `summary.json` — decision, counts, blockers, and authorization state;
- `provenance.json` — commits, code identities, execution boundary, and
  inspection scope;
- `reports/*.json` — strict field-level candidate reports;
- `inventories/*` — complete immutable Git-tree inventories;
- `source_files.json` — hash identities for cited source files;
- `retrieval/` — pre-inspection retrieval manifest and raw-payload hashes; and
- `integrity.json` — recursive file-set and SHA-256 manifest.

Important semantic self-hashes are:

| Object | SHA-256 |
|---|---|
| candidate catalog | `d8dfeaa65d6a34652f0018d9ac61a587ce884c208847094ee9750b0047a13fd3` |
| retrieval freeze | `1c4576d67a73b0ae771c6f7e37529933e5d1c9d981778bf45b70b0c21308c804` |
| census | `c9cfab43b56ce6f144a3b5f30ae7133ba72fe8963462c167f77bf866e218ed6b` |
| summary | `6cf305c043ce863e4486656235669e419e3592edf591d3cca0e9878a38490c74` |
| provenance | `6e4edfcdff8b2b6a2f225070478d50b1e6c8863707041325d4160456da854baa` |

Validate the frozen bundle with:

```bash
python3 scripts/validate_cross_tool_x0.py artifacts/cross_tool_x0_v1
```

The validator does not trust the summary booleans. It independently rebuilds
field-state sets, candidate eligibility, setting coverage, the gate decision,
evidence identities, path inventories, provenance, and recursive integrity.

To create a new non-canonical replication from the same exact external
checkouts and retrieval freeze:

```bash
python3 scripts/build_cross_tool_x0.py \
  /tmp/cross-tool-x0-repos \
  /tmp/cross-tool-x0-freeze \
  /tmp/cross-tool-x0-replication
python3 scripts/validate_cross_tool_x0.py \
  /tmp/cross-tool-x0-replication
```

The canonical run records the preregistration commit as its builder commit.
Later non-canonical replications are accepted only from descendants of that
commit, and only when all builder/census sources are tracked and unchanged from
the recorded `HEAD`. The builder also fails if an external checkout is dirty or
has the wrong origin/revision, or if the output directory already exists. The
canonical directory must not be rebuilt in place.

## 7. Decision and follow-on boundary

X1, X2, and X3 are not authorized. This branch therefore performs no verifier
build/replay, soundness-boundary experiment, deterministic matched baseline, or
LLM call. Contacting authors, using later releases, weakening fields, or
generating fresh outputs would define a new replication protocol and cannot be
used to rewrite this result.

The independent cross-tool project ends at X0. The result is an
artifact-availability finding, not a cross-tool soundness or effectiveness
finding.
