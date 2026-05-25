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


def extract_design_context(stderr_log: str) -> dict:
    """Extract design-level proof context from pono IC3IA verbose output.
    Returns structured dict with property, signal counts, initial predicates.
    """
    import re

    blocking_pos = stderr_log.find("Blocking phase")
    init_section = stderr_log[:blocking_pos] if blocking_pos > 0 else stderr_log

    preds_raw = re.findall(r"adding predicate (.+?)(?:\n|$)", init_section)
    prop_match = re.search(r"Solving property: (.+?)(?:\n|$)", stderr_log)
    states = sorted(set(re.findall(r"\b(state\d+)\b", init_section)))
    inputs = sorted(set(re.findall(r"\b(input\d+)\b", init_section)))

    return {
        "property": prop_match.group(1)[:500] if prop_match else "(unknown)",
        "num_state_vars": len(states),
        "num_input_vars": len(inputs),
        "num_init_predicates": len(preds_raw),
        "initial_predicates": preds_raw[:10],
    }


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


def extract_btor_transition(btor_path: str, hot_vars: list) -> dict:
    """Parse BTOR2 to get next-state equations for hot variables."""
    import os, re as _re

    if not btor_path or not os.path.exists(btor_path):
        return {}

    btor = {}
    for line in open(btor_path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";":
            continue
        lid = parts[0]
        try:
            int(lid)
        except ValueError:
            continue
        btor[lid] = parts[1:]

    next_map = {}
    init_map = {}
    for lid, p in btor.items():
        if p[0] == "next" and len(p) >= 4:
            next_map[p[2]] = p[3]
        if p[0] == "init" and len(p) >= 4:
            init_map[p[2]] = p[3]

    def _get_const(lid):
        if lid and lid in btor and btor[lid][0] == "const":
            return btor[lid][2] if len(btor[lid]) > 2 else "?"
        if lid and lid in btor and btor[lid][0] == "zero":
            return "0"
        return "<L{}>".format(lid)

    def _get_deps(lid, visited=None):
        if visited is None:
            visited = set()
        if lid in visited or lid not in btor:
            return set()
        visited.add(lid)
        p = btor[lid]
        if p[0] == "state":
            return {"state{}".format(lid)}
        if p[0] == "input":
            return {p[2] if len(p) > 2 else "input{}".format(lid)}
        if p[0] in ("const", "zero", "ones", "sort", "bitvec"):
            return set()
        deps = set()
        for arg in p[1:]:
            try:
                deps |= _get_deps(arg, visited)
            except Exception:
                pass
        return deps

    result = {}
    for var in hot_vars:
        m = _re.match(r"state(\d+)", var)
        if not m:
            continue
        sid = m.group(1)
        if sid not in btor or btor[sid][0] != "state":
            continue

        next_id = next_map.get(sid, "")
        init_id = init_map.get(sid, "")
        next_val = _get_const(next_id) if next_id else "?"
        init_val = _get_const(init_id) if init_id else "?"
        next_is_const = bool(next_id and next_id in btor and btor[next_id][0] == "const")
        deps = _get_deps(next_id) if next_id else set()

        result[var] = {
            "name": var,
            "width": int(btor[sid][1]) if len(btor[sid]) > 1 else 1,
            "init_val": init_val,
            "next_val": next_val,
            "next_is_const": next_is_const,
            "dependencies": sorted(deps),
        }

    return result


def format_btor_transition(transitions: dict) -> str:
    """Format BTOR2 transition info for LLM prompt."""
    if not transitions:
        return "(no BTOR2 transition info extracted)"

    lines = []
    for var, info in sorted(transitions.items()):
        deps = info["dependencies"]
        dep_str = ", ".join(deps) if deps else "NONE (constant after init)"
        lines.append("  {}: {}' = {}".format(var, var, info["next_val"]))
        lines.append("    init = {}".format(info["init_val"]))
        lines.append("    width = {} bit".format(info["width"]))
        lines.append("    depends on: {}".format(dep_str))
        if info.get("next_is_const"):
            lines.append(
                "    KEY: next value is CONSTANT {}. "
                "This variable never changes after init.".format(info["next_val"])
            )
        lines.append("")

    return "\n".join(lines)
