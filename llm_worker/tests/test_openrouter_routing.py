"""Tests for OpenRouter provider routing (no API calls)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openrouter_routing import (
    DEFAULT_IGNORE,
    DEFAULT_ONLY,
    MINIMAL_ONLY,
    resolve_openrouter_provider_routing,
)


def test_default_routing_excludes_fp4_via_quantizations(monkeypatch):
    monkeypatch.delenv("OPENROUTER_PROVIDER_ONLY", raising=False)
    monkeypatch.setenv("OPENROUTER_ROUTING_PRESET", "default")
    routing = resolve_openrouter_provider_routing()
    assert "deepinfra" in routing["ignore"]
    assert "fp4" not in routing["quantizations"]
    assert "fp8" in routing["quantizations"]
    assert routing["sort"] == "throughput"
    assert "novita" in routing["only"]
    assert "siliconflow" not in routing["only"]


def test_minimal_preset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_ROUTING_PRESET", "minimal")
    routing = resolve_openrouter_provider_routing()
    assert routing["only"] == MINIMAL_ONLY


def test_only_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROVIDER_ONLY", "novita,deepseek")
    routing = resolve_openrouter_provider_routing()
    assert routing["only"] == ["novita", "deepseek"]


def test_minimal_subset_of_default():
    assert set(MINIMAL_ONLY).issubset(set(DEFAULT_ONLY))


def test_fp4_provider_ignored():
    assert "deepinfra" in DEFAULT_IGNORE
