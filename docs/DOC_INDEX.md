# Documentation Index

**Project entry point:** [`../AGENTS.md`](../AGENTS.md) → `overview.md` · `structure.md` · `notes.md` · `plan.md` · `roadmap.md`
**Architecture:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
**Handoff (current task + file map):** [`HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md)
**Active plan:** [`plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md)

Last updated: 2026-06-15 (Stage 0/2 pivot + full archive migration)

> Pre-Stage-0/2 research records — Path 1 per-CTI injection, offline lemma-mining,
> closed-loop synthesis, Q2–Q4 harness, case studies, and one-off audits — were
> archived to [`../archive/docs/`](../archive/docs/) on 2026-06-15. They are
> **HISTORICAL only; not active truth.** `rg` excludes `archive/` by default.

---

## Canonical entry docs

| File | Description |
|------|-------------|
| [`overview.md`](overview.md) | What pono-llm is, domain concepts, external resources |
| [`structure.md`](structure.md) | Directory map + C++/Python module boundaries |
| [`notes.md`](notes.md) | Gotchas + decision rationale (tacit knowledge) |
| [`plan.md`](plan.md) | In-progress work + next-up + do-not-do |
| [`roadmap.md`](roadmap.md) | Backlog + recently shipped |

## Architecture & current state

| File | Description |
|------|-------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | C++/sidecar flow for the v1 integration |
| [`HANDOFF_CURRENT_STATE.md`](HANDOFF_CURRENT_STATE.md) | Current task and file map |
| [`BUG_ANALYSIS.md`](BUG_ANALYSIS.md) | Known/legacy bugs; update as v1 lands |

## Active plans (`plans/`)

| File | Description |
|------|-------------|
| [`plans/semantic_invariant_injection_v1_plan.md`](plans/semantic_invariant_injection_v1_plan.md) | **THE active plan** — Stage 0/2 semantic invariant injection |
| [`plans/lemma_expressiveness_roadmap.md`](plans/lemma_expressiveness_roadmap.md) | Future — lemma expressiveness X1–X4; gated on Phase Q data |
| [`plans/openrouter_provider_policy.md`](plans/openrouter_provider_policy.md) | OpenRouter v4-flash provider filtering policy |
| [`plans/experiment_parallel_policy.md`](plans/experiment_parallel_policy.md) | Parallel experiment defaults, server capacity, harness params |
| [`plans/experiment_plan_review.md`](plans/experiment_plan_review.md) | Experiment plan review + lessons from first round |
| [`plans/p040-smoke-session-latency-plan.md`](plans/p040-smoke-session-latency-plan.md) | p040 smoke session latency plan |

## Technical references (current)

| File | Description |
|------|-------------|
| [`hwmcc_experiment_tiers.md`](hwmcc_experiment_tiers.md) | Tier 0–3 HWMCC SOP; baseline / baseline-patch / `--skip-partial` resume |
| [`pono_dump_cpp_reference.md`](pono_dump_cpp_reference.md) | Pono C++ dump reference |
| [`pono_frame_cti_dump_format.md`](pono_frame_cti_dump_format.md) | Frame/CTI dump format |
| [`pono_ic3ia_dump_audit.md`](pono_ic3ia_dump_audit.md) | IC3IA dump audit |
| [`ic3ia_predicate_mapping_audit.md`](ic3ia_predicate_mapping_audit.md) | `stateNN` ↔ BTOR2 predicate mapping |
| [`mapping_spike_solver_shortlist.md`](mapping_spike_solver_shortlist.md) | Symbol shortlist notes |
| [`generalization_operators.md`](generalization_operators.md) | Operator vocabulary for the `operator` field |
| [`baseline_reproducibility.md`](baseline_reproducibility.md) | IC3IA nondeterminism — E2E metric design |
| [`ic3ia_nondeterminism_audit.md`](ic3ia_nondeterminism_audit.md) | Nondeterminism audit |
| [`gotchas.md`](gotchas.md) | General gotchas |

## Archived (historical)

All pre-Stage-0/2 research lives under [`../archive/docs/`](../archive/docs/) — 69 docs
covering Path 1 injection, offline lemma-mining / closed-loop synthesis, Q2–Q4
harness work, case studies, and one-off audits. Each carries an archive header.
Not active truth.

---

When adding a doc: link it here and tag its area. When a doc becomes historical,
archive it with `agents_rule archive <file> --reason ... --replacement ...` (never
`mv` manually).
