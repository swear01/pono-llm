"""Tests for llm_client.extract_json (no network)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_client import extract_json


def test_plain_json():
    raw = '{"type":"ic3_frame_response","block_clauses":[]}'
    assert extract_json(raw) == raw


def test_fenced_json():
    raw = '```json\n{"type":"ic3_frame_response","block_clauses":[]}\n```'
    out = extract_json(raw)
    assert json.loads(out)["type"] == "ic3_frame_response"


def test_preamble_before_json():
    raw = (
        "Analysis: long reasoning here...\n"
        '{"type":"ic3_frame_response","source_cti_id":"batch_f1_a1",'
        '"block_clauses":[[{"ref":"state5","op":"eq","rhs":"0","polarity":true}]]}'
    )
    out = extract_json(raw)
    parsed = json.loads(out)
    assert parsed["source_cti_id"] == "batch_f1_a1"
    assert parsed["block_clauses"][0][0]["ref"] == "state5"


def test_block_disjuncts_marker():
    raw = 'prefix text {"block_disjuncts":[{"ref":"state1","op":"eq","rhs":"0","polarity":false}]}'
    out = extract_json(raw)
    assert "block_disjuncts" in out
