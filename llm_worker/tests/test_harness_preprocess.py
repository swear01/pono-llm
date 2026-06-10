"""Tests for Q4 harness task card ordering and content."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness_preprocess import (
    build_init_table,
    build_must_falsify,
    render_task_card,
    section_byte_sizes,
)
from sidecar import build_batch_user_prompt


def _batch_req(**overrides):
    base = {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f3_a1",
        "frame_idx": 3,
        "attempt": 1,
        "max_block_clauses": 3,
        "cti_digest": {
            "cti_total": 50,
            "literal_stats": [
                {"lit": "state34=#b1", "count": 50},
                {"lit": "state512=#b0", "count": 40},
            ],
        },
        "cti_entries": [
            {"cti_id": "c0", "literals": ["state34=#b1", "state99=#b1"]},
        ],
        "frame_snapshot": {
            "frame_idx": 3,
            "clauses_total": 10,
            "clause_digest": {
                "literal_stats": [{"lit": "state19=#b0", "count": 5}],
            },
        },
        "feedback": [],
    }
    base.update(overrides)
    return base


def test_section_order_stable_first():
    text = render_task_card(_batch_req(), 0)
    idx_check = text.index("Self-check")
    idx_must = text.index("MUST_FALSIFY")
    idx_init = text.index("INIT_TABLE")
    idx_micro = text.index("Micro-example")
    idx_cti = text.index("CTI summary")
    assert idx_check < idx_must < idx_init < idx_micro < idx_cti


def test_must_falsify_lists_digest_literals():
    items = build_must_falsify(_batch_req())
    assert items[0]["lit"] == "state34=#b1"
    text = render_task_card(_batch_req(), 0)
    assert "state34=#b1" in text
    assert "do NOT copy as true disjunct" in text


def test_init_table_shows_witness_on_retry():
    req = _batch_req(
        attempt=2,
        feedback=[
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state512", "next_value": "#b1"},
                "rejected_json": (
                    '{"block_clauses":[[{"ref":"state512","op":"eq","rhs":"#b1",'
                    '"polarity":false}]]}'
                ),
            }
        ],
    )
    text = render_task_card(req, 0)
    assert "state512" in text
    assert "#b1" in text or "1" in text
    assert "REPAIR:" in text
    assert text.index("REPAIR:") < text.index("CTI summary")


def test_retry_repair_before_cti_summary():
    req = _batch_req(
        attempt=2,
        feedback=[
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state512", "next_value": "#b1"},
                "rejected_json": "{}",
            }
        ],
    )
    text = render_task_card(req, 0)
    assert text.index("REPAIR:") < text.index("CTI summary")


def test_self_check_and_output_line():
    text = render_task_card(_batch_req(), 0)
    assert "self_check" in text
    assert "Output json" in text


def test_build_batch_user_prompt_uses_task_card():
    prompt = build_batch_user_prompt(_batch_req(), {}, 0)
    assert prompt.startswith("Self-check")
    assert "Digest-derived block hints" not in prompt


def test_init_raw_populates_init_column():
    req = _batch_req(
        init_raw={
            "values": {
                "state34": "#b0",
                "state512": "#b1",
            }
        }
    )
    text = render_task_card(req, 0)
    assert "state34" in text
    assert "state512" in text
    assert "#b0" in text or "0" in text
    assert all(r.get("init") is not None for r in build_init_table(req))


def test_init_raw_attempt1_fills_unknown_init_rows():
    req_witness_only = _batch_req(attempt=1)
    req_with_init = _batch_req(
        attempt=1,
        init_raw={"values": {"state34": "#b0", "state512": "#b1"}},
    )
    unknown_w = sum(1 for r in build_init_table(req_witness_only) if r.get("init") is None)
    unknown_i = sum(1 for r in build_init_table(req_with_init) if r.get("init") is None)
    assert unknown_i == 0
    assert unknown_i < unknown_w


def test_task_card_smaller_than_legacy_digest_blob():
    sizes = section_byte_sizes(_batch_req(), 0)
    assert sizes["checklist"] > 0
    assert sizes["total"] < 8000


def test_candidate_hints_init_safe_tag_in_prompt():
    req = _batch_req(
        candidate_hints=[
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
            }
        ]
    )
    text = render_task_card(req, 0)
    assert "[init_safe]" in text
