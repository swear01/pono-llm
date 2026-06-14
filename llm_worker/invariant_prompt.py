"""
Prompt builders and response parser for semantic invariant generation.

Handles Stage 0 (pre-flight) and Stage 2 (mid-run) requests.
The predicate_ast format matches IC3FramePredicateNode in ic3_frame_ast.h:
  {"form": "eq", "args": [{"form": "ref", "ref": "stateNN"}, {"form": "const", "const": "0", "width": W}]}
Supported forms: ref, const, eq, ne, ult, ule, ugt, uge, not, and, or, implies, add, sub, bvand, bvor
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


INVARIANT_SYSTEM_PROMPT = """\
You are a hardware formal verification expert specialising in IC3/PDR model checking.

Your task is to generate INDUCTIVE INVARIANTS for a hardware circuit to help IC3 make progress.

INVARIANT REQUIREMENTS (critical):
1. TRUE at every initial state (init constraint must be satisfied)
2. Preserved by every transition (P ∧ T ⊨ P')
3. Expressed over STATE VARIABLES only — never input variables
4. Use only the refs listed in the request hot_variables

PREDICATE AST FORMAT:
{
  "form": <op>,     // eq, ne, ult, ule, ugt, uge, not, and, or, implies, add, sub, bvand, bvor
  "args": [...]     // sub-nodes
}
Leaves are:
  {"form": "ref", "ref": "stateNN"}          — state variable
  {"form": "const", "const": "0", "width": W} — bitvector constant (decimal or #b... or #x...)

OUTPUT FORMAT — return a single JSON object:
{
  "candidates": [
    {
      "id": <int>,
      "kind": "Type1_invariant",   // or "Type2_lift" or "Type3_predicate"
      "verilog_expr": "<human-readable expression>",
      "predicate_ast": <predicate AST node>,
      "intuition": "<why this invariant holds>"
    },
    ...
  ]
}

CANDIDATE KINDS:
- Type1_invariant: a new global invariant to inject directly (strongest)
- Type2_lift: unifies/generalizes many existing frame clauses into one stronger property
- Type3_predicate: an IC3IA abstract predicate hint (for predicate abstraction)

IMPORTANT: generate 5-15 candidates. Prefer simple, strong invariants over complex weak ones.
Sort candidates: most-likely-inductive first.
"""


# ---------------------------------------------------------------------------
# Stage 0 prompt
# ---------------------------------------------------------------------------

def build_stage0_prompt(request: dict) -> str:
    benchmark = request.get("benchmark", "unknown")
    property_desc = request.get("property_desc", "(unknown property)")
    hot_vars = request.get("hot_variables", [])
    transition_sketch = request.get("transition_sketch", [])

    parts = [
        f"BENCHMARK: {benchmark}",
        f"PROPERTY TO VERIFY: {property_desc}",
        "",
    ]

    if hot_vars:
        parts.append("HOT STATE VARIABLES (near the bad property):")
        for v in hot_vars:
            ref = v.get("ref", "?")
            width = v.get("width", "?")
            init = v.get("init", "?")
            verilog = v.get("verilog")
            label = f"  {ref} (width={width}, init={init})"
            if verilog:
                label += f" = {verilog}"
            parts.append(label)
        parts.append("")

    # Also list all inputs (gives semantic context even without clean state names)
    inputs = request.get("inputs", [])
    if inputs:
        parts.append("INPUT PORTS (for context):")
        for iv in inputs[:20]:
            sym = iv.get("symbol", iv.get("ref", "?"))
            w = iv.get("width", "?")
            parts.append(f"  {sym} (width={w})")
        parts.append("")

    if transition_sketch:
        parts.append("TRANSITION SKETCH (shallow, best-effort):")
        for line in transition_sketch[:10]:
            parts.append(f"  {line}")
        parts.append("")

    parts.append(
        "Generate 5-15 candidate invariants for this circuit. "
        "Focus on:\n"
        "  - Monotonicity / counter bounds\n"
        "  - Mutual exclusion between state bits\n"
        "  - Relationships between related state variables\n"
        "  - Conditions implied by the property\n\n"
        "Use ONLY the refs from the hot_variables list above in predicate_ast.\n"
        "Return JSON with a 'candidates' array."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Stage 2 prompt
# ---------------------------------------------------------------------------

def build_stage2_prompt(request: dict) -> str:
    trigger = request.get("trigger", "unknown")
    proof_state = request.get("proof_state", {})
    frame = proof_state.get("frame_idx", proof_state.get("current_frame", "?"))
    stuck_rounds = proof_state.get("frames_stuck_rounds", proof_state.get("stuck_rounds", "?"))
    cti_count = proof_state.get("total_cti_count", "?")
    clause_count = proof_state.get("frame_clause_count", "?")

    hot_vars = request.get("hot_variables", [])
    cti_cluster = request.get("cti_cluster", [])
    frame_clusters = request.get("frame_clause_clusters", [])
    prev_injected = request.get("previously_injected", [])

    parts = [
        f"IC3 IS STUCK at frame {frame} (trigger: {trigger}).",
        f"  Stuck rounds: {stuck_rounds}",
        f"  Total CTIs so far: {cti_count}",
        f"  Frame clauses so far: {clause_count}",
        "",
    ]

    if hot_vars:
        parts.append("STATE VARIABLES (in this frame's CTIs):")
        for v in hot_vars:
            ref = v.get("ref", "?")
            width = v.get("width", "?")
            init = v.get("init", "?")
            verilog = v.get("verilog")
            label = f"  {ref} (width={width}, init={init})"
            if verilog:
                label += f" = {verilog}"
            parts.append(label)
        parts.append("")

    if cti_cluster:
        parts.append(f"CTI CLUSTER ({len(cti_cluster)} CTIs — all are bad state candidates):")
        for i, cti in enumerate(cti_cluster[:8]):
            vals = cti.get("values", cti)
            parts.append(f"  CTI {i+1}: {json.dumps(vals, separators=(',', ':'))}")
        if len(cti_cluster) > 8:
            parts.append(f"  ... and {len(cti_cluster)-8} more")
        parts.append("")

    if frame_clusters:
        parts.append("FRAME CLAUSE PATTERNS (existing blocking clauses):")
        for fc in frame_clusters[:6]:
            pattern = fc.get("pattern_desc", "?")
            count = fc.get("count", "?")
            example = fc.get("example_verilog", fc.get("example", ""))
            parts.append(f"  [{count}x] {pattern}")
            if example:
                parts.append(f"       e.g. {example}")
        parts.append("")

    if prev_injected:
        parts.append("PREVIOUSLY INJECTED INVARIANTS (already applied):")
        for inv in prev_injected:
            parts.append(f"  {inv}")
        parts.append("")

    parts.append(
        "ANALYSIS TASK:\n"
        "1. Identify the common SEMANTIC PATTERN in the CTI cluster above.\n"
        "2. Generate invariants that would make ALL these CTIs unreachable.\n"
        "3. If applicable, generate a Type2 lift that UNIFIES multiple frame clauses into one.\n\n"
        "Return JSON with a 'candidates' array.\n"
        "Prioritise Type1 (eliminates CTI cluster) over Type3 (predicate refinement)."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _validate_predicate_ast(ast: Any) -> bool:
    """Minimal structural check: must be a dict with 'form' key."""
    if not isinstance(ast, dict):
        return False
    form = ast.get("form")
    if not form:
        return False
    if form in ("ref",) and not ast.get("ref"):
        return False
    if form in ("const",) and "const" not in ast:
        return False
    return True


def parse_invariant_response(text: str) -> List[dict]:
    """
    Parse the LLM JSON response into a list of candidate dicts.
    Returns [] on any parse error (caller handles gracefully).
    """
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON object from text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            return []

    raw_candidates = obj.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return []

    candidates = []
    for c in raw_candidates:
        if not isinstance(c, dict):
            continue
        kind = c.get("kind", "Type1_invariant")
        if kind not in ("Type1_invariant", "Type2_lift", "Type3_predicate"):
            kind = "Type1_invariant"
        ast = c.get("predicate_ast")
        if not _validate_predicate_ast(ast):
            continue
        candidates.append({
            "id": c.get("id", len(candidates) + 1),
            "kind": kind,
            "verilog_expr": c.get("verilog_expr", ""),
            "predicate_ast": ast,
            "intuition": c.get("intuition", ""),
        })

    return candidates
