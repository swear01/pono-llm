#!/usr/bin/env python3
"""Sidecar llm_log.jsonl fields (thinking_mode integration, no network)."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidecar import handle_one_request


def _minimal_batch() -> dict:
    return {
        "schema_version": 1,
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f1_a1",
        "frame_idx": 1,
        "attempt": 1,
        "max_attempts": 1,
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


class OpenRouterMockClient:
    def __init__(self):
        self.last_call_stats = {
            "thinking_mode": "disabled",
            "prompt_tokens": 100,
            "completion_tokens": 42,
            "reasoning_chars": 0,
        }

    def call(self, *args, **kwargs):
        return (
            json.dumps({
                "type": "ic3_frame_response",
                "block_clauses": [
                    [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}]
                ],
                "rationale": "mock",
            }),
            142,
            12.5,
        )


def test_log_includes_thinking_mode_and_tokens():
    tmpdir = tempfile.mkdtemp()
    resp_path = os.path.join(tmpdir, "resp.jsonl")
    log_path = os.path.join(tmpdir, "llm_log.jsonl")
    write_lock = threading.Lock()

    handle_one_request(
        OpenRouterMockClient(),
        _minimal_batch(),
        "system",
        resp_path,
        log_path,
        write_lock,
        0,
    )

    with open(log_path) as f:
        log = json.loads(f.readline())
    assert log["thinking_mode"] == "disabled"
    assert log["completion_tokens"] == 42
    assert log["prompt_tokens"] == 100
    assert log["reasoning_chars"] == 0


def main():
    test_log_includes_thinking_mode_and_tokens()
    print("All test_sidecar_log tests passed")


if __name__ == "__main__":
    main()
