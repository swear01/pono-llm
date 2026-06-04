#!/usr/bin/env python3
"""
Pono LLM Sidecar -- IC3 Frame v1 online integration.

Reads ic3_frame_request from JSONL (written by Pono C++),
calls LLM API with parallel K samples,
writes ic3_frame_response lines (polled by Pono C++).

Usage:
    python sidecar.py --req-path /tmp/pono_llm_requests.jsonl \
                      --resp-path /tmp/pono_llm_responses.jsonl \
                      --log-path /tmp/pono_llm_log.jsonl
"""

import argparse
import hashlib
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from deepseek_client import DeepSeekClient
from ic3_frame_schema import normalize_response, validate_request, validate_response
from jsonl_protocol import append_log_line, read_requests_batch, write_response
from prompt_format import (
    format_cti_batch_all,
    format_cti_literals,
    format_frame_snapshot,
)

V1_REQUEST_TYPES = frozenset({"ic3_frame_request", "ic3_frame_batch_request"})


def load_prompt(prompt_dir: str) -> str:
    path = Path(prompt_dir) / "ic3_frame_v1.txt"
    if path.exists():
        return path.read_text()
    return ""


def load_benchmark_context(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def build_batch_user_prompt(
    req: dict,
    benchmark_ctx: dict,
    sample_id: int,
    snapshot_max_clauses: int = 0,
) -> str:
    batch_id = req.get("batch_id", "")
    parts = [
        f"batch_id: {batch_id}",
        f"frame_idx: {req.get('frame_idx')}",
        f"attempt: {req.get('attempt', 1)}",
        f"sample_id: {sample_id}",
        "",
        format_cti_batch_all(req.get("cti_entries") or []),
        "",
        format_frame_snapshot(
            req.get("frame_snapshot", {}),
            max_clauses=snapshot_max_clauses,
        ),
    ]
    feedback = req.get("feedback") or []
    if feedback:
        parts.extend(["", "Previous failures (feedback):", json.dumps(feedback, indent=2)])
    if benchmark_ctx:
        parts.extend([
            "",
            "Benchmark context (reference):",
            json.dumps({
                "benchmark": benchmark_ctx.get("benchmark"),
                "bad_property": benchmark_ctx.get("bad_property"),
            }, separators=(",", ":")),
        ])
    parts.extend([
        "",
        "Respond with ic3_frame_response JSON only.",
        "Output exactly ONE block_disjuncts (one OR-clause) covering all listed CTI cubes.",
        f"Set source_cti_id to {batch_id!r} and sample_id to {sample_id}.",
    ])
    return "\n".join(parts)


def build_user_prompt(
    req: dict,
    benchmark_ctx: dict,
    sample_id: int,
    snapshot_max_clauses: int = 0,
) -> str:
    if req.get("type") == "ic3_frame_batch_request":
        return build_batch_user_prompt(
            req, benchmark_ctx, sample_id, snapshot_max_clauses=snapshot_max_clauses
        )
    parts = [
        f"frame_idx: {req.get('frame_idx')}",
        f"cti_id: {req.get('cti_id')}",
        f"attempt: {req.get('attempt', 1)}",
        f"sample_id: {sample_id}",
        "",
        format_cti_literals(req.get("cti", {})),
        "",
        format_frame_snapshot(
            req.get("frame_snapshot", {}),
            max_clauses=snapshot_max_clauses,
        ),
    ]
    feedback = req.get("feedback") or []
    if feedback:
        parts.extend(["", "Previous failures (feedback):", json.dumps(feedback, indent=2)])
    if benchmark_ctx:
        parts.extend([
            "",
            "Benchmark context (reference):",
            json.dumps({
                "benchmark": benchmark_ctx.get("benchmark"),
                "bad_property": benchmark_ctx.get("bad_property"),
            }, separators=(",", ":")),
        ])
    parts.extend([
        "",
        "Respond with ic3_frame_response JSON only.",
        f"Set source_cti_id to {req.get('cti_id')!r} and sample_id to {sample_id}.",
    ])
    return "\n".join(parts)


def process_request(
    client: DeepSeekClient,
    req: dict,
    system_prompt: str,
    snapshot_max_clauses: int = 0,
) -> tuple:
    ok, err = validate_request(req)
    if not ok:
        raise ValueError(f"Invalid request: {err}")

    benchmark_ctx = load_benchmark_context(req.get("benchmark_context_path", ""))
    parallel_samples = int(req.get("parallel_samples", 1))
    reasoning_effort = req.get("reasoning_effort", "none")
    model_name = req.get("model") or None
    source_id = req.get("batch_id") or req.get("cti_id", "")
    attempt = int(req.get("attempt", 1))
    if req.get("type") == "ic3_frame_batch_request":
        temperature = float(req.get("temperature", 0.5))
    else:
        temperature = float(req.get("temperature", 0.8))

    total_tokens = 0
    total_latency = 0.0

    def _call_sample(sample_id: int):
        user_prompt = build_user_prompt(
            req, benchmark_ctx, sample_id, snapshot_max_clauses=snapshot_max_clauses
        )
        text, tokens, latency_ms = client.call(
            user_prompt,
            system_prompt=system_prompt,
            model_name=model_name,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
        )
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = {"block_disjuncts": [], "rationale": "LLM response was not valid JSON"}
        normalized = normalize_response(raw, source_id, sample_id, attempt)
        valid, verr = validate_response(normalized)
        if not valid:
            normalized["rationale"] = f"{normalized.get('rationale', '')} [{verr}]"
        return sample_id, normalized, tokens, latency_ms

    responses = []
    with ThreadPoolExecutor(max_workers=parallel_samples) as pool:
        futs = [pool.submit(_call_sample, sid) for sid in range(parallel_samples)]
        by_id = {}
        for fut in as_completed(futs):
            sample_id, normalized, tokens, latency_ms = fut.result()
            by_id[sample_id] = (normalized, tokens, latency_ms)
        for sample_id in range(parallel_samples):
            normalized, tokens, latency_ms = by_id[sample_id]
            responses.append(normalized)
            total_tokens += tokens
            total_latency += latency_ms

    return responses, total_tokens, total_latency / max(parallel_samples, 1)


def handle_one_request(
    client: DeepSeekClient,
    request: dict,
    system_prompt: str,
    resp_path: str,
    log_path: str,
    write_lock: threading.Lock,
    request_index: int,
    snapshot_max_clauses: int = 0,
) -> tuple[int, int, float]:
    """Process one request line; thread-safe writes to resp/log files."""
    benchmark_ctx = load_benchmark_context(request.get("benchmark_context_path", ""))
    user_prompt = build_user_prompt(
        request, benchmark_ctx, 0, snapshot_max_clauses=snapshot_max_clauses
    )
    user_prompt_bytes = len(user_prompt.encode("utf-8"))
    system_prompt_bytes = len(system_prompt.encode("utf-8"))

    responses, token_count, latency_ms = process_request(
        client, request, system_prompt, snapshot_max_clauses=snapshot_max_clauses
    )
    with write_lock:
        for resp in responses:
            write_response(resp_path, resp)
        log_entry = {
            "timestamp": time.time(),
            "request_index": request_index,
            "request_type": request.get("type"),
            "batch_id": request.get("batch_id"),
            "cti_id": request.get("cti_id"),
            "cti_total": len(request.get("cti_entries") or []),
            "parallel_samples": len(responses),
            "token_count": token_count,
            "latency_ms": latency_ms,
            "user_prompt_bytes": user_prompt_bytes,
            "system_prompt_bytes": system_prompt_bytes,
            "prompt_hash": hashlib.sha256(
                json.dumps(request, sort_keys=True).encode()
            ).hexdigest()[:16],
        }
        stats = getattr(client, "last_call_stats", None) or {}
        if stats:
            log_entry.update({
                "thinking_mode": stats.get("thinking_mode"),
                "prompt_tokens": stats.get("prompt_tokens"),
                "completion_tokens": stats.get("completion_tokens"),
                "reasoning_chars": stats.get("reasoning_chars"),
            })
        append_log_line(log_path, log_entry)
    return len(responses), token_count, latency_ms


def drain_completed(
    inflight: dict[Future, int],
) -> list[tuple[int, int, float, Optional[Exception]]]:
    """Collect finished futures. Returns (responses, tokens, latency, error)."""
    done: list[tuple[int, int, float, Optional[Exception]]] = []
    finished = [fut for fut in list(inflight) if fut.done()]
    for fut in finished:
        req_index = inflight.pop(fut)
        try:
            n_resp, tokens, lat = fut.result()
            done.append((n_resp, tokens, lat, None))
            print(
                f"[sidecar] req #{req_index}: wrote {n_resp} responses, "
                f"{tokens} tokens, {lat:.0f}ms avg"
            )
        except Exception as e:
            done.append((0, 0, 0.0, e))
            print(f"[sidecar] req #{req_index} error: {e}")
            import traceback
            traceback.print_exc()
    return done


def main():
    parser = argparse.ArgumentParser(description="Pono LLM Sidecar (IC3 Frame v1)")
    parser.add_argument("--req-path", default="/tmp/pono_llm_requests.jsonl")
    parser.add_argument("--resp-path", default="/tmp/pono_llm_responses.jsonl")
    parser.add_argument("--log-path", default="/tmp/pono_llm_log.jsonl")
    parser.add_argument("--prompt-dir", default="llm_worker/prompts/")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-requests", type=int, default=0,
                        help="Max total requests to process (0=unlimited)")
    parser.add_argument("--max-inflight-requests", type=int, default=4,
                        help="Max concurrent request lines in flight")
    parser.add_argument("--snapshot-max-clauses", type=int, default=0,
                        help="Max frame clauses in prompt (0=all, compact line format)")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[sidecar] ERROR: DEEPSEEK_API_KEY not set")
        return 1

    client = DeepSeekClient(api_key, model_name=args.model or None)
    system_prompt = load_prompt(args.prompt_dir)
    write_lock = threading.Lock()

    print(f"[sidecar] IC3 Frame v1, polling {args.req_path}")
    print(f"[sidecar] Writing responses to {args.resp_path}")
    print(f"[sidecar] max_inflight_requests={args.max_inflight_requests}")
    print(f"[sidecar] snapshot_max_clauses={args.snapshot_max_clauses}")

    processed_count = 0
    submitted_count = 0
    last_position = 0
    inflight: dict[Future, int] = {}

    try:
        with ThreadPoolExecutor(max_workers=args.max_inflight_requests) as request_pool:
            while True:
                for _, _, _, err in drain_completed(inflight):
                    if err is None:
                        processed_count += 1

                if args.max_requests > 0 and processed_count >= args.max_requests:
                    if not inflight:
                        break

                slots = args.max_inflight_requests - len(inflight)
                if slots > 0:
                    if args.max_requests > 0:
                        slots = min(slots, args.max_requests - submitted_count)
                    if slots > 0:
                        try:
                            requests, last_position = read_requests_batch(
                                args.req_path, last_position, max_lines=slots
                            )
                        except FileNotFoundError:
                            requests = []

                        for request in requests:
                            req_type = request.get("type", "")
                            if req_type not in V1_REQUEST_TYPES:
                                print(f"[sidecar] Skipping non-v1 request type: {req_type}")
                                submitted_count += 1
                                processed_count += 1
                                continue

                            req_index = submitted_count
                            submitted_count += 1
                            fut = request_pool.submit(
                                handle_one_request,
                                client,
                                request,
                                system_prompt,
                                args.resp_path,
                                args.log_path,
                                write_lock,
                                req_index,
                                args.snapshot_max_clauses,
                            )
                            inflight[fut] = req_index

                if args.max_requests > 0 and processed_count >= args.max_requests and not inflight:
                    break

                time.sleep(args.poll_interval)

            while inflight:
                for _, _, _, err in drain_completed(inflight):
                    if err is None:
                        processed_count += 1
                if inflight:
                    time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print(f"\n[sidecar] Stopped after {processed_count} requests")

    return 0


if __name__ == "__main__":
    exit(main())
