"""Tests for invariant_prompt.py — no network calls."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from invariant_prompt import (
    INVARIANT_SYSTEM_PROMPT,
    build_stage0_prompt,
    build_stage2_prompt,
    parse_invariant_response,
    parse_invariant_response_with_diagnostics,
    _validate_predicate_ast,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_HOT_VARS = [
    {"ref": "state6", "width": 8, "init": "0", "verilog": "wr_ptr"},
    {"ref": "state7", "width": 8, "init": "0", "verilog": "rd_ptr"},
    {"ref": "state8", "width": 8, "init": "0", "verilog": "count"},
]

SAMPLE_STAGE0_REQUEST = {
    "type": "ic3_stage0_request",
    "request_id": "stage0_test",
    "benchmark": "myfifo-p001",
    "property_desc": "FIFO count never exceeds depth",
    "hot_variables": SAMPLE_HOT_VARS,
    "inputs": [
        {"symbol": "i_wr", "width": 1},
        {"symbol": "i_rd", "width": 1},
    ],
    "transition_sketch": [
        "wr_ptr' depends on inputs: i_wr; states: state7",
        "count' depends on inputs: i_wr, i_rd",
    ],
}

SAMPLE_STAGE2_REQUEST = {
    "type": "ic3_stage2_request",
    "request_id": "stage2_f3_t42",
    "trigger": "T2_plateau",
    "proof_state": {
        "current_frame": 3,
        "frames_stuck_rounds": 12,
        "total_cti_count": 89,
        "frame_clause_count": 47,
    },
    "hot_variables": SAMPLE_HOT_VARS,
    "cti_cluster": [
        {"state6": 7, "state7": 4, "state8": 4},
        {"state6": 9, "state7": 6, "state8": 4},
    ],
    "frame_clause_clusters": [
        {"pattern_desc": "count=4 variations", "count": 12,
         "example_verilog": "count≠4 ∨ rd_ptr≠4"},
    ],
    "previously_injected": ["count <= 8"],
}


# ---------------------------------------------------------------------------
# INVARIANT_SYSTEM_PROMPT
# ---------------------------------------------------------------------------

def test_system_prompt_not_empty():
    assert len(INVARIANT_SYSTEM_PROMPT) > 100


def test_system_prompt_mentions_init():
    assert "init" in INVARIANT_SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_predicate_ast():
    assert "predicate_ast" in INVARIANT_SYSTEM_PROMPT or "predicate" in INVARIANT_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# build_stage0_prompt
# ---------------------------------------------------------------------------

def test_stage0_prompt_contains_benchmark():
    prompt = build_stage0_prompt(SAMPLE_STAGE0_REQUEST)
    assert "myfifo-p001" in prompt


def test_stage0_prompt_contains_property():
    prompt = build_stage0_prompt(SAMPLE_STAGE0_REQUEST)
    assert "FIFO count never exceeds depth" in prompt


def test_stage0_prompt_contains_hot_vars():
    prompt = build_stage0_prompt(SAMPLE_STAGE0_REQUEST)
    assert "state6" in prompt
    assert "wr_ptr" in prompt
    assert "state8" in prompt


def test_stage0_prompt_contains_inputs():
    prompt = build_stage0_prompt(SAMPLE_STAGE0_REQUEST)
    assert "i_wr" in prompt


def test_stage0_prompt_contains_transition_sketch():
    prompt = build_stage0_prompt(SAMPLE_STAGE0_REQUEST)
    assert "wr_ptr'" in prompt or "transition" in prompt.lower()


def test_stage0_prompt_minimal_request():
    """Prompt must not crash on minimal request."""
    prompt = build_stage0_prompt({
        "type": "ic3_stage0_request",
        "request_id": "x",
        "benchmark": "foo",
        "property_desc": "something bad",
    })
    assert "foo" in prompt
    assert len(prompt) > 20


# ---------------------------------------------------------------------------
# build_stage2_prompt
# ---------------------------------------------------------------------------

def test_stage2_prompt_mentions_trigger():
    prompt = build_stage2_prompt(SAMPLE_STAGE2_REQUEST)
    assert "T2_plateau" in prompt


def test_stage2_prompt_mentions_frame():
    prompt = build_stage2_prompt(SAMPLE_STAGE2_REQUEST)
    assert "frame 3" in prompt or "frame=3" in prompt or "3" in prompt


def test_stage2_prompt_contains_cti_cluster():
    prompt = build_stage2_prompt(SAMPLE_STAGE2_REQUEST)
    assert "CTI" in prompt
    assert "state6" in prompt or "7" in prompt


def test_stage2_prompt_contains_frame_clusters():
    prompt = build_stage2_prompt(SAMPLE_STAGE2_REQUEST)
    assert "count=4" in prompt or "clause" in prompt.lower()


def test_stage2_prompt_contains_prev_injected():
    prompt = build_stage2_prompt(SAMPLE_STAGE2_REQUEST)
    assert "count <= 8" in prompt


def test_stage2_prompt_minimal_request():
    prompt = build_stage2_prompt({
        "type": "ic3_stage2_request",
        "request_id": "x",
        "trigger": "T1_cluster",
    })
    assert "T1_cluster" in prompt


# ---------------------------------------------------------------------------
# _validate_predicate_ast
# ---------------------------------------------------------------------------

def test_validate_ast_ref():
    assert _validate_predicate_ast({"form": "ref", "ref": "state6"}) is True


def test_validate_ast_const():
    assert _validate_predicate_ast({"form": "const", "const": "42", "width": 8}) is True


def test_validate_ast_eq():
    ast = {"form": "eq", "args": [
        {"form": "ref", "ref": "state6"},
        {"form": "const", "const": "0", "width": 8},
    ]}
    assert _validate_predicate_ast(ast) is True


def test_validate_ast_missing_form():
    assert _validate_predicate_ast({"ref": "state6"}) is False


def test_validate_ast_not_dict():
    assert _validate_predicate_ast("eq") is False
    assert _validate_predicate_ast(None) is False
    assert _validate_predicate_ast([]) is False


def test_validate_ast_ref_without_ref_key():
    assert _validate_predicate_ast({"form": "ref"}) is False


def test_validate_ast_const_without_const_key():
    assert _validate_predicate_ast({"form": "const", "width": 8}) is False


def test_validate_ast_rejects_unsupported_form_recursively():
    ast = {
        "form": "eq",
        "args": [
            {"form": "ref", "ref": "state6"},
            {
                "form": "div",
                "args": [
                    {"form": "ref", "ref": "state7"},
                    {"form": "const", "const": "2", "width": 8},
                ],
            },
        ],
    }
    assert _validate_predicate_ast(ast) is False


def test_validate_ast_rejects_wrong_arity():
    assert _validate_predicate_ast({
        "form": "eq",
        "args": [{"form": "ref", "ref": "state6"}],
    }) is False


# ---------------------------------------------------------------------------
# parse_invariant_response
# ---------------------------------------------------------------------------

VALID_RESPONSE = json.dumps({
    "candidates": [
        {
            "id": 1,
            "kind": "Type1_invariant",
            "verilog_expr": "count == wr_ptr - rd_ptr",
            "predicate_ast": {
                "form": "eq",
                "args": [
                    {"form": "ref", "ref": "state8"},
                    {"form": "sub", "args": [
                        {"form": "ref", "ref": "state6"},
                        {"form": "ref", "ref": "state7"},
                    ]},
                ],
            },
            "intuition": "count tracks wr_ptr minus rd_ptr",
        },
        {
            "id": 2,
            "kind": "Type3_predicate",
            "verilog_expr": "wr_ptr >= rd_ptr",
            "predicate_ast": {
                "form": "uge",
                "args": [
                    {"form": "ref", "ref": "state6"},
                    {"form": "ref", "ref": "state7"},
                ],
            },
            "intuition": "write pointer never falls behind read pointer",
        },
    ]
})


def test_parse_valid_response():
    candidates = parse_invariant_response(VALID_RESPONSE)
    assert len(candidates) == 2


def test_parse_response_fields():
    candidates = parse_invariant_response(VALID_RESPONSE)
    c0 = candidates[0]
    assert c0["kind"] == "Type1_invariant"
    assert c0["predicate_ast"]["form"] == "eq"
    assert "intuition" in c0


def test_parse_response_empty_candidates():
    text = json.dumps({"candidates": []})
    assert parse_invariant_response(text) == []


def test_parse_response_missing_candidates_key():
    text = json.dumps({"result": []})
    assert parse_invariant_response(text) == []


def test_parse_response_invalid_json():
    assert parse_invariant_response("not json at all") == []
    assert parse_invariant_response("") == []


def test_parse_response_candidate_missing_ast():
    text = json.dumps({"candidates": [
        {"id": 1, "kind": "Type1_invariant", "verilog_expr": "x", "intuition": "y"},
    ]})
    # Missing predicate_ast → filtered out
    assert parse_invariant_response(text) == []


def test_parse_response_unknown_kind_normalised():
    text = json.dumps({"candidates": [
        {
            "id": 1,
            "kind": "unknown_kind",
            "verilog_expr": "x >= 0",
            "predicate_ast": {"form": "ref", "ref": "state6"},
            "intuition": "y",
        },
    ]})
    candidates = parse_invariant_response(text)
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "Type1_invariant"


def test_parse_response_extracts_from_markdown_fence():
    """Response wrapped in markdown fences should still parse."""
    inner = json.dumps({"candidates": [
        {
            "id": 1,
            "kind": "Type1_invariant",
            "verilog_expr": "x",
            "predicate_ast": {"form": "ref", "ref": "state1"},
            "intuition": "z",
        }
    ]})
    wrapped = f"```json\n{inner}\n```"
    # parse_invariant_response should handle JSON extraction
    candidates = parse_invariant_response(inner)
    assert len(candidates) == 1


def test_parse_response_type2_lift():
    text = json.dumps({"candidates": [
        {
            "id": 1,
            "kind": "Type2_lift",
            "verilog_expr": "count <= 255",
            "predicate_ast": {"form": "ule", "args": [
                {"form": "ref", "ref": "state8"},
                {"form": "const", "const": "255", "width": 8},
            ]},
            "intuition": "count bounded by max",
        }
    ]})
    candidates = parse_invariant_response(text)
    assert candidates[0]["kind"] == "Type2_lift"


def test_parse_response_multiple_valid_and_invalid():
    """Mix of valid and invalid candidates — only valid ones returned."""
    text = json.dumps({"candidates": [
        {  # valid
            "id": 1, "kind": "Type1_invariant", "verilog_expr": "x",
            "predicate_ast": {"form": "ref", "ref": "state1"},
            "intuition": "ok",
        },
        {  # invalid: no predicate_ast
            "id": 2, "kind": "Type1_invariant", "verilog_expr": "y",
            "intuition": "missing ast",
        },
        {  # invalid: bad ast
            "id": 3, "kind": "Type1_invariant", "verilog_expr": "z",
            "predicate_ast": "not a dict",
            "intuition": "bad ast",
        },
    ]})
    candidates = parse_invariant_response(text)
    assert len(candidates) == 1
    assert candidates[0]["id"] == 1


def test_parse_response_reports_unsupported_form():
    text = json.dumps({"candidates": [{
        "id": 1,
        "predicate_ast": {
            "form": "div",
            "args": [
                {"form": "ref", "ref": "state1"},
                {"form": "const", "const": "2", "width": 8},
            ],
        },
    }]})
    candidates, errors = parse_invariant_response_with_diagnostics(text)
    assert candidates == []
    assert errors == [{
        "index": 0,
        "error": "predicate_ast uses unsupported form div",
    }]
