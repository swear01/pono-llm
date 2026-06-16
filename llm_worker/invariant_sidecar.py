"""
Handlers for ic3_stage0_request and ic3_stage2_request.
Imported by sidecar.py — implements the stub functions defined there.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from btor2_reader import (
    BTOR2Info,
    parse_btor2,
    hot_refs_near_bad,
    build_hot_variables,
    build_transition_sketch,
    detect_symmetric_pairs,
)
from invariant_arith import (
    detect_software_origin,
    build_software_prompt,
    verify_invariant,
    inject_as_constraints,
    _ast_has_arithmetic,
)
from invariant_prompt import (
    INVARIANT_SYSTEM_PROMPT,
    build_stage0_prompt,
    build_stage2_prompt,
    parse_invariant_response,
)
from llm_client import LLMClient

# Tokens budget: invariant generation needs more room than blocking clause
_MAX_TOKENS = 8192

# BFS depth from bad node for hot variable selection
_HOT_DEPTH = 6


def _load_btor2(btor2_path: str) -> Optional[BTOR2Info]:
    """Load BTOR2 info; return None on any error."""
    if not btor2_path or not os.path.isfile(btor2_path):
        return None
    try:
        return parse_btor2(btor2_path)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[inv_sidecar] WARNING: failed to parse BTOR2 {btor2_path}: {exc}")
        return None


def _enrich_request_with_btor2(request: dict) -> dict:
    """
    If the request has a 'btor2_path', parse it and inject:
      - hot_variables
      - inputs
      - transition_sketch
    Returns a shallow copy of request with these keys added (originals not overwritten).
    """
    if "hot_variables" in request:
        return request  # already enriched (e.g. from tests or future C++ pre-fill)

    btor2_path = request.get("btor2_path", "")
    info = _load_btor2(btor2_path)
    if info is None:
        return request

    enriched = dict(request)
    refs = hot_refs_near_bad(info, depth=_HOT_DEPTH)
    enriched["hot_variables"] = build_hot_variables(info, refs)
    enriched["transition_sketch"] = build_transition_sketch(info, refs)
    enriched["inputs"] = [
        {"ref": iv.ref, "symbol": iv.symbol, "width": iv.width}
        for iv in info.inputs
    ]
    # Detect symmetric pairs (likely inductive eq invariants) filtered to hot refs
    # and to pairs where both states have known init values.
    state_by_ref = {sv.ref: sv for sv in info.states}
    all_pairs = detect_symmetric_pairs(info, refs)
    sym_pairs = []
    for a, b in all_pairs:
        sv_a, sv_b = state_by_ref.get(a), state_by_ref.get(b)
        if sv_a and sv_b and sv_a.init_value is not None and sv_b.init_value is not None:
            na = sv_a.symbol or a
            nb = sv_b.symbol or b
            sym_pairs.append({"refA": a, "refB": b, "nameA": na, "nameB": nb})
    enriched["symmetric_pairs"] = sym_pairs
    return enriched


def _call_llm(client: LLMClient, user_prompt: str, request: dict) -> tuple[str, int, float]:
    """Wrapper around client.call with request-level overrides."""
    model_name = request.get("model") or None
    reasoning_effort = request.get("reasoning_effort", "none")
    text, tokens, latency_ms = client.call(
        user_prompt,
        system_prompt=INVARIANT_SYSTEM_PROMPT,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        max_tokens=_MAX_TOKENS,
    )
    return text, tokens, latency_ms


_REF_REF_FORMS = frozenset([
    "eq", "ne", "uge", "ule", "ugt", "ult", "sge", "sle", "sgt", "slt",
])


def _is_safe_candidate(cand: dict) -> bool:
    """
    Allow only binary comparisons (eq/ne/uge/ule/…) where BOTH operands are plain
    state-variable refs. Rejects anything with a const, bvand/bvor, or nested expr.

    Candidates from parse_invariant_response() have the predicate_ast nested inside
    a "predicate_ast" key. We unwrap that before checking.
    """
    ast = cand.get("predicate_ast", cand)  # unwrap LLM candidate format if present
    form = ast.get("form", "")
    args = ast.get("args", [])
    if form in _REF_REF_FORMS and len(args) == 2:
        a, b = args[0], args[1]
        if a.get("form") == "ref" and b.get("form") == "ref":
            return True
    return False


def _make_eq_candidate(ref_a: str, ref_b: str) -> dict:
    """Create a fully-formatted eq(A,B) candidate in the same format as parse_invariant_response."""
    return {
        "id": 0,
        "kind": "Type1_invariant",
        "verilog_expr": "",
        "predicate_ast": {
            "form": "eq",
            "args": [{"form": "ref", "ref": ref_a}, {"form": "ref", "ref": ref_b}],
        },
        "intuition": "structural symmetric pair (expression-hash verified)",
    }


def _filter_candidates(candidates: list, label: str, request_id: str) -> list:
    """Apply _is_safe_candidate and log how many were dropped."""
    before = len(candidates)
    safe = [c for c in candidates if _is_safe_candidate(c)]
    dropped = before - len(safe)
    if dropped:
        print(f"[inv_sidecar] {label} {request_id}: filtered {dropped} risky, "
              f"{len(safe)} safe remain")
    return safe


def _handle_software_origin_stage0(
    client: LLMClient, request: dict, info: "BTOR2Info", request_id: str
) -> tuple[list, int, float]:
    """
    Software-origin path: LLM generates arithmetic loop invariants,
    each candidate is verified sound via verify_invariant.

    Sound arithmetic invariants are injected as BTOR2 constraints into a temp
    file and written to request["btor2_path"].constrained (for external runners).
    Returns (verified_candidates, tokens, latency_ms).
    """
    btor2_path = request.get("btor2_path", "")
    user_prompt = build_software_prompt(request, info)
    text, tokens, latency_ms = _call_llm(client, user_prompt, request)
    raw = parse_invariant_response(text)

    verified = []
    sound_asts = []
    for c in raw:
        ast = c.get("predicate_ast")
        expr = c.get("verilog_expr", "?")
        if not ast:
            continue
        # Skip pure const-bound constraints (ref-const comparisons) — they slow IC3IA
        args = ast.get("args", [])
        has_arith = _ast_has_arithmetic(ast)
        is_ref_ref = len(args) == 2 and all(a.get("form") == "ref" for a in args)
        if not (has_arith or is_ref_ref):
            print(f"[inv_sidecar] sw_stage0 {request_id}: skip const-bound {expr!r}")
            continue
        ok, reason = verify_invariant(ast, btor2_path, timeout_s=20)
        if ok:
            print(f"[inv_sidecar] sw_stage0 {request_id}: SOUND {expr!r}")
            verified.append(c)
            sound_asts.append(ast)
        else:
            print(f"[inv_sidecar] sw_stage0 {request_id}: rejected {expr!r} ({reason})")

    # Write constrained BTOR2 for external pre-processing runners
    if sound_asts:
        constrained_path, n = inject_as_constraints(sound_asts, btor2_path)
        if constrained_path:
            marker = btor2_path + ".constrained"
            try:
                import shutil
                shutil.copy2(constrained_path, marker)
                print(f"[inv_sidecar] sw_stage0 {request_id}: "
                      f"constrained BTOR2 → {marker}")
            except Exception:
                pass

    return verified, tokens, latency_ms


def handle_stage0_request(client: LLMClient, request: dict) -> dict:
    """
    Pre-flight invariant generation.

    For software-origin circuits (C-derived, clean variable names like i,n,x,y):
      LLM generates arithmetic loop invariants; each is verified sound before injection.

    For hardware circuits with structural symmetric pairs:
      Always injects eq(A,B) for each sym_pair (deterministic); LLM for extras.
    """
    request_id = request.get("request_id", "unknown")
    enriched = _enrich_request_with_btor2(request)

    # Check for software-origin first (C-derived circuits with preserved names)
    btor2_path = request.get("btor2_path", "")
    info = _load_btor2(btor2_path)
    if info and detect_software_origin(info) and not enriched.get("symmetric_pairs"):
        sw_candidates, tokens, latency_ms = _handle_software_origin_stage0(
            client, request, info, request_id
        )
        print(f"[inv_sidecar] stage0 {request_id}: software-origin, "
              f"{len(sw_candidates)} sound candidates ({tokens} tokens, {latency_ms:.0f}ms)")
        return {
            "type": "ic3_invariant_response",
            "request_id": request_id,
            "candidates": sw_candidates,
            "_token_count": tokens,
            "_latency_ms": latency_ms,
        }

    # Deterministic: eq(A,B) for each structural symmetric pair (expression-hash verified)
    sym_pairs = enriched.get("symmetric_pairs", [])
    sym_pair_frozensets = {frozenset([sp["refA"], sp["refB"]]) for sp in sym_pairs}
    det_candidates = [_make_eq_candidate(sp["refA"], sp["refB"]) for sp in sym_pairs]

    # LLM: additional suggestions — only ask when sym_pairs give the LLM useful context.
    # Without structural equality evidence, LLM generates unreliable ordering invariants
    # that cause net regression (wrong bounds at loop termination, etc.).
    if sym_pairs:
        user_prompt = build_stage0_prompt(enriched)
        text, tokens, latency_ms = _call_llm(client, user_prompt, enriched)
        llm_raw = parse_invariant_response(text)
        llm_safe = _filter_candidates(llm_raw, "stage0", request_id)
    else:
        llm_safe = []
        tokens, latency_ms = 0, 0.0
        print(f"[inv_sidecar] stage0 {request_id}: no sym_pairs, skipping LLM")

    # Deduplicate: drop LLM eq(A,B) already covered by the deterministic sym_pair candidates
    llm_novel = []
    for c in llm_safe:
        ast = c.get("predicate_ast", c)
        if ast.get("form") == "eq" and len(ast.get("args", [])) == 2:
            a, b = ast["args"]
            if (a.get("form") == "ref" and b.get("form") == "ref"
                    and frozenset([a["ref"], b["ref"]]) in sym_pair_frozensets):
                continue  # already injected deterministically
        llm_novel.append(c)

    candidates = det_candidates + llm_novel
    print(f"[inv_sidecar] stage0 {request_id}: {len(det_candidates)} sym_pair + "
          f"{len(llm_novel)} LLM = {len(candidates)} candidates "
          f"({tokens} tokens, {latency_ms:.0f}ms)")
    return {
        "type": "ic3_invariant_response",
        "request_id": request_id,
        "candidates": candidates,
        "_token_count": tokens,
        "_latency_ms": latency_ms,
    }


def handle_stage2_request(client: LLMClient, request: dict) -> dict:
    """
    Mid-run guidance: CTI cluster + frame clause evidence → LLM → Type1/2/3 candidates.

    Only runs the LLM call when structural symmetric pairs are present: without that
    evidence, Stage 2 ordering suggestions are unreliable and cause net regression
    (extra CEGAR rounds from wrong invariants exceed the rounds saved by correct ones).
    """
    request_id = request.get("request_id", "unknown")
    enriched = _enrich_request_with_btor2(request)
    trigger = request.get("trigger", "?")

    sym_pairs = enriched.get("symmetric_pairs", [])
    if not sym_pairs:
        print(f"[inv_sidecar] stage2 {request_id} ({trigger}): no sym_pairs, skipping LLM")
        return {
            "type": "ic3_invariant_response",
            "request_id": request_id,
            "candidates": [],
        }

    # Skip Stage 2 LLM when there are 0 CTIs: T2_plateau with no counterexamples
    # gives the LLM nothing concrete to reason about (tends to return 0 useful candidates).
    proof_state = enriched.get("proof_state", {})
    cti_count = proof_state.get("total_cti_count", -1)
    if cti_count == 0:
        print(f"[inv_sidecar] stage2 {request_id} ({trigger}): 0 CTIs, skipping LLM")
        return {
            "type": "ic3_invariant_response",
            "request_id": request_id,
            "candidates": [],
        }

    # Inform the LLM about sym_pair invariants already injected at Stage 0
    already_injected = [f"eq({sp['refA']}, {sp['refB']})" for sp in sym_pairs]
    if already_injected and not enriched.get("previously_injected"):
        enriched = dict(enriched)
        enriched["previously_injected"] = already_injected

    user_prompt = build_stage2_prompt(enriched)
    text, tokens, latency_ms = _call_llm(client, user_prompt, enriched)
    candidates = parse_invariant_response(text)
    # Same safety filter as Stage 0: reject const bounds and complex subexpressions
    candidates = _filter_candidates(candidates, "stage2", request_id)
    print(f"[inv_sidecar] stage2 {request_id} ({trigger}): {len(candidates)} candidates "
          f"({tokens} tokens, {latency_ms:.0f}ms)")
    return {
        "type": "ic3_invariant_response",
        "request_id": request_id,
        "candidates": candidates,
        "_token_count": tokens,
        "_latency_ms": latency_ms,
    }
