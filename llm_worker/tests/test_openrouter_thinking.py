#!/usr/bin/env python3
"""Unit tests for OpenRouter reasoning mode mapping (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_client import LLMClient


def _openrouter_client() -> LLMClient:
    return LLMClient(api_key="sk-test", provider="openrouter")


def test_none_disables_reasoning_in_extra_body():
    client = _openrouter_client()
    kwargs: dict = {}
    mode = client._apply_thinking_mode(kwargs, "none")
    assert mode == "disabled"
    assert kwargs["extra_body"] == {"reasoning": {"effort": "none", "exclude": True}}


def test_empty_defaults_to_disabled():
    client = _openrouter_client()
    kwargs: dict = {}
    mode = client._apply_thinking_mode(kwargs, None)
    assert mode == "disabled"
    assert kwargs["extra_body"]["reasoning"]["effort"] == "none"
    assert kwargs["extra_body"]["reasoning"]["exclude"] is True


def test_high_enables_reasoning():
    client = _openrouter_client()
    kwargs: dict = {}
    mode = client._apply_thinking_mode(kwargs, "high")
    assert mode == "high"
    assert kwargs["extra_body"] == {"reasoning": {"effort": "high"}}


def test_unknown_effort_falls_back_to_high():
    client = _openrouter_client()
    kwargs: dict = {}
    mode = client._apply_thinking_mode(kwargs, "bogus")
    assert mode == "high"
    assert kwargs["extra_body"] == {"reasoning": {"effort": "high"}}


def test_direct_path_uses_top_level_reasoning():
    client = _openrouter_client()
    client._client = None
    payload: dict = {}
    mode = client._apply_thinking_mode(payload, "none")
    assert mode == "disabled"
    assert payload == {"reasoning": {"effort": "none", "exclude": True}}
    assert "extra_body" not in payload


def test_reasoning_merges_with_openrouter_routing():
    client = _openrouter_client()
    client._openrouter_routing = {"only": ["novita"], "sort": "throughput"}
    kwargs: dict = {}
    client._apply_thinking_mode(kwargs, "none")
    client._apply_openrouter_routing(kwargs)
    assert kwargs["extra_body"] == {
        "reasoning": {"effort": "none", "exclude": True},
        "provider": {"only": ["novita"], "sort": "throughput"},
    }


def main():
    test_none_disables_reasoning_in_extra_body()
    test_empty_defaults_to_disabled()
    test_high_enables_reasoning()
    test_unknown_effort_falls_back_to_high()
    test_direct_path_uses_top_level_reasoning()
    test_reasoning_merges_with_openrouter_routing()
    print("All test_openrouter_thinking tests passed")


if __name__ == "__main__":
    main()
