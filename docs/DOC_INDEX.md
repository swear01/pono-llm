# Documentation Index

**Last updated:** 2026-07-12 (Gate 2 complete; claims falsified; replay provenance hardened)

Start here:

- Project entry point: [`../AGENTS.md`](../AGENTS.md)
- Overview: [`overview.md`](overview.md)
- Active plan: [`plan.md`](plan.md)
- Roadmap: [`roadmap.md`](roadmap.md)
- Notes / gotchas: [`notes.md`](notes.md)
- Structure: [`structure.md`](structure.md)

## Canonical active docs

| File | Description |
|------|-------------|
| [`overview.md`](overview.md) | Current project scope, sound predicate-injection architecture, latest results |
| [`plan.md`](plan.md) | Completed Phase 1+2/Gate 2 evidence and the active representation-pivot decision |
| [`roadmap.md`](roadmap.md) | Current decision gates after the corrected deterministic-baseline audit |
| [`notes.md`](notes.md) | Tacit knowledge, soundness gotchas, timing caveats, next-step decisions |
| [`structure.md`](structure.md) | Directory map and module boundaries |

## Supporting references

| File | Description |
|------|-------------|
| [`plans/openrouter_provider_policy.md`](plans/openrouter_provider_policy.md) | OpenRouter provider filtering policy |
| [`../artifacts/README.md`](../artifacts/README.md) | Canonical Phase 1+2/Gate 2 evidence, integrity sidecars, and hash manifests |

## Archived in this update

The following docs were historical snapshots and were archived on 2026-07-11.  Do not use them as active truth:

- [`../archive/docs/HANDOFF_CURRENT_STATE.md`](../archive/docs/HANDOFF_CURRENT_STATE.md) — 2026-06-17 handoff, superseded by soundness-audit plan.
- [`../archive/docs/report.md`](../archive/docs/report.md) — 2026-06-17 constraint-injection report, superseded by sound predicate injection.
- [`../archive/docs/ARCHITECTURE.md`](../archive/docs/ARCHITECTURE.md) — reactive IC3 Frame v1 architecture, superseded by initial predicate injection + Phase 1/2 validation.
- [`../archive/docs/architecture_plan.md`](../archive/docs/architecture_plan.md) — obsolete constraint/assume-era architecture alternatives.
- [`../archive/docs/plan.md`](../archive/docs/plan.md) — first Phase 1+2 plan and biased static-baseline results, superseded by the corrected plan.
- [`../archive/docs/roadmap.md`](../archive/docs/roadmap.md) — long historical roadmap containing superseded constraint-era sections.
- [`../archive/docs/plans/experiment_parallel_policy.md`](../archive/docs/plans/experiment_parallel_policy.md) — reactive sidecar parallelism policy superseded by frozen replay.
- [`../archive/docs/plans/experiment_plan_review.md`](../archive/docs/plans/experiment_plan_review.md) — obsolete reactive IC3/sidecar experiment plan.
- [`../archive/docs/plans/lemma_expressiveness_roadmap.md`](../archive/docs/plans/lemma_expressiveness_roadmap.md) — obsolete frame-lemma roadmap superseded by initial predicates and certificates.

When adding a doc: link it here and tag whether it is active or background.  When a doc becomes historical, archive it with `agents_rule archive <file> --reason ... --replacement ...` (never `mv` manually).
