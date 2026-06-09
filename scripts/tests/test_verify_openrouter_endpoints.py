"""Tests for scripts/verify_openrouter_endpoints.py (mocked HTTP)."""

from __future__ import annotations

import pathlib
import sys

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
_ROOT = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_ROOT / "llm_worker"))

import verify_openrouter_endpoints as vor  # noqa: E402


SAMPLE_ENDPOINTS = [
    {
        "provider_name": "Novita",
        "tag": "novita/deepseek-v4-flash",
        "quantization": "fp8",
        "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
        "uptime_last_1d": 99.0,
        "status": 0,
    },
    {
        "provider_name": "DeepInfra",
        "tag": "deepinfra/deepseek-v4-flash",
        "quantization": "fp4",
        "pricing": {"prompt": "0.00000005", "completion": "0.0000001"},
        "uptime_last_1d": 98.0,
        "status": 0,
    },
    {
        "provider_name": "DeepSeek",
        "tag": "deepseek/deepseek-v4-flash",
        "quantization": "fp8",
        "pricing": {"prompt": "0.00000012", "completion": "0.00000024"},
        "uptime_last_1d": 99.5,
        "status": 0,
    },
]


def test_slug_from_tag():
    assert vor.slug_from_tag("novita/deepseek-v4-flash") == "novita"


def test_check_policy_ok(monkeypatch):
    monkeypatch.setattr(vor, "DEFAULT_ONLY", ["novita", "deepseek"])
    monkeypatch.setattr(vor, "MINIMAL_ONLY", ["novita", "deepseek"])
    assert vor.check_policy(SAMPLE_ENDPOINTS) == 0


def test_check_policy_fails_when_fp4_not_ignored():
    endpoints = [
        {
            "tag": "evil/deepseek-v4-flash",
            "quantization": "fp4",
        }
    ]
    assert vor.check_policy(endpoints) == 1


def test_fetch_endpoints_parses_payload(monkeypatch):
    payload = {"data": {"endpoints": SAMPLE_ENDPOINTS}}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json

            return json.dumps(payload).encode()

    monkeypatch.setattr(vor.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    assert len(vor.fetch_endpoints()) == 3
