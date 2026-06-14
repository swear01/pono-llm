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
_HOT_DEPTH = 4


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
    return enriched


def _call_llm(client: LLMClient, user_prompt: str, request: dict) -> tuple[str, int, float]:
    """Wrapper around client.call with request-level overrides."""
    model_name = request.get("model") or None
    reasoning_effort = request.get("reasoning_effort", "low")
    text, tokens, latency_ms = client.call(
        user_prompt,
        system_prompt=INVARIANT_SYSTEM_PROMPT,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        max_tokens=_MAX_TOKENS,
    )
    return text, tokens, latency_ms


def handle_stage0_request(client: LLMClient, request: dict) -> dict:
    """
    Pre-flight invariant generation.

    Reads RTL semantic bundle from the request (btor2_path → parsed hot_variables
    and transition_sketch) and asks LLM for invariant candidates.
    """
    request_id = request.get("request_id", "unknown")
    enriched = _enrich_request_with_btor2(request)
    user_prompt = build_stage0_prompt(enriched)
    text, tokens, latency_ms = _call_llm(client, user_prompt, enriched)
    candidates = parse_invariant_response(text)
    print(f"[inv_sidecar] stage0 {request_id}: {len(candidates)} candidates "
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
    """
    request_id = request.get("request_id", "unknown")
    enriched = _enrich_request_with_btor2(request)
    user_prompt = build_stage2_prompt(enriched)
    text, tokens, latency_ms = _call_llm(client, user_prompt, enriched)
    candidates = parse_invariant_response(text)
    trigger = request.get("trigger", "?")
    print(f"[inv_sidecar] stage2 {request_id} ({trigger}): {len(candidates)} candidates "
          f"({tokens} tokens, {latency_ms:.0f}ms)")
    return {
        "type": "ic3_invariant_response",
        "request_id": request_id,
        "candidates": candidates,
        "_token_count": tokens,
        "_latency_ms": latency_ms,
    }
