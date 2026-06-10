"""Tests for Q3.1 witness repair and Q3.2 digest-negate prompt formatting."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_format import (
    _failed_clause_from_rejected_json,
    _is_forbidden_witness_block_disjunct,
    apply_witness_forbidden_post_filter,
    collect_forbidden_positive_literals,
    disjunct_blocked_for_witness_retry,
    disjunct_equals,
    forbidden_disjuncts_for_witness,
    format_digest_block_hints,
    format_feedback_block,
    format_witness_repair_lines,
    negate_digest_lit_to_disjunct,
    parse_digest_lit_line,
    parse_witness_tag,
    pick_digest_literal_lines,
    sample_generalization_hint,
)
from sidecar import build_batch_user_prompt, build_user_prompt


def _digest_req():
    return {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f3_a1",
        "frame_idx": 3,
        "attempt": 2,
        "cti_digest": {
            "cti_total": 67,
            "literal_stats": [
                {"lit": "state215=#b1", "count": 67},
                {"lit": "state24=#b1", "count": 67},
                {"lit": "(bvor (bvcomp input9 #b1) (bvnot #b1))=#b1", "count": 67},
                {"lit": "!state5=#b0", "count": 12},
            ],
        },
        "cti_entries": [{"cti_id": "x", "cti": {"cube": {"literals": []}}}],
        "frame_snapshot": {"frame_idx": 3, "clauses": []},
        "feedback": [],
    }


def test_parse_witness_tag():
    assert parse_witness_tag("#b0") == "init0"
    assert parse_witness_tag("1") == "init1"
    assert parse_witness_tag("#b0001") == "init_wide"


def test_forbidden_init0_patterns():
    forbidden = forbidden_disjuncts_for_witness("state19", "#b0")
    assert disjunct_equals(
        forbidden[0], {"ref": "state19", "op": "eq", "rhs": "1", "polarity": True}
    )
    assert any(
        disjunct_equals(d, {"ref": "state19", "op": "eq", "rhs": "0", "polarity": False})
        for d in forbidden
    )


def test_disjunct_equals_normalizes_rhs():
    a = {"ref": "state5", "op": "eq", "rhs": "#b0", "polarity": False}
    b = {"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}
    assert disjunct_equals(a, b)


def test_negate_digest_lit_state_positive():
    dj = negate_digest_lit_to_disjunct("state215=#b1")
    assert dj == {"ref": "state215", "op": "eq", "rhs": "#b1", "polarity": False}


def test_negate_digest_lit_negated_prefix():
    dj = negate_digest_lit_to_disjunct("!state5=#b0")
    assert dj == {"ref": "state5", "op": "eq", "rhs": "#b0", "polarity": True}


def test_negate_digest_skips_compound():
    assert negate_digest_lit_to_disjunct("(bvor x y)=#b1") is None
    assert parse_digest_lit_line("(bvor x y)=#b1") is None


def test_pick_digest_literal_lines_skips_compound():
    req = _digest_req()
    lits = pick_digest_literal_lines(req, max_n=5)
    assert "state215=#b1" in lits
    assert all("bvor" not in x for x in lits)


def test_format_digest_block_hints():
    text = format_digest_block_hints(_digest_req())
    assert "Digest-derived block hints" in text
    assert "top-1 CTI literal: state215=#b1" in text
    assert "!state215=1" in text
    assert '"polarity":false' in text
    assert "FORBIDDEN" in text
    assert "state215=1" in text


def test_collect_forbidden_positive_literals():
    forbidden = collect_forbidden_positive_literals(_digest_req(), n=3)
    assert "state215=1" in forbidden
    assert "!state5=0" in forbidden or "state5=0" in forbidden


def test_witness_repair_init0_forbidden():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state19", "next_value": "#b0"},
        "rejected_json": json.dumps(
            {
                "clause_idx": 0,
                "block_clauses": [
                    [{"ref": "state19", "op": "eq", "rhs": "0", "polarity": False}]
                ],
            }
        ),
    }
    lines = format_witness_repair_lines(fb, req=_digest_req())
    joined = "\n".join(lines)
    assert "INIT_CHECK" in joined
    assert "FORBIDDEN" in joined
    assert "!state19=0" in joined
    assert "SUGGESTED" in joined
    assert "state215" in joined


def test_forbidden_init0_state19_eq_1_failed():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state19", "next_value": "#b0"},
        "rejected_json": json.dumps(
            {
                "clause_idx": 0,
                "block_clauses": [
                    [{"ref": "state19", "op": "eq", "rhs": "1", "polarity": True}]
                ],
            }
        ),
    }
    joined = "\n".join(format_witness_repair_lines(fb))
    assert "state19=1" in joined
    assert "FORBIDDEN" in joined


def test_witness_repair_init1_forbidden():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state7", "next_value": "#b1"},
        "rejected_json": "{}",
    }
    lines = format_witness_repair_lines(fb, req=None)
    joined = "\n".join(lines)
    assert "!state7=1" in joined
    assert "state7=0" in joined


def test_feedback_no_witness_fallback_repair():
    fb = [{"reason": "rejected_initial", "rejected_json": "{}"}]
    text = format_feedback_block(fb)
    assert "Repair: block must NOT hold on any initial state" in text


def test_rejected_json_without_clause_idx_uses_last_clause():
    rejected = json.dumps(
        {
            "block_clauses": [
                [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}],
                [{"ref": "state19", "op": "eq", "rhs": "0", "polarity": False}],
            ]
        }
    )
    clause, idx = _failed_clause_from_rejected_json(rejected)
    assert idx == 1
    assert clause[0]["ref"] == "state19"
    text = format_feedback_block(
        [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state19", "next_value": "#b0"},
                "rejected_json": rejected,
            }
        ]
    )
    assert "failed_clause[1]" in text
    assert "state19=0" in text
    assert "clause[0]" not in text


def test_feedback_block_q31_integration():
    fb = [
        {
            "reason": "rejected_initial",
            "witness": {"ref": "state19", "next_value": "#b0"},
            "rejected_json": json.dumps(
                {
                    "clause_idx": 0,
                    "block_clauses": [
                        [{"ref": "state19", "op": "eq", "rhs": "0", "polarity": False}]
                    ],
                }
            ),
        },
        {
            "reason": "induction_failed",
            "witness": {"ref": "state32", "next_value": "#b1"},
        },
    ]
    text = format_feedback_block(fb, req=_digest_req())
    assert "INIT_CHECK" in text
    assert "FORBIDDEN" in text
    assert "failed_clause[0]" in text
    assert "Inductiveness failures" in text
    assert "Repair:" in text


def test_digest_hints_from_cti_entries_fallback():
    req = {
        "cti_entries": [
            {
                "cti_id": "c1",
                "cti": {
                    "cube": {
                        "literals": [
                            {
                                "atom": {"ref": "state81", "rhs": "#b1"},
                                "polarity": True,
                            }
                        ]
                    }
                },
            }
        ],
    }
    text = format_digest_block_hints(req)
    assert "!state81=1" in text
    assert "FORBIDDEN" in text


def test_sample_generalization_hint_q32():
    assert "digest top-1 NEGATION" in sample_generalization_hint(0)
    assert "never restate positive" in sample_generalization_hint(2).lower()


def test_build_batch_user_prompt_uses_q4_task_card():
    req = _digest_req()
    prompt = build_batch_user_prompt(req, {}, 0)
    assert prompt.startswith("Self-check")
    assert "MUST_FALSIFY" in prompt
    assert "state215=#b1" in prompt
    assert "CANDIDATES" in prompt


def test_build_user_prompt_uses_q4_task_card():
    req = {
        "type": "ic3_frame_request",
        "frame_idx": 2,
        "cti_id": "c1",
        "attempt": 1,
        "cti": {
            "cube": {
                "literals": [
                    {"atom": {"ref": "state44", "rhs": "#b1"}, "polarity": True},
                ]
            }
        },
        "frame_snapshot": {"frame_idx": 2, "clauses": []},
    }
    prompt = build_user_prompt(req, {}, 0)
    assert "MUST_FALSIFY" in prompt
    assert "state44=1" in prompt


def test_digest_hints_skip_witness_forbidden_on_retry():
    """Q3.2 must not suggest !state24=1 when init1 witness forbids it."""
    req = {
        "attempt": 2,
        "cti_entries": [
            {
                "cti_id": "c1",
                "cti": {
                    "cube": {
                        "literals": [
                            {"atom": {"ref": "state24", "rhs": "#b1"}, "polarity": True},
                            {"atom": {"ref": "state34", "rhs": "#b0"}, "polarity": True},
                        ]
                    }
                },
            }
        ],
        "feedback": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state24", "next_value": "#b1"},
                "rejected_json": "{}",
            }
        ],
    }
    text = format_digest_block_hints(req)
    assert "!state24=1" not in text
    assert "!state34=0" in text
    assert "witness-safe" in text.lower() or "FORBIDDEN" in text


def test_pick_digest_literal_lines_skip_witness_forbidden():
    req = {
        "cti_digest": {
            "literal_stats": [
                {"lit": "state24=#b1", "count": 10},
                {"lit": "state34=#b0", "count": 8},
            ]
        },
        "feedback": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state24", "next_value": "#b1"},
            }
        ],
    }
    lits = pick_digest_literal_lines(req, max_n=3, skip_witness_forbidden=True)
    assert lits == ["state34=#b0"]
    dj = negate_digest_lit_to_disjunct("state24=#b1")
    assert _is_forbidden_witness_block_disjunct(dj, req)


def test_suggest_digest_negation_avoids_witness_forbidden_fallback():
    req = {
        "cti_digest": {"literal_stats": [{"lit": "state24=#b1", "count": 5}]},
        "feedback": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state24", "next_value": "#b1"},
            }
        ],
    }
    lines = format_witness_repair_lines(
        req["feedback"][0],
        req=req,
    )
    joined = "\n".join(lines)
    assert "!state24=1" not in joined.split("SUGGESTED")[-1]
    assert "different from witness" in joined or "state24" not in joined.split("SUGGESTED")[-1]


def test_disjunct_blocked_init_wide_any_ref():
    dj = {"ref": "state798", "op": "eq", "rhs": "#b000000000000", "polarity": False}
    assert disjunct_blocked_for_witness_retry(dj, "state798", "#b000000000000")


def test_post_filter_strips_witness_forbidden_on_retry():
    req = {
        "attempt": 2,
        "cti_digest": {
            "literal_stats": [
                {"lit": "state24=#b1", "count": 10},
                {"lit": "state34=#b0", "count": 8},
            ]
        },
        "feedback": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state24", "next_value": "#b1"},
            }
        ],
    }
    resp = {
        "type": "ic3_frame_response",
        "source_cti_id": "batch_f1_a2",
        "block_clauses": [
            [{"ref": "state24", "op": "eq", "rhs": "#b1", "polarity": False}],
            [{"ref": "state34", "op": "eq", "rhs": "#b0", "polarity": False}],
        ],
    }
    out = apply_witness_forbidden_post_filter(resp, req)
    assert out["block_clauses"][0][0]["ref"] == "state34"
    assert "post-filter" in out.get("rationale", "")


def test_post_filter_fallback_safe_digest_when_all_stripped():
    req = {
        "attempt": 3,
        "cti_digest": {
            "literal_stats": [{"lit": "state34=#b0", "count": 5}],
        },
        "feedback": [
            {
                "reason": "rejected_initial",
                "witness": {"ref": "state24", "next_value": "#b1"},
            }
        ],
    }
    resp = {
        "type": "ic3_frame_response",
        "block_clauses": [
            [{"ref": "state24", "op": "eq", "rhs": "1", "polarity": False}],
        ],
    }
    out = apply_witness_forbidden_post_filter(resp, req)
    assert len(out["block_clauses"]) == 1
    assert out["block_clauses"][0][0]["ref"] == "state34"


def test_post_filter_noop_on_attempt1():
    req = {"attempt": 1, "feedback": []}
    resp = {"block_clauses": [[{"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}]]}
    assert apply_witness_forbidden_post_filter(resp, req) is resp


def test_build_batch_user_prompt_includes_witness_repair_on_retry():
    req = _digest_req()
    req["feedback"] = [
        {
            "reason": "rejected_initial",
            "witness": {"ref": "state19", "next_value": "#b0"},
            "rejected_json": json.dumps(
                {
                    "clause_idx": 0,
                    "block_clauses": [
                        [{"ref": "state19", "op": "eq", "rhs": "0", "polarity": False}]
                    ],
                }
            ),
        }
    ]
    prompt = build_batch_user_prompt(req, {}, 0)
    assert "REPAIR:" in prompt
    assert "state19" in prompt
    assert "init_witness" in prompt
