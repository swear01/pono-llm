"""IC3 Frame v1 JSON schema validation."""

from typing import Any, Dict, List, Tuple


def validate_request(req: Dict[str, Any]) -> Tuple[bool, str]:
    if req.get("type") != "ic3_frame_request":
        return False, "type must be ic3_frame_request"
    if "frame_idx" not in req:
        return False, "missing frame_idx"
    if "cti_id" not in req:
        return False, "missing cti_id"
    if "cti" not in req:
        return False, "missing cti"
    return True, ""


def _flatten_disjuncts(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for item in raw:
        atom = item.get("atom") or item
        ref = atom.get("ref", "")
        rhs = atom.get("rhs", "")
        if not ref or not rhs:
            continue
        out.append({
            "ref": ref,
            "op": atom.get("op", "eq"),
            "rhs": rhs,
            "polarity": item.get("polarity", True),
        })
    return out


def _extract_predicate(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("form"):
        return raw
    for action in raw.get("actions") or []:
        if action.get("kind") == "refine_predicate":
            pred = action.get("predicate")
            if isinstance(pred, dict):
                return pred
    return {}


def _validate_predicate_node(node: Dict[str, Any]) -> Tuple[bool, str]:
    form = node.get("form", "")
    if form == "ref":
        if not node.get("ref"):
            return False, "ref leaf missing ref"
        return True, ""
    if form == "const":
        if "const" not in node and "width" not in node:
            return False, "const leaf missing value"
        return True, ""
    if form in ("eq", "ne", "ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge",
                "and", "or", "not", "implies", "bvand", "bvor", "bvxor", "bvnot",
                "concat", "extract"):
        args = node.get("args") or []
        if form in ("not", "bvnot") and len(args) != 1:
            return False, f"{form} requires 1 arg"
        if form in ("eq", "ne", "ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge",
                    "implies", "bvand", "bvor", "bvxor") and len(args) != 2:
            return False, f"{form} requires 2 args"
        if form in ("and", "or", "concat") and len(args) < 1:
            return False, f"{form} requires args"
        for arg in args:
            ok, err = _validate_predicate_node(arg)
            if not ok:
                return False, err
        return True, ""
    return False, f"unsupported predicate form: {form}"


def validate_response(resp: Dict[str, Any]) -> Tuple[bool, str]:
    if resp.get("type") != "ic3_frame_response":
        return False, "type must be ic3_frame_response"
    if not resp.get("source_cti_id"):
        return False, "missing source_cti_id"

    disjuncts = resp.get("block_disjuncts")
    if not disjuncts:
        for action in resp.get("actions") or []:
            if action.get("kind") == "block":
                clause = action.get("clause") or {}
                disjuncts = _flatten_disjuncts(clause.get("disjuncts") or [])
                break

    predicate = resp.get("refine_predicate") or _extract_predicate(resp)

    if not disjuncts and not predicate:
        return False, "missing block_disjuncts and refine_predicate"

    if disjuncts:
        for d in disjuncts:
            if not d.get("ref") or not d.get("rhs"):
                return False, "disjunct missing ref or rhs"

    if predicate:
        ok, err = _validate_predicate_node(predicate)
        if not ok:
            return False, err

    return True, ""


def normalize_response(resp: Dict[str, Any], source_cti_id: str, sample_id: int,
                       attempt: int = 1) -> Dict[str, Any]:
    """Normalize LLM output to flat block_disjuncts + refine_predicate."""
    disjuncts = resp.get("block_disjuncts")
    if not disjuncts:
        for action in resp.get("actions") or []:
            if action.get("kind") == "block":
                clause = action.get("clause") or {}
                disjuncts = _flatten_disjuncts(clause.get("disjuncts") or [])
                break

    predicate = resp.get("refine_predicate") or _extract_predicate(resp)

    symbols = resp.get("symbols_used") or []
    if not symbols:
        sym_set = set()
        for d in disjuncts or []:
            if d.get("ref"):
                sym_set.add(d["ref"])
        symbols = sorted(sym_set)

    out = {
        "schema_version": 1,
        "type": "ic3_frame_response",
        "source_cti_id": resp.get("source_cti_id") or source_cti_id,
        "sample_id": resp.get("sample_id", sample_id),
        "attempt": resp.get("attempt", attempt),
        "block_disjuncts": disjuncts or [],
        "symbols_used": symbols,
        "rationale": resp.get("rationale", ""),
    }
    if predicate:
        out["refine_predicate"] = predicate
    return out
