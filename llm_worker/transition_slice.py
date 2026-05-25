"""Extract transition slice pseudo-code from IC3IA SMT context.

MVP: extracts hot variable names from CTI literals.
Full version would convert SMT transition to pseudocode (deferred to v1).
"""

import re
from typing import List, Dict, Set


def extract_hot_variables(cti_literals: List[dict]) -> List[str]:
    """Extract state/input variable names from CTI literal varnames.

    Looks for patterns like 'stateNNN', 'inputNNN' in simplified SMT expressions.
    Also finds single-word variable names from simpler expressions.
    """
    seen: Set[str] = set()

    for lit in cti_literals:
        text = lit.get("varname", "") + " " + lit.get("expr", lit.get("varname", ""))

        # SMT-style state variables: stateNNN, inputNNN
        for match in re.finditer(r'\b(state\d+|input\d+)\b', text):
            seen.add(match.group(1))

        # Simple word-level vars (for simpler benchmarks)
        for match in re.finditer(r'\b([a-z_][a-z0-9_]{2,})\b', text):
            word = match.group(1)
            # Skip common SMT keywords
            if word not in (
                "bvor", "bvand", "bvnot", "ite", "bvult", "bvugt", "bvule",
                "bvuge", "bvslt", "bvsgt", "extract", "concat", "zero_ext",
                "sign_ext", "bvadd", "bvsub", "bvmul", "distinct", "bvcomp",
                "true", "false", "not", "and", "or", "xor", "let",
            ):
                seen.add(word)

    # Sort: state vars first, then inputs, then others
    def sort_key(v: str) -> tuple:
        if v.startswith("state"):
            return (0, v)
        if v.startswith("input"):
            return (1, v)
        return (2, v)

    return sorted(seen, key=sort_key)[:30]


def format_variable_list(hot_vars: List[str]) -> str:
    """Format hot variable list for LLM prompt consumption."""
    if not hot_vars:
        return "(no hot variables extracted)"
    return "\n".join(f"  - {v}" for v in hot_vars)


def summarize_cti_batch(
    ctis: List[dict],
    max_ctis: int = 10,
    max_lits_per_cti: int = 12,
) -> str:
    """Summarize a batch of CTI contexts for LLM consumption.

    Groups by frame and annotates common vs varying literals.
    """
    if not ctis:
        return "(no CTIs available)"

    lines = []

    for i, cti in enumerate(ctis[:max_ctis], 1):
        frame = cti.get("frame_idx", "?")
        lits = cti.get("literals", [])
        lines.append(f"CTI #{i} (frame {frame}, {len(lits)} literals):")

        for lit in lits[:max_lits_per_cti]:
            vn = lit.get("varname", "?")
            val = lit.get("value", "?")
            # Truncate very long varnames
            if len(vn) > 150:
                vn = vn[:147] + "..."
            lines.append(f"    {vn} = {val}")

        if len(lits) > max_lits_per_cti:
            lines.append(f"    ... ({len(lits) - max_lits_per_cti} more literals)")

        lines.append("")

    return "\n".join(lines)
