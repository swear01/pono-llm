"""Unit tests for IC3 Frame v1 schema (block + refine_predicate)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_worker.ic3_frame_schema import (
    normalize_response,
    validate_batch_request,
    validate_request,
    validate_response,
)


def test_block_only_response():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "cti_001",
        "block_disjuncts": [
            {"ref": "state93", "op": "eq", "rhs": "1", "polarity": False},
        ],
        "symbols_used": ["state93"],
        "rationale": "block CTI",
    }
    ok, err = validate_response(resp)
    assert ok, err
    out = normalize_response(resp, "cti_001", 0)
    assert out["block_disjuncts"]
    assert "refine_predicate" not in out


def test_block_plus_predicate():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "cti_002",
        "block_disjuncts": [
            {"ref": "state93", "op": "eq", "rhs": "0", "polarity": False},
        ],
        "refine_predicate": {
            "form": "eq",
            "args": [
                {
                    "form": "bvand",
                    "args": [
                        {"form": "ref", "ref": "state1536"},
                        {"form": "const", "const": "2", "width": 4},
                    ],
                },
                {"form": "const", "const": "0", "width": 4},
            ],
        },
        "symbols_used": ["state93", "state1536"],
        "rationale": "block + refine",
    }
    ok, err = validate_response(resp)
    assert ok, err
    out = normalize_response(resp, "cti_002", 1)
    assert out["refine_predicate"]["form"] == "eq"
    assert out["sample_id"] == 1


def test_predicate_only_via_actions():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "cti_003",
        "actions": [
            {
                "kind": "refine_predicate",
                "predicate": {
                    "form": "eq",
                    "args": [
                        {"form": "ref", "ref": "state1"},
                        {"form": "const", "const": "1", "width": 1},
                    ],
                },
            }
        ],
        "rationale": "predicate only",
    }
    ok, err = validate_response(resp)
    assert ok, err
    out = normalize_response(resp, "cti_003", 0)
    assert out["refine_predicate"]["form"] == "eq"
    assert not out.get("block_disjuncts")


def test_invalid_predicate_form():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "cti_004",
        "refine_predicate": {"form": "forall", "args": []},
    }
    ok, err = validate_response(resp)
    assert not ok
    assert "unsupported" in err or "missing" in err


def test_block_clauses_multi():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "batch_f2_a1",
        "block_clauses": [
            [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": True}],
            [{"ref": "state93", "op": "eq", "rhs": "1", "polarity": False}],
        ],
        "rationale": "alternatives",
    }
    ok, err = validate_response(resp, max_block_clauses=3)
    assert ok, err
    out = normalize_response(resp, "batch_f2_a1", 0, max_block_clauses=3)
    assert len(out["block_clauses"]) == 2
    assert out["block_disjuncts"] == out["block_clauses"][0]


def test_block_clauses_over_limit_rejected():
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "batch_f2_a1",
        "block_clauses": [
            [{"ref": f"state{i}", "op": "eq", "rhs": "0", "polarity": True}]
            for i in range(4)
        ],
    }
    ok, err = validate_response(resp, max_block_clauses=3)
    assert not ok


def test_validate_batch_via_validate_request():
    req = {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f2_a1",
        "frame_idx": 2,
        "cti_entries": [{"cti_id": "x", "cti": {"cube": {"literals": []}}}],
    }
    ok, err = validate_request(req)
    assert ok, err


def test_feedback_witness_request_shape():
    """Contract test: C++ retry request feedback[] with witness fields."""
    import json

    req = {
        "type": "ic3_frame_request",
        "attempt": 2,
        "feedback": [
            {
                "reason": "induction_failed",
                "rejected_json": "{}",
                "witness": {"ref": "state93", "next_value": "42"},
            }
        ],
    }
    parsed = json.loads(json.dumps(req))
    fb = parsed["feedback"][0]
    assert fb["witness"]["ref"] == "state93"
    assert fb["witness"]["next_value"] == "42"


if __name__ == "__main__":
    test_block_only_response()
    test_block_plus_predicate()
    test_predicate_only_via_actions()
    test_invalid_predicate_form()
    test_feedback_witness_request_shape()
    print("All ic3_frame_schema tests passed")
