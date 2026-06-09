"""Tests for scripts/smoke_channel_health.py (smoke dry-run checks)."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS_DIR))

import smoke_channel_health as sch  # noqa: E402


def _write_batch_req(path: pathlib.Path, n: int = 1) -> None:
    lines = [
        json.dumps({"type": "ic3_frame_batch_request", "batch_id": f"b{i}"})
        for i in range(n)
    ]
    path.write_text("\n".join(lines) + "\n")


def _write_responses(path: pathlib.Path, n: int) -> None:
    lines = [json.dumps({"type": "ic3_frame_response", "sample_id": i}) for i in range(n)]
    path.write_text("\n".join(lines) + "\n")


def test_healthy_channel_passes(tmp_path):
    req = tmp_path / "requests.jsonl"
    resp = tmp_path / "responses.jsonl"
    _write_batch_req(req, 2)
    _write_responses(resp, 2)
    errors, summary = sch.evaluate_channel_health(
        req_path=req, resp_path=resp, strict=True, parallel=1
    )
    assert errors == []
    assert summary["strict_pass"] is True
    assert summary["requests"] == 2
    assert summary["responses"] == 2


def test_mismatched_response_count_fails(tmp_path):
    req = tmp_path / "requests.jsonl"
    resp = tmp_path / "responses.jsonl"
    _write_batch_req(req, 2)
    _write_responses(resp, 1)
    errors, summary = sch.evaluate_channel_health(
        req_path=req, resp_path=resp, strict=True, parallel=1
    )
    assert summary["strict_pass"] is False
    assert any("responses" in e for e in errors)


def test_batch_timeout_in_llm_stats_fails(tmp_path):
    req = tmp_path / "requests.jsonl"
    resp = tmp_path / "responses.jsonl"
    _write_batch_req(req, 1)
    _write_responses(resp, 1)
    errors, _ = sch.evaluate_channel_health(
        req_path=req,
        resp_path=resp,
        strict=True,
        llm_stats={"batch_timeouts": 1},
    )
    assert any("batch_timeouts" in e for e in errors)


def test_no_requests_strict_fails(tmp_path):
    req = tmp_path / "requests.jsonl"
    resp = tmp_path / "responses.jsonl"
    req.write_text("")
    resp.write_text("")
    errors, summary = sch.evaluate_channel_health(
        req_path=req, resp_path=resp, strict=True
    )
    assert summary["strict_pass"] is False
    assert any("no batch requests" in e for e in errors)
