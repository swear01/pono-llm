"""Tests for llm_client.extract_json fence stripping (no network)."""

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


def test_strips_whitespace():
    raw = '  \n{"type":"ic3_frame_response"}\n  '
    assert extract_json(raw) == '{"type":"ic3_frame_response"}'
