"""JSONL protocol reader tests."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonl_protocol import read_requests_batch, write_request_test


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
        "cti": {"cube": {"literals": []}},
        "frame_snapshot": {"frame_idx": 1, "clauses": []},
        "feedback": [],
    }


def test_partial_line_does_not_advance():
    tmpdir = tempfile.mkdtemp()
    req_path = os.path.join(tmpdir, "req.jsonl")
    write_request_test(req_path, _minimal_request("cti_ok"))
    full_line = json.dumps(_minimal_request("cti_big"), ensure_ascii=False)
    partial = full_line[: len(full_line) // 2]
    with open(req_path, "a") as f:
        f.write(partial)

    pos = 0
    reqs, pos = read_requests_batch(req_path, pos, max_lines=4)
    assert len(reqs) == 1
    assert reqs[0]["cti_id"] == "cti_ok"

    with open(req_path, "a") as f:
        f.write(full_line[len(partial) :] + "\n")

    reqs2, pos2 = read_requests_batch(req_path, pos, max_lines=4)
    assert len(reqs2) == 1
    assert reqs2[0]["cti_id"] == "cti_big"
    assert pos2 > pos


def test_corrupt_complete_line_is_skipped():
    tmpdir = tempfile.mkdtemp()
    req_path = os.path.join(tmpdir, "req.jsonl")
    write_request_test(req_path, _minimal_request("good"))
    with open(req_path, "a") as f:
        f.write("{not valid json}\n")
    write_request_test(req_path, _minimal_request("after"))

    pos = 0
    reqs, pos = read_requests_batch(req_path, pos, max_lines=1)
    assert [r["cti_id"] for r in reqs] == ["good"]
    reqs2, pos2 = read_requests_batch(req_path, pos, max_lines=2)
    assert [r["cti_id"] for r in reqs2] == ["after"]
    assert pos2 > pos


def test_empty_line_skipped():
    tmpdir = tempfile.mkdtemp()
    req_path = os.path.join(tmpdir, "req.jsonl")
    write_request_test(req_path, _minimal_request("a"))
    with open(req_path, "a") as f:
        f.write("\n\n")
    write_request_test(req_path, _minimal_request("b"))

    reqs, _ = read_requests_batch(req_path, 0, max_lines=4)
    assert [r["cti_id"] for r in reqs] == ["a", "b"]


def test_no_new_data_returns_empty():
    tmpdir = tempfile.mkdtemp()
    req_path = os.path.join(tmpdir, "req.jsonl")
    write_request_test(req_path, _minimal_request("only"))
    _, pos = read_requests_batch(req_path, 0, max_lines=4)
    reqs, pos2 = read_requests_batch(req_path, pos, max_lines=4)
    assert reqs == []
    assert pos2 == pos


if __name__ == "__main__":
    test_partial_line_does_not_advance()
    test_corrupt_complete_line_is_skipped()
    test_empty_line_skipped()
    test_no_new_data_returns_empty()
    print("jsonl_protocol tests passed")
