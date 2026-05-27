#!/usr/bin/env python3
"""
Pono LLM Sidecar -- Asynchronous DeepSeek V4 Pro integration for IC3 lemma generalization.

Reads CTI context requests from a JSONL file (written by Pono C++),
calls DeepSeek V4 Pro API for lemma generalization suggestions,
writes candidates back to a JSONL response file (polled by Pono C++).

Usage:
    python sidecar.py --req-path /tmp/pono_llm_requests.jsonl \
                      --resp-path /tmp/pono_llm_responses.jsonl \
                      --log-path /tmp/pono_llm_log.jsonl \
                      --candidate-language cube-subset \
                      --prompt-dir llm_worker/prompts/
"""

import argparse
import json
import os
import time
import hashlib
from pathlib import Path

from deepseek_client import DeepSeekClient
from jsonl_protocol import read_request, write_response, CTIContext, LLMCandidate


def load_prompt(name: str, prompt_dir: str) -> str:
    path = Path(prompt_dir) / f"{name}.txt"
    if path.exists():
        return path.read_text()
    return ""


def build_cube_subset_prompt(ctx: CTIContext, template: str) -> str:
    """Build a prompt for cube-subset generalization."""
    lit_lines = []
    for lit in ctx["literals"]:
        lit_lines.append(f"  {lit['varname']} = {lit['value']}")
    literals_text = "\n".join(lit_lines)

    prop_name = ctx.get("property", "(unknown)")
    frame_idx = ctx.get("frame_idx", 0)

    if template:
        return template.format(
            property_name=prop_name,
            frame_idx=frame_idx,
            literals=literals_text,
        )

    return f"""You are a hardware verification assistant. Given a counterexample-to-induction (CTI) cube from a PDR/IC3 model checker, suggest which literals to KEEP and which to DROP to form a generalized blocking clause.

Property being checked: {prop_name}
CTI found at frame: {frame_idx}

CTI cube literals:
{literals_text}

Analyze the semantic relationships among these signals and identify:
1. Which literals represent the core semantic condition (KEEP these)
2. Which literals are incidental details like exact counter values, specific FSM states, or datapath artifacts (DROP these)

Respond with a JSON object:
{{
  "type": "cube_subset",
  "frame_hint": {frame_idx},
  "keep_literals": ["varname = value", ...],
  "drop_literals": ["varname = value", ...],
  "rationale": "Brief explanation"
}}"""


def build_multi_cti_prompt(ctx: CTIContext) -> str:
    """Build a prompt for multi-CTI batch generalization.
    The request has cti_contexts array with multiple CTI cubes from the same frame."""
    frame_idx = ctx.get("frame_idx", 0)
    batch_size = ctx.get("batch_size", len(ctx.get("cti_contexts", [])))
    cti_contexts = ctx.get("cti_contexts", [])

    cti_blocks = []
    for i, cti in enumerate(cti_contexts, 1):
        lit_lines = [f"    {l['varname']} = {l['value']}" for l in cti["literals"]]
        cti_blocks.append(
            f"CTI #{i} ({len(cti['literals'])} literals):\n" + "\n".join(lit_lines)
        )
    cti_text = "\n\n".join(cti_blocks)

    return f"""You are a hardware verification assistant. Below are {batch_size} counterexample-to-induction (CTI) cubes from frame {frame_idx} of a PDR/IC3 model checker. All CTIs come from the same frame and violate the same property.

Your task: identify the COMMON CORE literals that appear across all CTIs. These common literals likely represent the essential unreachable condition. Drop literals that differ across CTIs or are incidental details.

CTI cubes:
{cti_text}

Guidelines:
- Literals present in ALL CTIs with identical values: likely CORE → KEEP
- Literals present in some CTIs but not others: incidental → DROP
- Literals with different values across CTIs: data-dependent → DROP
- Primary input literals: usually DROP unless they gate critical state transitions

Respond with a JSON object containing keep_literals and drop_literals in the EXACT format shown in the CTIs:
{{
  "type": "cube_subset",
  "frame_hint": {frame_idx},
  "keep_literals": ["varname = value", ...],
  "drop_literals": ["varname = value", ...],
  "rationale": "Brief explanation of which patterns are core vs incidental"
}}"""


def process_request(
    client: DeepSeekClient,
    ctx: CTIContext,
    candidate_language: str,
    prompt_dir: str,
    default_model: str = "",
) -> tuple:
    """Process a single CTI context through the LLM.

    Returns:
        (candidates_list, token_count, latency_ms)
        candidates_list is always a list (possibly of one element).
    """
    # Template-guided mode: expects a full context bundle
    if candidate_language == "template-guided":
        from template_prompt import build_template_prompt
        prompt = build_template_prompt(ctx)
        response_text, token_count, latency_ms = client.call(
            prompt, model_name=default_model or None
        )
        try:
            result = json.loads(response_text)
            candidates = result.get("candidates", [])
            # Fallback: if LLM returned a single object (non-compliant), wrap it
            if not candidates and "lemma" in result:
                candidates = [result]
            for cand in candidates:
                cand.setdefault("type", "template_lemma")
        except (json.JSONDecodeError, KeyError, IndexError):
            candidates = [{
                "type": "template_lemma",
                "lemma": "",
                "schema": "unknown",
                "rationale": "LLM response was not valid JSON",
            }]
        return candidates, token_count, latency_ms

    # Detect multi-CTI batch requests
    if "cti_contexts" in ctx:
        prompt = build_multi_cti_prompt(ctx)
    elif candidate_language == "cube-subset":
        template = load_prompt("cube_subset", prompt_dir)
        prompt = build_cube_subset_prompt(ctx, template)
    elif candidate_language == "qf-smt":
        template = load_prompt("qf_smt", prompt_dir)
        prompt = template.format(**ctx) if template else str(ctx)
    else:
        raise ValueError(f"Unknown candidate language: {candidate_language}")

    model_name = ctx.get("model", "") or default_model or None
    response_text, token_count, latency_ms = client.call(prompt, model_name=model_name)

    try:
        candidate = json.loads(response_text)
        candidate.setdefault("type", "cube_subset")
        candidate.setdefault("frame_hint", ctx.get("frame_idx", 0))
        candidate.setdefault("keep_literals", [])
        candidate.setdefault("drop_literals", [])
        candidate.setdefault("used_symbols", [])
        candidate.setdefault("formula", "")
        candidate.setdefault("rationale", "")
    except json.JSONDecodeError:
        candidate = {
            "type": "cube_subset",
            "frame_hint": ctx.get("frame_idx", 0),
            "keep_literals": [],
            "drop_literals": [],
            "rationale": "LLM response was not valid JSON",
        }

    return [candidate], token_count, latency_ms


def main():
    parser = argparse.ArgumentParser(description="Pono LLM Sidecar")
    parser.add_argument(
        "--req-path",
        default="/tmp/pono_llm_requests.jsonl",
        help="Path to JSONL request file (written by Pono)",
    )
    parser.add_argument(
        "--resp-path",
        default="/tmp/pono_llm_responses.jsonl",
        help="Path to JSONL response file (polled by Pono)",
    )
    parser.add_argument(
        "--log-path",
        default="/tmp/pono_llm_log.jsonl",
        help="Path to JSONL log file",
    )
    parser.add_argument(
        "--candidate-language",
        default="cube-subset",
        choices=["cube-subset", "qf-smt", "predicate-relation", "template-guided"],
        help="LLM output restriction level",
    )
    parser.add_argument(
        "--prompt-dir",
        default="llm_worker/prompts/",
        help="Directory containing prompt templates",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=0,
        help="Maximum number of requests to process (0 = unlimited)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model name override (default: use model from request or deepseek-v4-pro)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("[sidecar] ERROR: DEEPSEEK_API_KEY or OPENROUTER_API_KEY environment variable not set")
        return 1

    client = DeepSeekClient(api_key, model_name=args.model or None)

    print(f"[sidecar] Started, polling {args.req_path}")
    print(f"[sidecar] Writing responses to {args.resp_path}")
    print(f"[sidecar] Logging to {args.log_path}")
    print(f"[sidecar] Candidate language: {args.candidate_language}")

    processed_count = 0
    last_position = 0

    try:
        while True:
            if args.max_requests > 0 and processed_count >= args.max_requests:
                print(f"[sidecar] Reached max requests ({args.max_requests}), exiting")
                break

            try:
                request, new_position = read_request(args.req_path, last_position)
            except FileNotFoundError:
                time.sleep(args.poll_interval)
                continue

            if request is None:
                time.sleep(args.poll_interval)
                continue

            last_position = new_position
            print(f"[sidecar] Processing request #{processed_count + 1}")

            try:
                candidates, token_count, latency_ms = process_request(
                    client,
                    request,
                    args.candidate_language,
                    args.prompt_dir,
                    default_model=args.model,
                )

                for cand in candidates:
                    write_response(args.resp_path, cand)
                candidate = candidates[0] if candidates else {}

                # Log the interaction
                log_entry = {
                    "timestamp": time.time(),
                    "request_index": processed_count,
                    "prompt_hash": hashlib.sha256(
                        json.dumps(request, sort_keys=True).encode()
                    ).hexdigest()[:16],
                    "response_hash": hashlib.sha256(
                        json.dumps(candidate, sort_keys=True).encode()
                    ).hexdigest()[:16],
                    "token_count": token_count,
                    "latency_ms": latency_ms,
                    "candidate_count": len(candidates),
                    "candidate_type": candidate.get("type"),
                    "keep_count": len(candidate.get("keep_literals", [])),
                    "drop_count": len(candidate.get("drop_literals", [])),
                }
                with open(args.log_path, "a") as log_f:
                    log_f.write(json.dumps(log_entry) + "\n")

                processed_count += 1
                print(
                    f"[sidecar] Response written ({len(candidates)} candidates), "
                    f"{token_count} tokens, {latency_ms:.0f}ms latency"
                )

            except Exception as e:
                print(f"[sidecar] Error processing request: {e}")
                import traceback
                traceback.print_exc()
                processed_count += 1
                time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print(f"\n[sidecar] Stopped after processing {processed_count} requests")

    return 0


if __name__ == "__main__":
    exit(main())
