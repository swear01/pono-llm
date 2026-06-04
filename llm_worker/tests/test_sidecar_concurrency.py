"""Test sidecar cross-request concurrency without calling the real API."""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonl_protocol import read_requests_batch, write_request_test
from sidecar import handle_one_request


def _minimal_request(cti_id: str) -> dict:
    return {
        "schema_version": 1,
        "type": "ic3_frame_request",
        "frame_idx": 1,
        "cti_id": cti_id,
        "attempt": 1,
        "max_attempts": 2,
        "parallel_samples": 1,
        "reasoning_effort": "none",
        "benchmark_context_path": "",
        "symbol_registry": {
            "state1": {"kind": "state", "width": 1, "btor2_line": 1, "verilog": "s"}
        },
        "cti": {
            "cube": {
                "form": "and",
                "literals": [{
                    "id": 0,
                    "form": "literal",
                    "atom": {"ref": "state1", "op": "eq", "rhs": "1"},
                    "polarity": True,
                }],
            }
        },
        "frame_snapshot": {"frame_idx": 1, "clauses": []},
        "feedback": [],
    }


def test_read_requests_batch():
    tmpdir = tempfile.mkdtemp()
    req_path = os.path.join(tmpdir, "req.jsonl")
    for i in range(3):
        write_request_test(req_path, _minimal_request(f"cti_{i}"))

    reqs, pos = read_requests_batch(req_path, 0, max_lines=2)
    assert len(reqs) == 2
    reqs2, pos2 = read_requests_batch(req_path, pos, max_lines=10)
    assert len(reqs2) == 1
    assert pos2 > pos


def test_parallel_requests_faster_than_serial():
    """Four requests with 0.5s mock latency should finish in ~0.5s with inflight=4."""
    from concurrent.futures import Future, ThreadPoolExecutor

    tmpdir = tempfile.mkdtemp()
    resp_path = os.path.join(tmpdir, "resp.jsonl")
    log_path = os.path.join(tmpdir, "log.jsonl")
    write_lock = threading.Lock()

    class MockClient:
        def call(self, *args, **kwargs):
            time.sleep(0.5)
            return (
                json.dumps({
                    "type": "ic3_frame_response",
                    "block_disjuncts": [
                        {"ref": "state1", "op": "eq", "rhs": "0", "polarity": False}
                    ],
                    "rationale": "mock",
                }),
                10,
                500.0,
            )

    client = MockClient()
    requests = [_minimal_request(f"cti_{i}") for i in range(4)]
    inflight: dict[Future, int] = {}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, req in enumerate(requests):
            fut = pool.submit(
                handle_one_request,
                client,
                req,
                "system",
                resp_path,
                log_path,
                write_lock,
                i,
            )
            inflight[fut] = i
        for fut in list(inflight):
            fut.result()
    elapsed = time.time() - t0

    assert elapsed < 1.5, f"expected parallel ~0.5s, got {elapsed:.2f}s"
    with open(resp_path) as f:
        lines = [ln for ln in f if ln.strip()]
    assert len(lines) == 4


if __name__ == "__main__":
    test_read_requests_batch()
    test_parallel_requests_faster_than_serial()
    print("All sidecar concurrency tests passed")
