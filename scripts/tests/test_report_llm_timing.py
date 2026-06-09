"""Tests for scripts/report_llm_timing.py."""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS_DIR))

import report_llm_timing as rlt  # noqa: E402


def test_load_entries_skips_bad_lines(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text('{"latency_ms": 10}\nnot json\n{"latency_ms": 20}\n')
    entries = rlt.load_entries(p)
    assert len(entries) == 2


def test_summarize_includes_completion_and_thinking_mode(tmp_path):
    entries = [
        {
            "latency_ms": 1000,
            "user_prompt_bytes": 500,
            "prompt_tokens": 400,
            "completion_tokens": 50,
            "thinking_mode": "disabled",
        },
        {
            "latency_ms": 2000,
            "user_prompt_bytes": 600,
            "prompt_tokens": 450,
            "completion_tokens": 60,
            "thinking_mode": "disabled",
        },
    ]
    summary = rlt.summarize(entries)
    assert summary["count"] == 2
    assert summary["completion_tokens"]["mean"] == 55
    assert summary["thinking_mode"] == "disabled"


def test_summarize_empty():
    assert rlt.summarize([]) == {"count": 0}


def test_main_json_output(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    p.write_text(
        json.dumps({
            "latency_ms": 1500,
            "user_prompt_bytes": 1000,
            "prompt_tokens": 800,
            "completion_tokens": 30,
            "thinking_mode": "disabled",
        }) + "\n"
    )
    import subprocess

    out = subprocess.check_output(
        [sys.executable, str(_SCRIPTS_DIR / "report_llm_timing.py"), str(p), "--json"],
        text=True,
    )
    data = json.loads(out)
    assert data["count"] == 1
    assert data["completion_tokens"]["mean"] == 30
    assert data["thinking_mode"] == "disabled"
