"""Tests for permanent JSON object mode wiring (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_client import LLMClient


def _client(provider: str = "deepseek") -> LLMClient:
    return LLMClient(api_key="sk-test", provider=provider)


def test_apply_response_format_always_json_object():
    client = _client()
    kwargs: dict = {}
    client._apply_response_format(kwargs)
    assert kwargs == {"response_format": {"type": "json_object"}}


def test_call_openai_payload_includes_json_object():
    client = _client("openrouter")
    captured: dict = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class _Msg:
                content = '{"type":"ic3_frame_response","block_clauses":[]}'
                reasoning_content = "must not be used as output"

            class _Choice:
                message = _Msg()
                finish_reason = "stop"

            class _Usage:
                prompt_tokens = 1
                completion_tokens = 2
                total_tokens = 3

            class _Resp:
                choices = [_Choice()]
                usage = _Usage()

            return _Resp()

    class _FakeClient:
        chat = type("Chat", (), {"completions": _FakeCompletions()})()

    client._client = _FakeClient()
    text, _, _ = client.call("user json task", system_prompt="system json rules")
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 4096
    assert text.startswith("{")


def test_message_content_ignores_empty():
    client = _client()
    assert client._message_content("  \n") == ""
