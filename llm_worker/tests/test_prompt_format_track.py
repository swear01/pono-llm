"""Tests for Track A prompt formatting (feedback, digest, hints)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_format import (
    format_feedback_block,
    format_frame_clause_digest,
    format_frame_snapshot,
    format_proof_context,
    format_symbol_hints,
    sample_generalization_hint,
)


def test_feedback_renders_failed_clause_with_idx():
    fb = [
        {
            "reason": "rejected_initial",
            "witness": {"ref": "state0", "next_value": "0"},
            "rejected_json": (
                '{"clause_idx":0,"block_clauses":['
                '[{"ref":"state0","op":"eq","rhs":"1","polarity":true}],'
                '[{"ref":"state5","op":"eq","rhs":"0","polarity":false}]'
                "]}"
            ),
        },
    ]
    text = format_feedback_block(fb)
    assert "failed_clause[0]" in text
    assert "state0=1" in text
    assert "clause[1]" not in text


def test_init_aware_block_present():
    from prompt_format import format_init_aware_block

    text = format_init_aware_block()
    assert "CTI literals" in text
    assert "FALSE at design reset" in text


def test_contrastive_feedback_zones():
    fb = [
        {
            "reason": "rejected_initial",
            "witness": {"ref": "state93", "next_value": "0"},
            "rejected_json": '{"block_disjuncts":[{"ref":"state93"}]}',
        },
        {
            "reason": "induction_failed",
            "witness": {"ref": "state12", "next_value": "1"},
        },
    ]
    text = format_feedback_block(fb)
    assert "Correctness failures" in text
    assert "Inductiveness failures" in text
    assert "Repair:" in text
    assert "state93=0" in text or "state93" in text


def test_attempt1_omit_frame_bodies():
    snap = {
        "frame_idx": 2,
        "clauses_total": 477,
        "clauses": [{"disjuncts": [{"atom": {"ref": "state1", "rhs": "1"}, "polarity": True}]}],
    }
    text = format_frame_snapshot(snap, max_clauses=0, attempt=1, has_feedback=False)
    assert "clause bodies omitted" in text
    assert "state1=1" not in text


def test_clause_digest_rendering():
    snap = {
        "frame_idx": 2,
        "clauses_total": 100,
        "clause_digest": {
            "clauses_total": 100,
            "literal_stats": [{"lit": "!state5=0", "count": 12}],
        },
        "clauses": [
            {
                "disjuncts": [
                    {"atom": {"ref": "state5", "rhs": "0"}, "polarity": False},
                ]
            }
        ],
    }
    text = format_frame_clause_digest(snap)
    assert "!state5=0" in text
    assert "count=12" in text
    assert "Sample clauses" in text


def test_symbol_hints_filtered():
    refs = {"state5", "state999"}
    registry = {
        "state5": {"width": 1, "verilog": "bad_flag"},
    }
    text = format_symbol_hints(refs, registry)
    assert "state5" in text
    assert "state999" not in text


def test_sample_hints_differ():
    assert sample_generalization_hint(0) != sample_generalization_hint(1)


def test_proof_context_fallback():
    req = {
        "frame_idx": 1,
        "attempt": 1,
        "cti_digest": {"cti_total": 9},
        "frame_snapshot": {"clauses_total": 50},
    }
    text = format_proof_context(req)
    assert "proof_context:" in text
    assert "cti_total" in text
    assert "clauses_total" in text
