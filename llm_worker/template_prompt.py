"""Build prompts for template-guided semantic lemma generation.

Assembles a full context bundle: target property, hot variables,
transition slice, CTI batch, clause clusters, lemma memory, allowed schemas.
"""

import json
from typing import List, Dict, Optional
from lemma_schema import get_schema_list_for_prompt, get_schema_names


def build_template_prompt(context: Dict) -> str:
    """Build a complete prompt for template-guided LLM call.

    Args:
        context: Dict with keys:
            target_property, hot_variables, transition_slice,
            cti_batch, clause_clusters, lemma_memory, previous_results

    Returns:
        Complete prompt string
    """
    parts = []

    # ── Role ──
    parts.append(
        "You are assisting a word-level IC3IA hardware model checker (Pono).\n"
        "Your task: Generate broad candidate lemmas that may hold for all "
        "reachable states and may subsume multiple existing frame clauses."
    )

    # ── Rules ──
    parts.append(
        "RULES:\n"
        "- Do NOT select a subset of a single CTI cube.\n"
        "- Do NOT merely find literals common across CTIs.\n"
        "- Do NOT generate a lemma equivalent to the bad property.\n"
        "- Do NOT use variables not listed in the hot variables section.\n"
        "- Do NOT use arrays, quantifiers, uninterpreted memory, or next-state variables.\n"
        "- Generate semantic invariants over CURRENT-state variables only.\n"
        "- Use ONLY the lemma schemas listed below.\n"
        "- Infer semantic relations from the transition slice.\n"
        "- Target one or more clause clusters when reasonable.\n"
        "- Lemmas will be validated by SMT solvers; they do not need to be proven here.\n"
        "- All candidates are welcome; plausible ones are preferred.\n"
        "- Return JSON only, no markdown, no explanation outside JSON."
    )

    # ── Target property ──
    target = context.get("target_property", "(unknown)")
    if len(target) > 500:
        target = target[:497] + "..."
    parts.append(f"TARGET PROPERTY (to prove unreachable):\n{target}")

    # ── Hot variables ──
    parts.append(
        "HOT VARIABLES (relevant state/input signals):\n"
        f"{context.get('hot_variables', '(none)')}"
    )

    # ── Transition slice ──
    transition = context.get("transition_slice", "(unavailable)")
    parts.append(f"TRANSITION SLICE (pseudo-code of relevant next-state logic):\n{transition}")

    # ── CTI batch ──
    cti_batch = context.get("cti_batch", "(none)")
    parts.append(f"CURRENT CTI BATCH (counterexamples from the same IC3 frame):\n{cti_batch}")

    # ── Clause clusters ──
    clusters = context.get("clause_clusters", "")
    if clusters:
        parts.append(f"FRAME CLAUSE CLUSTERS (groups to potentially subsume):\n{clusters}")

    # ── Lemma memory ──
    memory = context.get("lemma_memory", {})
    accepted = memory.get("accepted", [])
    rejected = memory.get("rejected", [])
    if accepted or rejected:
        if accepted:
            parts.append("PREVIOUSLY ACCEPTED LEMMAS (these are known facts):")
            for a in accepted[:5]:
                parts.append(f"  ✓ {a}")
        if rejected:
            parts.append(
                "PREVIOUSLY REJECTED LEMMAS (these failed; do NOT repeat unless "
                "the context has changed):"
            )
            for r in rejected[:5]:
                parts.append(f"  ✗ {r}")

    # ── Allowed schemas ──
    parts.append(f"ALLOWED LEMMA SCHEMAS (use only these):\n{get_schema_list_for_prompt()}")

    # ── Output format ──
    parts.append(
        'OUTPUT FORMAT (JSON only):\n'
        '{\n'
        '  "candidates": [\n'
        '    {\n'
        '      "id": "cand_001",\n'
        '      "lemma": "(=> (= mode IDLE) (= valid 0))",\n'
        '      "schema": "mode_implication",\n'
        '      "target_clusters": ["cluster_00"],\n'
        '      "variables_used": ["mode", "valid"],\n'
        '      "intuition": "brief reasoning: why this might be invariant",\n'
        '      "risk_level": "low|medium|high"\n'
        '    }\n'
        '  ]\n'
        '}\n'
        f'Allowed schema values: {", ".join(get_schema_names())}\n'
        'Return ONLY the JSON object, no other text.'
    )

    return "\n\n".join(parts)
