#!/usr/bin/env python3
"""
End-to-end test for LLM sidecar with a real API call.

Usage:
    # Dry-run (no API key needed)
    python3 test_sidecar.py

    # With real LLM API call
    DEEPSEEK_API_KEY=sk-or-xxx python3 test_sidecar.py --with-llm

    # Test just the client directly
    DEEPSEEK_API_KEY=sk-or-xxx python3 test_sidecar.py --client-only
"""

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_client_direct():
    """Test DeepSeekClient directly with a real API call."""
    print("=== Test: DeepSeekClient direct API call ===\n")

    from llm_worker.deepseek_client import DeepSeekClient, get_api_key

    api_key = get_api_key()
    if not api_key:
        print("  SKIP: No API key set (DEEPSEEK_API_KEY or OPENROUTER_API_KEY)")
        return

    client = DeepSeekClient(api_key)
    print(f"  Provider: {client.provider}")
    print(f"  Model: {client.model_name}")
    print(f"  Base URL: {client.base_url}")

    prompt = """You are testing an API connection. Reply with EXACTLY this JSON:
{"status": "ok", "message": "hello from LLM"}
Do not include markdown fencing, just the raw JSON."""

    try:
        response, tokens, latency_ms = client.call(prompt)
        print(f"\n  Tokens: {tokens}")
        print(f"  Latency: {latency_ms:.0f}ms")
        print(f"  Raw response: {response}")

        data = json.loads(response)
        assert data.get("status") == "ok"
        print("  Status: ok")
        print("  PASS")
    except Exception as e:
        print(f"  FAIL: {e}")
        raise


def test_sidecar_with_llm():
    """Test the full sidecar pipeline with a real LLM call."""
    print("\n=== Test: Sidecar pipeline with real LLM ===\n")

    from llm_worker.deepseek_client import get_api_key

    api_key = get_api_key()
    if not api_key:
        print("  SKIP: No API key set")
        return

    tmpdir = tempfile.mkdtemp(prefix="pono_llm_test_")
    req_path = os.path.join(tmpdir, "requests.jsonl")
    resp_path = os.path.join(tmpdir, "responses.jsonl")
    log_path = os.path.join(tmpdir, "log.jsonl")

    # Write a test CTI request
    ctx = {
        "frame_idx": 3,
        "property": "b0",
        "literals": [
            {"varname": "valid", "value": "true"},
            {"varname": "ready", "value": "false"},
            {"varname": "state", "value": "BUSY"},
            {"varname": "counter", "value": "3"},
            {"varname": "fifo_empty", "value": "false"},
        ],
        "candidate_language": "cube-subset",
    }

    from llm_worker.jsonl_protocol import write_request_test
    write_request_test(req_path, ctx)

    sidecar_path = Path(__file__).parent / "llm_worker" / "sidecar.py"
    prompt_dir = Path(__file__).parent / "llm_worker" / "prompts"

    env = os.environ.copy()

    result = subprocess.run(
        [
            sys.executable, str(sidecar_path),
            "--req-path", req_path,
            "--resp-path", resp_path,
            "--log-path", log_path,
            "--poll-interval", "0.5",
            "--max-requests", "1",
            "--candidate-language", "cube-subset",
            "--prompt-dir", str(prompt_dir),
        ],
        capture_output=True, text=True, timeout=60,
        env=env,
    )

    print(f"  stdout: {result.stdout[-500:]}")
    if result.stderr:
        print(f"  stderr: {result.stderr[-500:]}")

    # Check response file
    if os.path.exists(resp_path):
        with open(resp_path) as f:
            resp_line = f.readline().strip()
            if resp_line:
                candidate = json.loads(resp_line)
                print(f"\n  Response type: {candidate.get('type')}")
                print(f"  Keep count: {len(candidate.get('keep_literals', []))}")
                print(f"  Drop count: {len(candidate.get('drop_literals', []))}")
                print(f"  Keep: {candidate.get('keep_literals')}")
                print(f"  Drop: {candidate.get('drop_literals')}")
                print(f"  Rationale: {candidate.get('rationale', '')[:200]}")
                print("  PASS (response written)")
            else:
                print("  FAIL: No response line")
    else:
        print("  FAIL: No response file created")

    # Check log file
    if os.path.exists(log_path):
        with open(log_path) as f:
            log_line = f.readline().strip()
            if log_line:
                log_entry = json.loads(log_line)
                print(f"\n  Log tokens: {log_entry.get('token_count')}")
                print(f"  Log latency: {log_entry.get('latency_ms', 0):.0f}ms")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true",
                        help="Run tests with real LLM API calls")
    parser.add_argument("--client-only", action="store_true",
                        help="Only test the DeepSeekClient directly")
    args = parser.parse_args()

    print("Pono LLM Sidecar -- API Integration Tests")
    print("=" * 50)

    if args.client_only:
        test_client_direct()
        return 0

    if args.with_llm:
        test_client_direct()
        test_sidecar_with_llm()
    else:
        print("Dry-run: set DEEPSEEK_API_KEY and use --with-llm for API tests")
        from llm_worker.deepseek_client import get_api_key
        api_key = get_api_key()
        if api_key:
            print("  (API key found, try --with-llm)")
        else:
            print("  (no API key found, set DEEPSEEK_API_KEY or OPENROUTER_API_KEY)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    exit(main())
