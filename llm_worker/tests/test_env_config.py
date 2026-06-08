"""Tests for .env / provider resolution (no API calls)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env_config import (
    default_model,
    get_api_key,
    get_llm_provider,
    normalize_provider,
)


def test_default_provider_is_openrouter():
    assert get_llm_provider("") == "openrouter"


def test_openrouter_provider():
    assert normalize_provider("openrouter") == "openrouter"


def test_default_model_per_provider():
    assert default_model("deepseek") == "deepseek-v4-pro"
    assert default_model("openrouter") == "deepseek/deepseek-v4-flash"


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    assert get_api_key("openrouter") == "or-test-key"
