#!/usr/bin/env python3
"""
End-to-end test for IC3 Frame v1 LLM sidecar.

Usage:
    python3 test_sidecar.py
    python3 test_sidecar.py --with-llm   # requires DEEPSEEK_API_KEY
    python3 test_sidecar.py --client-only
"""

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_client_direct():
    print("=== Test: DeepSeekClient direct API call ===\n")

    from llm_worker.deepseek_client import DeepSeekClient, get_api_key

    api_key = get_api_key()
    if not api_key:
        print("  SKIP: No API key set")
        return

    client = DeepSeekClient(api_key)
    prompt = '{"status": "ok", "message": "hello from LLM"}'
    response, tokens, latency_ms = client.call(
        f'Reply with EXACTLY this JSON and nothing else:\n{prompt}'
    )
    data = json.loads(response)
    assert data.get("status") == "ok"
    print(f"  PASS ({tokens} tokens, {latency_ms:.0f}ms)")


def test_sidecar_with_llm():
    print("\n=== Test: Sidecar IC3 Frame v1 pipeline ===\n")

    from llm_worker.deepseek_client import get_api_key

    if not get_api_key():
        print("  SKIP: No API key set")
        return

    tmpdir = tempfile.mkdtemp(prefix="pono_llm_test_")
    req_path = os.path.join(tmpdir, "requests.jsonl")
    resp_path = os.path.join(tmpdir, "responses.jsonl")
    log_path = os.path.join(tmpdir, "log.jsonl")
    ctx_path = os.path.join(tmpdir, "benchmark_context.json")

    with open(ctx_path, "w") as f:
        json.dump({
            "schema_version": 1,
            "type": "benchmark_context",
            "benchmark": "test",
            "bad_property": "b0",
            "symbol_registry": {
                "state1": {"kind": "state", "width": 1, "btor2_line": 1, "verilog": "valid"}
            },
        }, f)

    request = {
        "schema_version": 1,
        "type": "ic3_frame_request",
        "frame_idx": 3,
        "cti_id": "cti_f3_state1=true;",
        "attempt": 1,
        "max_attempts": 2,
        "parallel_samples": 1,
        "reasoning_effort": "none",
        "benchmark_context_path": ctx_path,
        "symbol_registry": {
            "state1": {"kind": "state", "width": 1, "btor2_line": 1, "verilog": "valid"}
        },
        "cti": {
            "cube": {
                "form": "and",
                "literals": [
                    {
                        "id": 0,
                        "form": "literal",
                        "atom": {"ref": "state1", "op": "eq", "rhs": "1"},
                        "polarity": True,
                    }
                ],
            }
        },
        "frame_snapshot": {"frame_idx": 3, "clauses": []},
        "feedback": [],
    }

    from llm_worker.jsonl_protocol import write_request_test
    write_request_test(req_path, request)

    sidecar_path = Path(__file__).parent / "llm_worker" / "sidecar.py"
    prompt_dir = Path(__file__).parent / "llm_worker" / "prompts"

    result = subprocess.run(
        [
            sys.executable, str(sidecar_path),
            "--req-path", req_path,
            "--resp-path", resp_path,
            "--log-path", log_path,
            "--poll-interval", "0.5",
            "--max-requests", "1",
            "--prompt-dir", str(prompt_dir),
        ],
        capture_output=True, text=True, timeout=120,
        env=os.environ.copy(),
    )

    print(result.stdout[-500:] if result.stdout else "")
    if result.stderr:
        print(result.stderr[-500:])

    assert os.path.exists(resp_path), "No response file"
    with open(resp_path) as f:
        line = f.readline().strip()
        assert line, "Empty response"
        resp = json.loads(line)
        assert resp.get("type") == "ic3_frame_response"
        assert resp.get("source_cti_id") == request["cti_id"]
        print(f"  Response disjuncts: {resp.get('block_disjuncts')}")
        print("  PASS")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true")
    parser.add_argument("--client-only", action="store_true")
    args = parser.parse_args()

    if args.client_only:
        test_client_direct()
        return 0
    if args.with_llm:
        test_client_direct()
        test_sidecar_with_llm()
    else:
        print("Dry-run: use --with-llm for API tests")
    return 0


if __name__ == "__main__":
    exit(main())
