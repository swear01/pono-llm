> **HISTORICAL (2026-06-03)** — Offline sampling prompts. Runtime uses `llm_worker/prompts/ic3_frame_v1.txt` (planned). See [`docs/ic3_frame_v1_integration.md`](../docs/ic3_frame_v1_integration.md).

=== DYNAMIC PAYLOAD START ===

## Sampling Direction

Sampling mode: {sampling_mode}
Diversity seed: {diversity_seed}
Requested candidates: {requested_candidates}

## Target Context

{target_context}

## Representative Frame Clauses

{frame_clauses}

## CTI Examples

{cti_examples}

## Known Failures to Avoid

{known_failures}

## Instructions

Use the static primer above as your fixed knowledge base.
Only use the dynamic payload below to choose the sampling direction.
Generate exactly {requested_candidates} candidates.
Return ONLY valid JSON.
