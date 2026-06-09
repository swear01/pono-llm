"""Mock sidecar batch request: 3 parallel responses."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sidecar import (
    V1_REQUEST_TYPES,
    build_batch_user_prompt,
    format_benchmark_context_ref,
    process_request,
)
def _minimal_batch(parallel_samples: int = 3) -> dict:
    return {
        "schema_version": 1,
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f1_a1",
        "frame_idx": 1,
        "attempt": 1,
        "max_attempts": 2,
        "parallel_samples": parallel_samples,
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


class MockClient:
    def call(self, *args, **kwargs):
        return (
            json.dumps({
                "type": "ic3_frame_response",
                "block_disjuncts": [
                    {"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}
                ],
                "rationale": "mock batch block",
            }),
            12,
            100.0,
        )


def test_v1_request_types_includes_batch():
    assert "ic3_frame_batch_request" in V1_REQUEST_TYPES


def test_process_batch_writes_k_responses():
    tmpdir = tempfile.mkdtemp()
    resp_path = os.path.join(tmpdir, "resp.jsonl")
    write_lock = threading.Lock()
    req = _minimal_batch(parallel_samples=3)

    responses, tokens, latency = process_request(
        MockClient(), req, "system", snapshot_max_clauses=50
    )
    assert len(responses) == 3
    assert tokens > 0

    for sample_id, resp in enumerate(responses):
        assert resp["source_cti_id"] == "batch_f1_a1"
        assert resp["sample_id"] == sample_id
        write_lock  # used by handle_one_request path; direct write here
        with open(resp_path, "a") as f:
            f.write(json.dumps(resp) + "\n")

    with open(resp_path) as f:
        lines = [ln for ln in f if ln.strip()]
    assert len(lines) == 3


def test_process_request_post_filters_witness_forbidden_on_retry():
    class RetryMockClient:
        def call(self, *args, **kwargs):
            return (
                json.dumps({
                    "block_clauses": [
                        [{"ref": "state24", "op": "eq", "rhs": "#b1", "polarity": False}],
                    ],
                }),
                12,
                100.0,
            )

    req = _minimal_batch(parallel_samples=1)
    req["attempt"] = 2
    req["batch_id"] = "batch_f1_a2"
    req["cti_digest"] = {
        "cti_total": 1,
        "literal_stats": [
            {"lit": "state24=#b1", "count": 5},
            {"lit": "state34=#b0", "count": 3},
        ],
    }
    req["cti_entries"] = [{"cti_id": "f1_abc", "literals": ["state24=1", "state34=0"]}]
    req["feedback"] = [
        {
            "reason": "rejected_initial",
            "witness": {"ref": "state24", "next_value": "#b1"},
            "rejected_json": "{}",
        }
    ]
    responses, _, _ = process_request(RetryMockClient(), req, "system")
    assert len(responses) == 1
    clause = responses[0]["block_clauses"][0]
    assert clause[0]["ref"] == "state34"
    assert "post-filter" in responses[0].get("rationale", "")


def test_benchmark_context_omits_bad_property():
    ctx = {
        "benchmark": "/path/foo.btor2",
        "bad_property": "x" * 10_000,
    }
    ref = format_benchmark_context_ref(ctx)
    assert "bad_property" not in ref
    assert "foo.btor2" in ref
    prompt = build_batch_user_prompt(_minimal_batch(), ctx, 0)
    assert "bad_property" not in prompt
    assert len(prompt) < 5000


if __name__ == "__main__":
    test_v1_request_types_includes_batch()
    test_process_batch_writes_k_responses()
    test_benchmark_context_omits_bad_property()
    print("sidecar batch tests passed")
