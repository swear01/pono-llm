#!/usr/bin/env python3
"""
Pono LLM Sidecar — Semantic Invariant Guidance.

Reads ic3_stage0_request / ic3_stage2_request from JSONL (written by pono C++),
calls LLM API, writes ic3_invariant_response lines back.

Usage:
    python sidecar.py --req-path /tmp/pono_llm_requests.jsonl \
                      --resp-path /tmp/pono_llm_responses.jsonl \
                      --log-path /tmp/pono_llm_log.jsonl
"""

import argparse
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from env_config import load_env, require_api_key, get_llm_provider, default_model
from invariant_sidecar import handle_stage0_request, handle_stage2_request
from llm_client import LLMClient, create_llm_client
from jsonl_protocol import append_log_line, read_requests_batch, write_response

SUPPORTED_REQUEST_TYPES = frozenset({
    "ic3_stage0_request",
    "ic3_stage2_request",
})


def load_benchmark_context(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_request(
    client: LLMClient,
    request: dict,
    resp_path: str,
    log_path: str,
    write_lock: threading.Lock,
    request_index: int,
) -> tuple[int, int, float]:
    """Route one request by type, write response + log. Thread-safe."""
    req_type = request.get("type", "")
    request_id = request.get("request_id", f"req_{request_index}")
    t_start = time.time()

    try:
        if req_type == "ic3_stage0_request":
            resp = handle_stage0_request(client, request)
        elif req_type == "ic3_stage2_request":
            resp = handle_stage2_request(client, request)
        else:
            raise ValueError(f"Unknown request type: {req_type}")
        token_count = resp.pop("_token_count", 0)
        latency_ms = resp.pop("_latency_ms", (time.time() - t_start) * 1000)
    except NotImplementedError as e:
        print(f"[sidecar] req #{request_index} ({req_type}): not implemented — {e}")
        resp = {
            "type": "ic3_invariant_response",
            "request_id": request_id,
            "candidates": [],
            "error": str(e),
        }
        token_count = 0
        latency_ms = (time.time() - t_start) * 1000
    except Exception as e:
        print(f"[sidecar] req #{request_index} ({req_type}): error — {e}")
        import traceback
        traceback.print_exc()
        resp = {
            "type": "ic3_invariant_response",
            "request_id": request_id,
            "candidates": [],
            "error": str(e),
        }
        token_count = 0
        latency_ms = (time.time() - t_start) * 1000

    with write_lock:
        write_response(resp_path, resp)
        append_log_line(log_path, {
            "timestamp": time.time(),
            "request_index": request_index,
            "request_type": req_type,
            "request_id": request_id,
            "token_count": token_count,
            "latency_ms": latency_ms,
        })

    return 1, token_count, latency_ms


def drain_completed(
    inflight: dict[Future, int],
) -> list[tuple[int, int, float, Optional[Exception]]]:
    """Collect finished futures. Returns (n_resp, tokens, latency, error)."""
    done: list[tuple[int, int, float, Optional[Exception]]] = []
    finished = [fut for fut in list(inflight) if fut.done()]
    for fut in finished:
        req_index = inflight.pop(fut)
        try:
            n_resp, tokens, lat = fut.result()
            done.append((n_resp, tokens, lat, None))
            print(f"[sidecar] req #{req_index}: done, {tokens} tokens, {lat:.0f}ms")
        except Exception as e:
            done.append((0, 0, 0.0, e))
            print(f"[sidecar] req #{req_index} error: {e}")
    return done


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pono LLM Sidecar (Semantic Invariant)")
    parser.add_argument("--req-path", default="/tmp/pono_llm_requests.jsonl")
    parser.add_argument("--resp-path", default="/tmp/pono_llm_responses.jsonl")
    parser.add_argument("--log-path", default="/tmp/pono_llm_log.jsonl")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-requests", type=int, default=0,
                        help="Max total requests (0=unlimited)")
    parser.add_argument("--max-inflight", type=int, default=4,
                        help="Max concurrent requests")
    parser.add_argument("--model", default="")
    parser.add_argument("--provider", default="",
                        choices=["", "deepseek", "openrouter"])
    args = parser.parse_args()

    env_path = load_env()
    if env_path:
        print(f"[sidecar] loaded env from {env_path}")

    try:
        provider = get_llm_provider(args.provider or None)
        api_key = require_api_key(provider)
        client = create_llm_client(
            provider=provider,
            api_key=api_key,
            model_name=args.model or default_model(provider),
        )
    except (RuntimeError, ValueError) as e:
        print(f"[sidecar] ERROR: {e}")
        return 1

    write_lock = threading.Lock()
    print(f"[sidecar] Semantic Invariant mode, polling {args.req_path}")
    print(f"[sidecar] Writing responses to {args.resp_path}")

    processed_count = 0
    submitted_count = 0
    last_position = 0
    inflight: dict[Future, int] = {}

    try:
        with ThreadPoolExecutor(max_workers=args.max_inflight) as pool:
            while True:
                for _, _, _, err in drain_completed(inflight):
                    if err is None:
                        processed_count += 1

                if args.max_requests > 0 and processed_count >= args.max_requests:
                    if not inflight:
                        break

                slots = args.max_inflight - len(inflight)
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
                            if req_type not in SUPPORTED_REQUEST_TYPES:
                                print(f"[sidecar] skipping unsupported type: {req_type}")
                                submitted_count += 1
                                processed_count += 1
                                continue

                            req_index = submitted_count
                            submitted_count += 1
                            fut = pool.submit(
                                dispatch_request,
                                client, request,
                                args.resp_path, args.log_path,
                                write_lock, req_index,
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
