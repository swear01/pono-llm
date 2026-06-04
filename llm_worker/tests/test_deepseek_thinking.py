#!/usr/bin/env python3
"""Unit tests for DeepSeek thinking mode mapping (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deepseek_client import DeepSeekClient


def test_none_disables_thinking():
    client = DeepSeekClient(api_key="sk-test")
    kwargs = {}
    mode = client._apply_thinking_mode(kwargs, "none")
    assert mode == "disabled"
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in kwargs


def test_empty_defaults_to_disabled():
    client = DeepSeekClient(api_key="sk-test")
    kwargs = {}
    mode = client._apply_thinking_mode(kwargs, None)
    assert mode == "disabled"
    assert kwargs["extra_body"]["thinking"]["type"] == "disabled"


def test_high_enables_thinking():
    client = DeepSeekClient(api_key="sk-test")
    kwargs = {}
    mode = client._apply_thinking_mode(kwargs, "high")
    assert mode == "high"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "high"


def test_unknown_effort_falls_back_to_high():
    client = DeepSeekClient(api_key="sk-test")
    kwargs = {}
    client._apply_thinking_mode(kwargs, "bogus")
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "high"


def main():
    test_none_disables_thinking()
    test_empty_defaults_to_disabled()
    test_high_enables_thinking()
    test_unknown_effort_falls_back_to_high()
    print("All test_deepseek_thinking tests passed")


if __name__ == "__main__":
    main()
