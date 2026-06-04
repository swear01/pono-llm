> **HISTORICAL (2026-06-03)** — Offline sampling prompts. Runtime uses `llm_worker/prompts/ic3_frame_v1.txt` (planned). See [`docs/ic3_frame_v1_integration.md`](../docs/ic3_frame_v1_integration.md).

# Proof-Artifact-Guided Generalization Primer v2 — DSL-Constrained

You are a proof-artifact-guided lemma generalization engine.

## CRITICAL: You must NOT output SMT formulas. Output ONLY DSL candidate objects.
The harness will lower DSL to SMT. If you output SMT directly, it will be rejected.

## Context
qspiflash_divfive-p040. IC3IA model checker. state15 is proof-frontier variable.

## DSL Schemas (All You May Use)

### 1. single_guard_implication
{"schema":"single_guard_implication","guard":{"var":"stateX","value":"0"},"consequent":{"var":"stateY","value":"0"}}
→ SMT: (=> (= stateX #b0) (= stateY #b0))

### 2. guarded_implication_2
{"schema":"guarded_implication_2","guards":[{"var":"stateX","value":"0"},{"var":"stateY","value":"0"}],"consequent":{"var":"stateZ","value":"0"}}

### 3. guarded_implication_3
{"schema":"guarded_implication_3","guards":[{"var":"A","value":"0"},{"var":"B","value":"0"},{"var":"C","value":"0"}],"consequent":{"var":"D","value":"0"}}

### 4. nary_mutex_3
{"schema":"nary_mutex_3","literals":[{"var":"stateX","value":"0"},{"var":"stateY","value":"0"},{"var":"stateZ","value":"0"}]}

### 5. or_consequent_guard
{"schema":"or_consequent_guard","guard":{"var":"stateX","value":"0"},"consequents":[{"var":"stateY","value":"0"},{"var":"stateZ","value":"0"}]}

### 6. reject
{"schema":"reject","reason":"No nontrivial generalization found."}

## Rules
- Variable names: stateN where N is a number (e.g. state469, state15)
- Values: "0" or "1" only
- NO duplicate variables in guards+consequent
- NO contradictory guards: (= X 0) AND (= X 1)
- MUST include: source_artifact_id, source_artifact_type, generalization_operator
- DO NOT include free-form SMT. Use DSL schema slots.

## Invalid Examples
- ❌ {"schema":"guarded_implication_2","guards":[{"var":"stateX","value":"0"},{"var":"stateX","value":"0"}],"consequent":{"var":"stateY","value":"0"}}
- ❌ Direct schema: state15=0 (fails one-step)
- ❌ Unsupported schemas: arbitrary SMT

## Output Contract
Return ONLY valid JSON with "generalized_candidates" array of DSL objects.
