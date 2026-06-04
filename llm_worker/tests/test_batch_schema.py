"""Tests for ic3_frame_batch_request validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_worker.ic3_frame_schema import validate_batch_request, validate_request


def _minimal_batch():
    return {
        "schema_version": 1,
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f1_a1",
        "frame_idx": 1,
        "attempt": 1,
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
    }


def test_validate_batch_request_ok():
    ok, err = validate_batch_request(_minimal_batch())
    assert ok, err
    ok2, err2 = validate_request(_minimal_batch())
    assert ok2, err2


def test_validate_batch_request_empty_entries():
    req = _minimal_batch()
    req["cti_entries"] = []
    ok, err = validate_batch_request(req)
    assert not ok
    assert "empty" in err


def test_validate_batch_request_missing_batch_id():
    req = _minimal_batch()
    del req["batch_id"]
    ok, err = validate_batch_request(req)
    assert not ok
    assert "batch_id" in err
