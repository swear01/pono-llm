=== DYNAMIC PAYLOAD START ===

## Source Artifacts

{artifacts}

## Allowed Operators

{allowed_operators}

## Known Failures to Avoid

{known_failures}

## Instructions

Generalize the source artifacts above. Use ONLY the allowed operators listed.
Every candidate MUST include source_artifact_id referencing one of the artifacts above.
Return ONLY valid JSON with a "generalized_candidates" array.
Each candidate must have: candidate_id, source_artifact_id, source_artifact_type,
generalization_operator, original_artifact, lemma, schema, variables,
why_this_is_a_generalization, why_may_be_inductive, why_may_have_proof_impact, risk.

Generate {requested_candidates} candidates.
