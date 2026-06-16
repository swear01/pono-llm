"""
OpenAI-compatible LLM HTTP client for DeepSeek and OpenRouter.

API keys and default provider come from .env / environment (see env_config.py).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from env_config import PROVIDERS, default_model, get_llm_provider, normalize_provider
from openrouter_routing import resolve_openrouter_provider_routing, routing_summary

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Backward-compatible constants
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

_PROVIDER_URLS = {
    "deepseek": DEEPSEEK_BASE_URL,
    "openrouter": OPENROUTER_BASE_URL,
}

_OPENROUTER_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)

# ic3_frame_response is small; json_object mode does not need 32k completion budget.
DEFAULT_MAX_RESPONSE_TOKENS = 4096


def get_api_key(provider: str | None = None):
    from env_config import get_api_key as _get

    return _get(provider)


class LLMClient:
    """Chat-completions client for DeepSeek or OpenRouter."""

    def __init__(
        self,
        api_key: str,
        *,
        provider: str | None = None,
        model_name: str | None = None,
    ):
        if not api_key:
            raise RuntimeError("API key is required")

        self.provider = normalize_provider(provider)
        self.api_key = api_key
        self.model_name = model_name or default_model(self.provider)
        self.base_url = _PROVIDER_URLS[self.provider]
        self._supports_thinking = PROVIDERS[self.provider]["supports_thinking"]
        self._client = None

        if OpenAI is not None:
            client_kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "base_url": self.base_url,
            }
            if self.provider == "openrouter":
                headers = {}
                referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
                title = os.environ.get("OPENROUTER_APP_NAME", "pono-llm").strip()
                if referer:
                    headers["HTTP-Referer"] = referer
                if title:
                    headers["X-Title"] = title
                if headers:
                    client_kwargs["default_headers"] = headers
            self._client = OpenAI(**client_kwargs)

        self._openrouter_routing: dict[str, Any] | None = None
        if self.provider == "openrouter":
            self._openrouter_routing = resolve_openrouter_provider_routing()
            print(
                f"[llm] provider={self.provider} base_url={self.base_url} "
                f"model={self.model_name} routing={routing_summary(self._openrouter_routing)}",
                file=__import__("sys").stderr,
            )
        else:
            print(
                f"[llm] provider={self.provider} base_url={self.base_url} "
                f"model={self.model_name}",
                file=__import__("sys").stderr,
            )
        self.last_call_stats: dict[str, Any] = {}

    def _thinking_payload_target(self, payload: dict) -> dict:
        """Provider knobs live in extra_body (OpenAI SDK) or top-level (urllib)."""
        if self._client is not None:
            return payload.setdefault("extra_body", {})
        return payload

    def _apply_thinking_mode(self, payload: dict, reasoning_effort: str | None = None) -> str:
        effort = (reasoning_effort or "none").lower()

        if self.provider == "openrouter":
            target = self._thinking_payload_target(payload)
            if effort in ("none", "", "off", "disabled"):
                target["reasoning"] = {"effort": "none", "exclude": True}
                return "disabled"
            mapped = effort if effort in _OPENROUTER_REASONING_EFFORTS else "high"
            target["reasoning"] = {"effort": mapped}
            return mapped

        if not self._supports_thinking:
            return "n/a"

        target = self._thinking_payload_target(payload)
        if effort in ("none", "", "off", "disabled"):
            target["thinking"] = {"type": "disabled"}
            return "disabled"
        target["thinking"] = {"type": "enabled"}
        mapped = effort if effort in ("high", "max", "low", "medium", "xhigh") else "high"
        payload["reasoning_effort"] = mapped
        return mapped

    def _apply_openrouter_routing(self, payload: dict) -> None:
        if self.provider != "openrouter" or not self._openrouter_routing:
            return
        if self._client is not None:
            payload.setdefault("extra_body", {})["provider"] = self._openrouter_routing
        else:
            payload["provider"] = self._openrouter_routing

    def _apply_response_format(self, payload: dict) -> None:
        payload["response_format"] = {"type": "json_object"}

    def _message_content(self, text: str) -> str:
        return (text or "").strip()

    def call(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model_name: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        model = model_name or self.model_name
        if system_prompt is None:
            system_prompt = (
                "You are a hardware verification assistant for PDR/IC3. "
                "Output valid json matching ic3_frame_response v1."
            )
        temp = 0.3 if temperature is None else temperature
        cap = max_tokens if max_tokens is not None else DEFAULT_MAX_RESPONSE_TOKENS

        if self._client is not None:
            return self._call_openai(
                prompt, system_prompt, model, temp, reasoning_effort, cap
            )
        return self._call_direct(
            prompt, system_prompt, model, temp, reasoning_effort, cap
        )

    def _call_openai(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
        temperature: float,
        reasoning_effort: str | None = None,
        max_tokens: int = DEFAULT_MAX_RESPONSE_TOKENS,
    ):
        start = time.time()
        kwargs = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        thinking_mode = self._apply_thinking_mode(kwargs, reasoning_effort)
        self._apply_response_format(kwargs)
        self._apply_openrouter_routing(kwargs)

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"API call failed after {elapsed:.0f}ms: {e}") from e

        elapsed = (time.time() - start) * 1000
        choice = response.choices[0]
        text = self._message_content(choice.message.content or "")
        reasoning = getattr(choice.message, "reasoning_content", None) or ""
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        token_count = getattr(usage, "total_tokens", 0) or 0

        stats: dict[str, Any] = {
            "provider": self.provider,
            "json_mode": "json_object",
            "thinking_mode": thinking_mode,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": token_count,
            "reasoning_chars": len(reasoning),
            "content_chars": len(text),
            "latency_ms": elapsed,
        }
        if self._openrouter_routing is not None:
            stats["openrouter_routing"] = self._openrouter_routing
        self.last_call_stats = stats

        finish = getattr(choice, "finish_reason", "stop")
        if finish not in ("stop", "length", None):
            raise RuntimeError(
                f"API returned finish_reason={finish}: {text[:200]}"
            )

        return extract_json(text), token_count, elapsed

    def _call_direct(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
        temperature: float,
        reasoning_effort: str | None = None,
        max_tokens: int = DEFAULT_MAX_RESPONSE_TOKENS,
    ):
        import urllib.error
        import urllib.request

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        thinking_mode = self._apply_thinking_mode(payload, reasoning_effort)
        self._apply_response_format(payload)

        self._apply_openrouter_routing(payload)

        body = json.dumps(payload).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
            title = os.environ.get("OPENROUTER_APP_NAME", "pono-llm").strip()
            if referer:
                headers["HTTP-Referer"] = referer
            if title:
                headers["X-Title"] = title

        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(url, data=body, headers=headers)

        start = time.time()
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            elapsed = (time.time() - start) * 1000

            if "error" in data:
                raise RuntimeError(f"API error: {data['error']}")

            choice = data["choices"][0]
            msg = choice["message"]
            text = self._message_content(msg.get("content", "") or "")
            reasoning = msg.get("reasoning_content", "") or ""
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            token_count = usage.get("total_tokens", 0)
            self.last_call_stats = {
                "provider": self.provider,
                "json_mode": "json_object",
                "thinking_mode": thinking_mode,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": token_count,
                "reasoning_chars": len(reasoning),
                "content_chars": len(text),
                "latency_ms": elapsed,
            }

            finish = choice.get("finish_reason", "stop")
            if finish not in ("stop", "length", None):
                raise RuntimeError(
                    f"API returned finish_reason={finish}: {text[:200]}"
                )

            return extract_json(text), token_count, elapsed
        except urllib.error.HTTPError as e:
            elapsed = (time.time() - start) * 1000
            error_body = e.read().decode()
            raise RuntimeError(
                f"HTTP error {e.code} after {elapsed:.0f}ms: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"URL error after {elapsed:.0f}ms: {e}") from e


def create_llm_client(
    provider: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> LLMClient:
    from env_config import require_api_key

    prov = normalize_provider(provider)
    return LLMClient(
        api_key or require_api_key(prov),
        provider=prov,
        model_name=model_name,
    )


# Backward-compatible alias
class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        from env_config import require_api_key

        super().__init__(
            api_key or require_api_key("deepseek"),
            provider="deepseek",
            model_name=model_name,
        )


def extract_json(text: str) -> str:
    """Normalize API message content to a JSON object string.

    With ``response_format=json_object`` the model returns bare JSON; this only
    strips optional markdown fences if present.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
