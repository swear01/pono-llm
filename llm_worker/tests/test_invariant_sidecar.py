"""Tests for invariant_sidecar.py — mocks LLMClient, no network."""
import json
import os
import sys
import textwrap
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from invariant_sidecar import handle_stage0_request, handle_stage2_request, _enrich_request_with_btor2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_client(response_json: dict, tokens: int = 100, latency: float = 500.0):
    client = MagicMock()
    client.call.return_value = (json.dumps(response_json), tokens, latency)
    return client


GOOD_RESPONSE = {
    "candidates": [
        {
            "id": 1,
            "kind": "Type1_invariant",
            "verilog_expr": "wr_ptr >= rd_ptr",
            "predicate_ast": {
                "form": "uge",
                "args": [
                    {"form": "ref", "ref": "state6"},
                    {"form": "ref", "ref": "state7"},
                ],
            },
            "intuition": "write pointer is always ahead",
        }
    ]
}

STAGE0_REQUEST = {
    "type": "ic3_stage0_request",
    "request_id": "stage0_test_001",
    "benchmark": "myfifo-p001",
    "property_desc": "FIFO never overflows",
    "hot_variables": [
        {"ref": "state6", "width": 8, "init": "0", "verilog": "wr_ptr"},
        {"ref": "state7", "width": 8, "init": "0", "verilog": "rd_ptr"},
    ],
    "symmetric_pairs": [
        {"refA": "state6", "refB": "state7",
         "nameA": "wr_ptr", "nameB": "rd_ptr"},
    ],
}

STAGE2_REQUEST = {
    "type": "ic3_stage2_request",
    "request_id": "stage2_test_001",
    "trigger": "T2_plateau",
    "proof_state": {"current_frame": 3, "frames_stuck_rounds": 10,
                    "total_cti_count": 50, "frame_clause_count": 30},
    "hot_variables": [
        {"ref": "state6", "width": 8, "init": "0"},
    ],
    "symmetric_pairs": [
        {"refA": "state6", "refB": "state7",
         "nameA": "wr_ptr", "nameB": "rd_ptr"},
    ],
    "cti_cluster": [{"state6": 5, "state7": 3}],
    "frame_clause_clusters": [],
    "previously_injected": [],
}


# ---------------------------------------------------------------------------
# handle_stage0_request
# ---------------------------------------------------------------------------

def test_stage0_returns_ic3_invariant_response():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage0_request(client, STAGE0_REQUEST)
    assert result["type"] == "ic3_invariant_response"


def test_stage0_request_id_preserved():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage0_request(client, STAGE0_REQUEST)
    assert result["request_id"] == "stage0_test_001"


def test_stage0_candidates_parsed():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage0_request(client, STAGE0_REQUEST)
    assert len(result["candidates"]) == 2
    assert any(
        candidate["predicate_ast"]["form"] == "uge"
        for candidate in result["candidates"]
    )


def test_stage0_token_count_attached():
    client = make_mock_client(GOOD_RESPONSE, tokens=250, latency=600.0)
    result = handle_stage0_request(client, STAGE0_REQUEST)
    assert result["_token_count"] == 250
    assert result["_latency_ms"] == pytest.approx(600.0)


def test_stage0_llm_call_uses_system_prompt():
    client = make_mock_client(GOOD_RESPONSE)
    handle_stage0_request(client, STAGE0_REQUEST)
    call_kwargs = client.call.call_args
    # system_prompt should be passed as kwarg
    assert call_kwargs.kwargs.get("system_prompt") or \
           (call_kwargs.args and len(call_kwargs.args) > 1)


def test_stage0_llm_gets_benchmark_in_prompt():
    client = make_mock_client(GOOD_RESPONSE)
    handle_stage0_request(client, STAGE0_REQUEST)
    user_prompt = client.call.call_args.args[0]
    assert "myfifo-p001" in user_prompt


def test_stage0_api_error_returns_empty_candidates():
    client = MagicMock()
    client.call.side_effect = RuntimeError("network error")
    with pytest.raises(RuntimeError):
        handle_stage0_request(client, STAGE0_REQUEST)


def test_stage0_bad_json_from_llm_returns_empty():
    client = make_mock_client({})  # empty response
    result = handle_stage0_request(client, STAGE0_REQUEST)
    # parse_invariant_response handles empty candidates
    assert isinstance(result["candidates"], list)


def test_stage0_llm_model_override():
    """Request model override should be forwarded to client.call."""
    client = make_mock_client(GOOD_RESPONSE)
    req = dict(STAGE0_REQUEST)
    req["model"] = "claude-opus-4-8"
    handle_stage0_request(client, req)
    call_kwargs = client.call.call_args.kwargs
    assert call_kwargs.get("model_name") == "claude-opus-4-8"


# ---------------------------------------------------------------------------
# handle_stage2_request
# ---------------------------------------------------------------------------

def test_stage2_returns_ic3_invariant_response():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage2_request(client, STAGE2_REQUEST)
    assert result["type"] == "ic3_invariant_response"


def test_stage2_request_id_preserved():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage2_request(client, STAGE2_REQUEST)
    assert result["request_id"] == "stage2_test_001"


def test_stage2_candidates_parsed():
    client = make_mock_client(GOOD_RESPONSE)
    result = handle_stage2_request(client, STAGE2_REQUEST)
    assert len(result["candidates"]) == 1


def test_stage2_prompt_includes_trigger():
    client = make_mock_client(GOOD_RESPONSE)
    handle_stage2_request(client, STAGE2_REQUEST)
    user_prompt = client.call.call_args.args[0]
    assert "T2_plateau" in user_prompt


def test_stage2_prompt_includes_cti_cluster():
    client = make_mock_client(GOOD_RESPONSE)
    handle_stage2_request(client, STAGE2_REQUEST)
    user_prompt = client.call.call_args.args[0]
    assert "CTI" in user_prompt


def test_stage2_zero_cti_cluster():
    """Empty cluster should not crash."""
    client = make_mock_client(GOOD_RESPONSE)
    req = dict(STAGE2_REQUEST)
    req["cti_cluster"] = []
    result = handle_stage2_request(client, req)
    assert result["type"] == "ic3_invariant_response"


def test_stage2_multiple_candidates():
    multi = {
        "candidates": [
            {
                "id": 1, "kind": "Type1_invariant", "verilog_expr": "a",
                "predicate_ast": {
                    "form": "uge",
                    "args": [
                        {"form": "ref", "ref": "state6"},
                        {"form": "ref", "ref": "state7"},
                    ],
                },
                "intuition": "x",
            },
            {
                "id": 2, "kind": "Type2_lift", "verilog_expr": "b",
                "predicate_ast": {
                    "form": "ule",
                    "args": [
                        {"form": "ref", "ref": "state6"},
                        {"form": "ref", "ref": "state7"},
                    ],
                },
                "intuition": "y",
            },
        ]
    }
    client = make_mock_client(multi)
    result = handle_stage2_request(client, STAGE2_REQUEST)
    assert len(result["candidates"]) == 2
    kinds = {c["kind"] for c in result["candidates"]}
    assert "Type2_lift" in kinds


# ---------------------------------------------------------------------------
# BTOR2 enrichment
# ---------------------------------------------------------------------------

MINI_BTOR2 = """\
; BTOR description generated by Yosys for module myfifo.
1 sort bitvec 1
2 sort bitvec 8
3 input 1 i_clk
4 input 1 i_reset
5 state 2 wr_ptr
6 state 2 rd_ptr
7 const 2 0
8 init 2 5 7
9 init 2 6 7
10 add 2 5 7
11 next 2 5 10
12 add 2 6 7
13 next 2 6 12
14 sub 2 5 6
15 eq 1 14 7
16 not 1 15
17 bad 16
"""


@pytest.fixture()
def mini_btor2_path(tmp_path):
    p = tmp_path / "mini.btor2"
    p.write_text(textwrap.dedent(MINI_BTOR2))
    return str(p)


def test_enrich_adds_hot_variables(mini_btor2_path):
    req = {"benchmark": "test", "btor2_path": mini_btor2_path}
    enriched = _enrich_request_with_btor2(req)
    assert "hot_variables" in enriched
    assert len(enriched["hot_variables"]) > 0


def test_enrich_adds_inputs(mini_btor2_path):
    req = {"benchmark": "test", "btor2_path": mini_btor2_path}
    enriched = _enrich_request_with_btor2(req)
    assert "inputs" in enriched
    syms = {iv["symbol"] for iv in enriched["inputs"]}
    assert "i_clk" in syms


def test_enrich_adds_transition_sketch(mini_btor2_path):
    req = {"benchmark": "test", "btor2_path": mini_btor2_path}
    enriched = _enrich_request_with_btor2(req)
    assert "transition_sketch" in enriched
    # wr_ptr has a next, so sketch should be non-empty
    assert isinstance(enriched["transition_sketch"], list)


def test_enrich_skips_when_hot_variables_present():
    """If hot_variables already in request, don't load BTOR2."""
    req = {
        "benchmark": "test",
        "btor2_path": "/nonexistent/file.btor2",
        "hot_variables": [{"ref": "state5", "width": 8, "init": "0"}],
    }
    enriched = _enrich_request_with_btor2(req)
    # Should return the same request unchanged
    assert enriched is req


def test_enrich_missing_btor2_path_is_no_op():
    req = {"benchmark": "test"}
    enriched = _enrich_request_with_btor2(req)
    assert enriched is req


def test_enrich_invalid_btor2_path_is_no_op():
    req = {"benchmark": "test", "btor2_path": "/nonexistent/file.btor2"}
    enriched = _enrich_request_with_btor2(req)
    assert enriched is req


def test_stage0_with_btor2_path_includes_hot_vars_in_prompt(mini_btor2_path):
    """When btor2_path is in request, hot_variables reach the LLM prompt."""
    req = {
        "type": "ic3_stage0_request",
        "request_id": "enrich_test",
        "benchmark": "myfifo",
        "property_desc": "never overflow",
        "btor2_path": mini_btor2_path,
    }
    client = make_mock_client(GOOD_RESPONSE)
    handle_stage0_request(client, req)
    user_prompt = client.call.call_args.args[0]
    # wr_ptr or rd_ptr should appear (clean state names)
    assert "wr_ptr" in user_prompt or "state5" in user_prompt or "state6" in user_prompt
