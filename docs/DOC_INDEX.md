# Documentation Index

**Last updated:** 2026-07-13 (Gate 5A0 stopped population-insufficient)

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
| [`plan.md`](plan.md) | Completed Gate 0--5 evidence and the final algorithm-expansion stop |
| [`roadmap.md`](roadmap.md) | Closed prior gates plus Gate 5 census/transport sequencing and stop criteria |
| [`notes.md`](notes.md) | Tacit knowledge, soundness gotchas, timing caveats, next-step decisions |
| [`structure.md`](structure.md) | Directory map and module boundaries |
| [`representation_phase_gate.md`](representation_phase_gate.md) | Completed source/lifted/raw phase-local grammar-routing contract and H1--H4 decisions |
| [`algebraic_certificate_gate.md`](algebraic_certificate_gate.md) | Frozen Gate 4B0 contract plus official zero-eligible-population, solver, soundness, and stop decisions |
| [`inductiveness_gap_gate.md`](inductiveness_gap_gate.md) | Gate 5A failure decomposition and 6/6 false-candidate decision |
| [`certified_transport_gate.md`](certified_transport_gate.md) | Frozen Gate 5A0/5A contract plus official population-insufficient stop |

## Supporting references

| File | Description |
|------|-------------|
| [`plans/openrouter_provider_policy.md`](plans/openrouter_provider_policy.md) | OpenRouter provider filtering policy |
| [`../artifacts/README.md`](../artifacts/README.md) | Canonical Phase 1+2, Gate 2, representation/phase, and algebraic-certificate evidence |
| [`../artifacts/representation_phase_v1/README.md`](../artifacts/representation_phase_v1/README.md) | Paired population, prompts, capture, matrices, certificates, and recursive integrity manifest |
| [`../artifacts/algebraic_certificate_v1/README.md`](../artifacts/algebraic_certificate_v1/README.md) | Gate 4B0 solver reconnaissance, strict certificates, population decision, negative suite, and recursive integrity manifest |
| [`../artifacts/certified_transport_v1/README.md`](../artifacts/certified_transport_v1/README.md) | Gate 5A0 source-certificate census, explicit runtime exclusions, and population-insufficient stop |

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
