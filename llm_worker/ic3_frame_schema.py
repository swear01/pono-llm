"""IC3 Frame v1 JSON schema validation."""

from typing import Any, Dict, List, Tuple

MAX_DISJUNCTS_PER_CLAUSE = 8
MAX_BLOCK_CLAUSES_HARD_CAP = 8


def validate_batch_request(req: Dict[str, Any]) -> Tuple[bool, str]:
    if req.get("type") != "ic3_frame_batch_request":
        return False, "type must be ic3_frame_batch_request"
    for key in ("batch_id", "frame_idx", "cti_entries"):
        if key not in req:
            return False, f"missing {key}"
    entries = req.get("cti_entries") or []
    if not entries:
        return False, "cti_entries empty"
    digest = req.get("cti_digest")
    if digest is not None:
        if not isinstance(digest, dict):
            return False, "cti_digest must be object"
        if not digest.get("cti_total"):
            return False, "cti_digest missing cti_total"
    for i, ent in enumerate(entries):
        if not ent.get("cti_id"):
            return False, f"cti_entries[{i}] missing cti_id"
        if "cti" not in ent and "literals" not in ent:
            return False, f"cti_entries[{i}] invalid"
    return True, ""


def validate_request(req: Dict[str, Any]) -> Tuple[bool, str]:
    req_type = req.get("type")
    if req_type == "ic3_frame_batch_request":
        return validate_batch_request(req)
    if req_type != "ic3_frame_request":
        return False, f"unknown request type: {req_type}"
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


def _collect_block_clauses(
    resp: Dict[str, Any],
    max_clauses: int = 0,
) -> List[List[Dict[str, Any]]]:
    clauses: List[List[Dict[str, Any]]] = []

    raw_clauses = resp.get("block_clauses")
    if isinstance(raw_clauses, list):
        for item in raw_clauses:
            if isinstance(item, list):
                flat = _flatten_disjuncts(item)
            elif isinstance(item, dict):
                flat = _flatten_disjuncts([item])
            else:
                flat = []
            if flat:
                clauses.append(flat)

    if not clauses:
        disjuncts = resp.get("block_disjuncts")
        if disjuncts:
            flat = _flatten_disjuncts(disjuncts)
            if flat:
                clauses.append(flat)

    if not clauses:
        for action in resp.get("actions") or []:
            if action.get("kind") == "block":
                clause = action.get("clause") or {}
                flat = _flatten_disjuncts(clause.get("disjuncts") or [])
                if flat:
                    clauses.append(flat)

    if max_clauses > 0 and len(clauses) > max_clauses:
        clauses = clauses[:max_clauses]
    return clauses


def _validate_disjuncts(disjuncts: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if not disjuncts:
        return False, "empty clause"
    if len(disjuncts) > MAX_DISJUNCTS_PER_CLAUSE:
        return False, f"clause exceeds {MAX_DISJUNCTS_PER_CLAUSE} disjuncts"
    for d in disjuncts:
        if not d.get("ref") or not d.get("rhs"):
            return False, "disjunct missing ref or rhs"
    return True, ""


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


def validate_response(
    resp: Dict[str, Any],
    max_block_clauses: int = MAX_BLOCK_CLAUSES_HARD_CAP,
) -> Tuple[bool, str]:
    if resp.get("type") != "ic3_frame_response":
        return False, "type must be ic3_frame_response"
    if not resp.get("source_cti_id"):
        return False, "missing source_cti_id"

    clauses_all = _collect_block_clauses(resp, max_clauses=0)
    if max_block_clauses > 0 and len(clauses_all) > max_block_clauses:
        return False, f"too many block_clauses (max {max_block_clauses})"
    clauses = clauses_all if max_block_clauses <= 0 else clauses_all[:max_block_clauses]
    predicate = resp.get("refine_predicate") or _extract_predicate(resp)

    if not clauses and not predicate:
        return False, "missing block_clauses/block_disjuncts and refine_predicate"

    for clause in clauses:
        ok, err = _validate_disjuncts(clause)
        if not ok:
            return False, err

    if predicate:
        ok, err = _validate_predicate_node(predicate)
        if not ok:
            return False, err

    return True, ""


def collect_block_clauses(
    resp: Dict[str, Any],
    max_clauses: int = 0,
) -> List[List[Dict[str, Any]]]:
    """Public accessor for normalized block_clauses extraction."""
    return _collect_block_clauses(resp, max_clauses=max_clauses)


def normalize_response(resp: Dict[str, Any], source_cti_id: str, sample_id: int,
                       attempt: int = 1,
                       max_block_clauses: int = MAX_BLOCK_CLAUSES_HARD_CAP) -> Dict[str, Any]:
    """Normalize LLM output to block_clauses + refine_predicate."""
    clauses = _collect_block_clauses(resp, max_clauses=max_block_clauses)
    predicate = resp.get("refine_predicate") or _extract_predicate(resp)

    symbols = resp.get("symbols_used") or []
    if not symbols:
        sym_set = set()
        for clause in clauses:
            for d in clause:
                if d.get("ref"):
                    sym_set.add(d["ref"])
        symbols = sorted(sym_set)

    out = {
        "schema_version": 1,
        "type": "ic3_frame_response",
        "source_cti_id": resp.get("source_cti_id") or source_cti_id,
        "sample_id": resp.get("sample_id", sample_id),
        "attempt": resp.get("attempt", attempt),
        "block_clauses": clauses,
        "block_disjuncts": clauses[0] if clauses else [],
        "symbols_used": symbols,
        "rationale": resp.get("rationale", ""),
    }
    if predicate:
        out["refine_predicate"] = predicate
    return out
