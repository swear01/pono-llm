"""
Prompt builders and response parser for semantic invariant generation.

Handles Stage 0 (pre-flight) and Stage 2 (mid-run) requests.
The predicate_ast format matches IC3FramePredicateNode in ic3_frame_ast.h:
  {"form": "eq", "args": [{"form": "ref", "ref": "stateNN"}, {"form": "const", "const": "0", "width": W}]}
Supported forms: ref, const, eq, ne, unsigned/signed comparisons, logical
connectives, add, sub, mul, bitwise operations, concat, and extract.
"""
from __future__ import annotations

import json
import re
import sys
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
  "form": <op>,     // eq/ne; ult/ule/ugt/uge/slt/sle/sgt/sge; not/and/or/implies; add/sub/mul; bvand/bvor/bvxor/bvnot; concat/extract
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
    # Truncate property_desc: pono can send a multi-MB circuit formula; cap at 200 chars.
    property_desc = request.get("property_desc", "(unknown property)")
    if isinstance(property_desc, str) and len(property_desc) > 200:
        property_desc = property_desc[:200] + "...(truncated)"
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
        for iv in inputs[:30]:
            sym = iv.get("symbol", iv.get("ref", "?"))
            w = iv.get("width", "?")
            parts.append(f"  {sym} (width={w})")
        parts.append("")

    if transition_sketch:
        parts.append("TRANSITION SKETCH (shallow, best-effort):")
        for line in transition_sketch[:10]:
            parts.append(f"  {line}")
        parts.append("")

    sym_pairs = request.get("symmetric_pairs", [])
    if sym_pairs:
        parts.append("STRUCTURAL EQUALITY INVARIANTS (very likely inductive — MUST include as candidates):")
        for sp in sym_pairs[:12]:
            a, b, na, nb = sp["refA"], sp["refB"], sp["nameA"], sp["nameB"]
            if na != a:
                parts.append(f"  eq({a}, {b})  [{na} == {nb}]")
            else:
                parts.append(f"  eq({a}, {b})")
        if len(sym_pairs) > 12:
            parts.append(f"  ... and {len(sym_pairs)-12} more equality pairs")
        parts.append(
            "  These pairs have IDENTICAL init values and transition structure, so they"
            " are guaranteed to stay equal. Include ALL of the above as eq() candidates."
        )
        parts.append("")

    parts.append(
        "Generate 5-15 candidate invariants for this circuit. "
        "Focus on:\n"
        "  - The EQUALITY INVARIANTS listed above (include ALL of them)\n"
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

_BINARY_FORMS = frozenset({
    "eq", "ne", "ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge",
    "implies", "bvand", "bvor", "bvxor",
})
_UNARY_FORMS = frozenset({"not", "bvnot", "extract"})
_VARIADIC_FORMS = frozenset({"and", "or", "add", "sub", "mul"})


def predicate_ast_error(ast: Any, path: str = "predicate_ast") -> str | None:
    if not isinstance(ast, dict):
        return f"{path} must be an object"
    form = ast.get("form")
    if not isinstance(form, str) or not form:
        return f"{path}.form must be a non-empty string"
    if form == "ref":
        if not isinstance(ast.get("ref"), str) or not ast["ref"]:
            return f"{path}.ref must be a non-empty string"
        return None
    if form == "const":
        if not isinstance(ast.get("const"), str):
            return f"{path}.const must be a string"
        width = ast.get("width", 0)
        if not isinstance(width, int) or width < 0:
            return f"{path}.width must be a non-negative integer"
        return None

    args = ast.get("args")
    if not isinstance(args, list):
        return f"{path}.args must be a list"
    if form in _BINARY_FORMS and len(args) != 2:
        return f"{path} form {form} requires exactly 2 args"
    if form in _UNARY_FORMS and len(args) != 1:
        return f"{path} form {form} requires exactly 1 arg"
    if form in _VARIADIC_FORMS and not args:
        return f"{path} form {form} requires at least 1 arg"
    if form == "concat" and len(args) < 2:
        return f"{path} form concat requires at least 2 args"
    if (
        form not in _BINARY_FORMS
        and form not in _UNARY_FORMS
        and form not in _VARIADIC_FORMS
        and form != "concat"
    ):
        return f"{path} uses unsupported form {form}"
    if form == "extract":
        hi = ast.get("hi")
        lo = ast.get("lo")
        if not isinstance(hi, int) or not isinstance(lo, int):
            return f"{path} extract requires integer hi/lo"
        if lo < 0 or hi < lo:
            return f"{path} extract has invalid range [{hi}:{lo}]"
    for index, arg in enumerate(args):
        error = predicate_ast_error(arg, f"{path}.args[{index}]")
        if error:
            return error
    return None


def _validate_predicate_ast(ast: Any) -> bool:
    return predicate_ast_error(ast) is None


def parse_invariant_response_with_diagnostics(
    text: str,
) -> tuple[List[dict], List[dict]]:
    """
    Parse supported candidates and return explicit rejection diagnostics.
    """
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON object from text
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return [], [{"index": None, "error": "response is not JSON"}]
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            return [], [{"index": None, "error": "response is not JSON"}]

    if not isinstance(obj, dict):
        return [], [{"index": None, "error": "response root must be an object"}]

    raw_candidates = obj.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return [], [{"index": None, "error": "candidates must be a list"}]

    candidates = []
    rejected = []
    for index, c in enumerate(raw_candidates):
        if not isinstance(c, dict):
            rejected.append({"index": index, "error": "candidate must be an object"})
            continue
        kind = c.get("kind", "Type1_invariant")
        if kind not in ("Type1_invariant", "Type2_lift", "Type3_predicate"):
            kind = "Type1_invariant"
        ast = c.get("predicate_ast")
        error = predicate_ast_error(ast)
        if error:
            rejected.append({"index": index, "error": error})
            continue
        candidates.append({
            "id": c.get("id", len(candidates) + 1),
            "kind": kind,
            "verilog_expr": c.get("verilog_expr", ""),
            "predicate_ast": ast,
            "intuition": c.get("intuition", ""),
        })

    return candidates, rejected


def parse_invariant_response(text: str) -> List[dict]:
    """Parse supported candidates; malformed candidates are rejected."""
    candidates, errors = parse_invariant_response_with_diagnostics(text)
    if errors:
        print(
            "[invariant_prompt] rejected candidates: "
            + json.dumps(errors, sort_keys=True),
            file=sys.stderr,
        )
    return candidates
