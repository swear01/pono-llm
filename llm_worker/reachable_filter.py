#!/usr/bin/env python3
"""Reachable-sample consistency checker for lemma candidates.

Evaluates a lemma against concrete state assignments and reports
whether the lemma holds, is violated, or cannot be evaluated.

A sound invariant must hold on all reachable states.
If a candidate excludes a known reachable sample, it cannot be an invariant.
"""

import re
from typing import Dict, Optional, List


def get_var_bw(var_name: str) -> Optional[int]:
    """Return bitwidth for known state variables."""
    known = {
        "state1536": 4, "state790": 1, "state1558": 1,
        "state2002": 1, "state79": 1, "state1359": 1, "state1361": 1,
    }
    return known.get(var_name)


def _max_val(bw: int) -> int:
    return (1 << bw) - 1


# --- Core evaluation ---

def evaluate_on_sample(lemma: str, sample_values: Dict[str, str]
                       ) -> Dict:
    """Evaluate a lemma on concrete sample values.

    Args:
        lemma: The lemma S-expression
        sample_values: Dict mapping var_name (or var_name_next) to value string

    Returns:
        {"result": "holds | violated | unknown_parse | missing_variable | unsupported",
         "reason": "..."}
    """
    if not lemma or not lemma.strip():
        return {"result": "unknown_parse", "reason": "empty lemma"}

    # Resolve variable values: try both var_name and var_name_next
    def _val(v):
        v_next = v + "_next"
        if v_next in sample_values:
            return sample_values[v_next]
        if v in sample_values:
            return sample_values[v]
        return None

    try:
        held = _evaluate_expr(lemma.strip(), _val)
        if held is None:
            return {"result": "missing_variable", "reason": f"could not resolve all variables in sample"}
        return {"result": "holds" if held else "violated",
                "reason": f"evaluates to {held} on sample"}
    except ParseError as e:
        return {"result": "unknown_parse", "reason": str(e)}
    except UnsupportedExpr as e:
        return {"result": "unsupported", "reason": str(e)}


class ParseError(Exception):
    pass


class UnsupportedExpr(Exception):
    pass


def _evaluate_expr(expr: str, val_fn) -> Optional[bool]:
    """Recursively evaluate an S-expression against concrete values.

    Returns True/False or None if a variable value is missing.
    """
    expr = expr.strip()

    # Parse S-expression
    parsed, consumed = _parse_s_expr(expr)
    if parsed is None:
        # Try as a simple comparison handled by regex
        return _eval_simple(expr, val_fn)

    return _eval_parsed(parsed, val_fn)


def _eval_simple(expr: str, val_fn) -> Optional[bool]:
    expr = expr.strip()

    # (<= stateX V)
    m = re.match(r'\(\s*<=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        v = val_fn(m.group(1))
        if v is None: return None
        return int(v) <= int(m.group(2))

    # (>= stateX V)
    m = re.match(r'\(\s*>=\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        v = val_fn(m.group(1))
        if v is None: return None
        return int(v) >= int(m.group(2))

    # (< stateX V)
    m = re.match(r'\(\s*<\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        v = val_fn(m.group(1))
        if v is None: return None
        return int(v) < int(m.group(2))

    # (> stateX V)
    m = re.match(r'\(\s*>\s*(state\d+)\s+(\d+)\s*\)', expr)
    if m:
        v = val_fn(m.group(1))
        if v is None: return None
        return int(v) > int(m.group(2))

    raise ParseError(f"cannot parse: {expr[:60]}")


def _eval_parsed(expr_list, val_fn) -> Optional[bool]:
    if not expr_list:
        raise ParseError("empty expression list")
    op = expr_list[0]

    if op == '=>' and len(expr_list) >= 3:
        ante = _eval_parsed(expr_list[1], val_fn) if isinstance(expr_list[1], list) else _eval_atom(expr_list[1], val_fn)
        cons = _eval_parsed(expr_list[2], val_fn) if isinstance(expr_list[2], list) else _eval_atom(expr_list[2], val_fn)
        if ante is None or cons is None:
            return None
        return (not ante) or cons

    if op == 'and' and len(expr_list) >= 3:
        a = _eval_parsed(expr_list[1], val_fn) if isinstance(expr_list[1], list) else _eval_atom(expr_list[1], val_fn)
        b = _eval_parsed(expr_list[2], val_fn) if isinstance(expr_list[2], list) else _eval_atom(expr_list[2], val_fn)
        if a is None or b is None:
            return None
        return a and b

    if op == 'or' and len(expr_list) >= 3:
        a = _eval_parsed(expr_list[1], val_fn) if isinstance(expr_list[1], list) else _eval_atom(expr_list[1], val_fn)
        b = _eval_parsed(expr_list[2], val_fn) if isinstance(expr_list[2], list) else _eval_atom(expr_list[2], val_fn)
        if a is None or b is None:
            return None
        return a or b

    if op == 'not' and len(expr_list) >= 2:
        inner = _eval_parsed(expr_list[1], val_fn) if isinstance(expr_list[1], list) else _eval_atom(expr_list[1], val_fn)
        if inner is None:
            return None
        return not inner

    if op == '!' and len(expr_list) >= 2:
        inner = _eval_parsed(expr_list[1], val_fn) if isinstance(expr_list[1], list) else _eval_atom(expr_list[1], val_fn)
        if inner is None:
            return None
        return not inner

    if op == '=' and len(expr_list) >= 3:
        return _eval_eq(expr_list, val_fn)

    if op == '<=' and len(expr_list) >= 3:
        return _eval_rel(expr_list, val_fn, lambda a, b: a <= b)

    if op == '>=' and len(expr_list) >= 3:
        return _eval_rel(expr_list, val_fn, lambda a, b: a >= b)

    if op == '<' and len(expr_list) >= 3:
        return _eval_rel(expr_list, val_fn, lambda a, b: a < b)

    raise UnsupportedExpr(f"unsupported op '{op}' in subexpression")


def _eval_atom(atom, val_fn) -> Optional[bool]:
    if isinstance(atom, list):
        return _eval_parsed(atom, val_fn)
    raise ParseError(f"unexpected atom: {atom}")


def _eval_eq(expr_list, val_fn) -> Optional[bool]:
    a = expr_list[1]
    b = expr_list[2]
    if isinstance(a, str) and a.startswith("state"):
        va = val_fn(a)
        vb = int(b) if isinstance(b, str) and b.isdigit() else val_fn(str(b))
    elif isinstance(b, str) and b.startswith("state"):
        vb = val_fn(b)
        va = int(a) if isinstance(a, str) and a.isdigit() else val_fn(str(a))
    else:
        va = val_fn(str(a))
        vb = val_fn(str(b))
    if va is None or vb is None:
        return None
    return int(va) == int(vb)


def _eval_rel(expr_list, val_fn, cmp) -> Optional[bool]:
    a = expr_list[1]
    b = expr_list[2]
    if isinstance(a, str) and a.startswith("state"):
        va = val_fn(a)
        vb = int(b) if isinstance(b, str) and b.isdigit() else val_fn(str(b))
    elif isinstance(b, str) and b.startswith("state"):
        vb = val_fn(b)
        va = int(a) if isinstance(a, str) and a.isdigit() else val_fn(str(a))
    else:
        return None
    if va is None or vb is None:
        return None
    return cmp(int(va), int(vb))


# --- S-expression parser (same as lemma_nontriviality but self-contained) ---

def _parse_s_expr(s: str):
    """Parse a balanced S-expression. Returns (parsed, consumed)."""
    s = s.strip()
    if not s or s[0] != '(':
        return None, 0
    pos = 1
    result = []
    buf = ""
    while pos < len(s):
        ch = s[pos]
        if ch == '(':
            if buf.strip():
                result.append(buf.strip())
                buf = ""
            sub, consumed = _parse_s_expr(s[pos:])
            if sub is None:
                return None, 0
            result.append(sub)
            pos += consumed
        elif ch == ')':
            if buf.strip():
                result.append(buf.strip())
            return result, pos + 1
        elif ch == ' ':
            if buf.strip():
                result.append(buf.strip())
            buf = ""
            pos += 1
        else:
            buf += ch
            pos += 1
    return None, 0


# --- Batch application ---

def filter_candidates(candidates: List[Dict],
                      samples: List[Dict]) -> List[Dict]:
    """Apply reachable-sample filter to a list of candidates.

    Args:
        candidates: List of {lemma: str, candidate_id: str, ...}
        samples: List of {sample_id: str, values: dict, ...}

    Returns:
        List of evaluation records
    """
    results = []
    for cand in candidates:
        lemma = cand.get("lemma") or cand.get("repaired_lemma") or cand.get("lemma_str", "")
        cid = cand.get("candidate_id") or cand.get("repair_id") or cand.get("id", "?")

        # For "reject" — skip
        if lemma.strip().lower() == "reject" or not lemma.strip():
            results.append({"candidate_id": cid, "lemma": lemma,
                            "filter_result": "not_applicable",
                            "reason": "empty or rejected"})
            continue

        violations = []
        all_holds = []

        for smp in samples:
            result = evaluate_on_sample(lemma, smp.get("values", {}))
            if result["result"] == "violated":
                violations.append({
                    "sample_id": smp["sample_id"],
                    "sample_values": smp.get("values", {}),
                    "evaluation": result["reason"],
                })
            elif result["result"] == "holds":
                all_holds.append(smp["sample_id"])
            elif result["result"] == "missing_variable":
                pass  # sample doesn't cover this lemma's vars
            elif result["result"] == "unknown_parse":
                violations.append({
                    "sample_id": smp["sample_id"],
                    "evaluation": f"parse error: {result['reason']}",
                })

        if violations:
            final = "violates_reachable_sample"
        elif not any(r["result"] == "holds" for r in [evaluate_on_sample(lemma, s.get("values", {}))
                 for s in samples]):
            final = "no_applicable_samples"
        else:
            final = "consistent_with_samples"

        results.append({
            "candidate_id": cid,
            "lemma": lemma[:150],
            "filter_result": final,
            "samples_checked": len(samples),
            "samples_violated": len(violations),
            "samples_held": len(all_holds),
            "violations": violations[:3],
        })

    return results


def filter_summary(filter_results: List[Dict]) -> Dict:
    """Generate summary statistics from filter results."""
    from collections import Counter
    verdicts = Counter(r["filter_result"] for r in filter_results)
    return {
        "total": len(filter_results),
        "consistent_with_samples": verdicts.get("consistent_with_samples", 0),
        "violates_reachable_sample": verdicts.get("violates_reachable_sample", 0),
        "no_applicable_samples": verdicts.get("no_applicable_samples", 0),
        "not_applicable": verdicts.get("not_applicable", 0),
    }
