"""Tests for Q4.2–Q4.6 harness completion (feedback_raw, candidates, constraints)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness_preprocess import (
    build_candidates,
    build_constraints,
    build_harness_packet,
    build_repair,
    harness_metrics,
    render_task_card,
)
from sidecar import HARNESS_LEGACY, build_batch_user_prompt


def _batch_req(**overrides):
    base = {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f3_a2",
        "frame_idx": 3,
        "attempt": 2,
        "max_block_clauses": 3,
        "cti_digest": {
            "cti_total": 50,
            "literal_stats": [
                {"lit": "state34=#b1", "count": 50},
                {"lit": "state512=#b0", "count": 40},
            ],
        },
        "init_raw": {
            "values": {"state34": "#b0", "state512": "#b1"},
        },
        "candidate_hints": [
            {
                "lit": "state34=#b1",
                "count": 50,
                "init_safe": True,
                "block_disjunct": {
                    "ref": "state34",
                    "op": "eq",
                    "rhs": "#b1",
                    "polarity": False,
                },
            },
            {
                "lit": "state512=#b0",
                "count": 40,
                "init_safe": False,
                "reason": "init_true",
                "block_disjunct": {
                    "ref": "state512",
                    "op": "eq",
                    "rhs": "#b0",
                    "polarity": True,
                },
            },
        ],
        "feedback_raw": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state512", "next_value": "#b1"},
                "failed_clause": [
                    {"ref": "state512", "op": "eq", "rhs": "1", "polarity": False}
                ],
                "clause_idx": 0,
                "sample_id": 1,
            }
        ],
        "feedback": [],
        "frame_snapshot": {"frame_idx": 3, "clauses_total": 10},
    }
    base.update(overrides)
    return base


def test_candidates_rank_init_safe_first():
    cands = build_candidates(_batch_req())
    assert cands[0]["init_safe"] is True
    assert cands[0]["lit"] == "state34=#b1"


def test_constraints_collect_forbidden_refs():
    c = build_constraints(_batch_req())
    assert "state512" in c["forbidden_refs"]
    assert "state34=#b1" in c["must_falsify"]


def test_repair_uses_feedback_raw_failed_clause():
    lines = build_repair(_batch_req())
    text = "\n".join(lines)
    assert "you_tried" in text
    assert "state512" in text


def test_task_card_shows_init_safe_and_constraints():
    text = render_task_card(_batch_req(), 0)
    assert "[init_safe]" in text
    assert "CONSTRAINTS:" in text
    assert "forbidden_refs" in text


def test_harness_packet_schema():
    pkt = build_harness_packet(_batch_req(), 0)
    assert pkt["type"] == "harness_packet"
    assert pkt["candidates"]
    assert pkt["constraints"]["must_falsify"]
    assert pkt["repair"]


def test_harness_metrics_coverage():
    m = harness_metrics(_batch_req(), 0)
    assert m["init_table_coverage_pct"] >= 90
    assert m["user_prompt_bytes"] < 8000
    assert m["has_candidate_hints"]
    assert m["has_init_raw"]


def test_legacy_prompt_differs_from_task_card(monkeypatch):
    import sidecar

    monkeypatch.setattr(sidecar, "HARNESS_LEGACY", False)
    harness = build_batch_user_prompt(_batch_req(attempt=1), {}, 0)
    monkeypatch.setattr(sidecar, "HARNESS_LEGACY", True)
    legacy = build_batch_user_prompt(_batch_req(attempt=1), {}, 0)
    assert harness.startswith("Self-check")
    assert "Digest-derived block hints" in legacy or "proof_context:" in legacy
    assert "INIT_TABLE" not in legacy
