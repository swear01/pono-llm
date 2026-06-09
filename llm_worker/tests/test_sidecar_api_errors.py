#!/usr/bin/env python3
"""Sidecar resilience when LLM API returns errors (no network)."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidecar import handle_one_request, process_request


def _minimal_batch() -> dict:
    return {
        "schema_version": 1,
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f1_a1",
        "frame_idx": 1,
        "attempt": 1,
        "max_attempts": 2,
        "max_block_clauses": 3,
        "parallel_samples": 1,
        "temperature": 0.5,
        "reasoning_effort": "none",
        "benchmark_context_path": "",
        "cti_entries": [
            {
                "cti_id": "f1_abc",
                "cti": {
                    "cube": {
                        "literals": [
                            {
                                "atom": {"ref": "state5", "rhs": "1"},
                                "polarity": True,
                            }
                        ]
                    }
                },
            }
        ],
        "frame_snapshot": {"frame_idx": 1, "clauses": []},
        "feedback": [],
    }


class ErrorClient:
    def call(self, *args, **kwargs):
        raise RuntimeError("API returned finish_reason=error: ")


def test_process_request_survives_api_error():
    req = _minimal_batch()
    responses, tokens, latency = process_request(
        ErrorClient(), req, "system", snapshot_max_clauses=0
    )
    assert len(responses) == 1
    assert responses[0]["source_cti_id"] == "batch_f1_a1"
    assert "api_error" in responses[0].get("rationale", "")


def test_handle_one_request_writes_response_and_log():
    tmpdir = tempfile.mkdtemp()
    resp_path = os.path.join(tmpdir, "resp.jsonl")
    log_path = os.path.join(tmpdir, "llm_log.jsonl")
    write_lock = threading.Lock()
    req = _minimal_batch()

    n_resp, tokens, latency = handle_one_request(
        ErrorClient(),
        req,
        "system",
        resp_path,
        log_path,
        write_lock,
        0,
        snapshot_max_clauses=0,
    )

    assert n_resp == 1
    assert tokens == 0
    with open(resp_path) as f:
        line = f.readline().strip()
    resp = json.loads(line)
    assert resp["sample_id"] == 0
    assert "api_error" in resp.get("rationale", "")

    with open(log_path) as f:
        log = json.loads(f.readline())
    assert log["batch_id"] == "batch_f1_a1"


def test_drain_completed_records_error_without_crashing():
    from concurrent.futures import Future

    from sidecar import drain_completed

    inflight: dict = {}

    fut = Future()
    fut.set_exception(RuntimeError("API returned finish_reason=error: "))
    inflight[fut] = 0

    done = drain_completed(inflight)
    assert len(done) == 1
    assert done[0][3] is not None
    assert inflight == {}


def test_second_request_after_error():
    req = _minimal_batch()

    class OkClient:
        def __init__(self):
            self.calls = 0

        def call(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("API returned finish_reason=error: ")
            return (
                json.dumps({
                    "type": "ic3_frame_response",
                    "block_clauses": [
                        [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}]
                    ],
                    "rationale": "ok",
                }),
                10,
                5.0,
            )

    client = OkClient()
    err_responses, _, _ = process_request(client, req, "system")
    ok_responses, _, _ = process_request(client, req, "system")
    assert "api_error" in err_responses[0]["rationale"]
    assert "api_error" not in ok_responses[0]["rationale"]


def main():
    test_process_request_survives_api_error()
    test_handle_one_request_writes_response_and_log()
    test_second_request_after_error()
    print("All test_sidecar_api_errors tests passed")


if __name__ == "__main__":
    main()
