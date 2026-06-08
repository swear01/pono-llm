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
                f"model={self.model_name} routing={routing_summary(self._openrouter_routing)}"
            )
        else:
            print(
                f"[llm] provider={self.provider} base_url={self.base_url} "
                f"model={self.model_name}"
            )
        self.last_call_stats: dict[str, Any] = {}

    def _apply_thinking_mode(self, kwargs: dict, reasoning_effort: str | None = None) -> str:
        if not self._supports_thinking:
            return "n/a"
        effort = (reasoning_effort or "none").lower()
        extra = kwargs.setdefault("extra_body", {})
        if effort in ("none", "", "off", "disabled"):
            extra["thinking"] = {"type": "disabled"}
            return "disabled"
        extra["thinking"] = {"type": "enabled"}
        if effort in ("high", "max", "low", "medium", "xhigh"):
            kwargs["reasoning_effort"] = effort
        else:
            kwargs["reasoning_effort"] = "high"
        return effort

    def _apply_openrouter_routing(self, payload: dict) -> None:
        if self.provider != "openrouter" or not self._openrouter_routing:
            return
        if self._client is not None:
            payload.setdefault("extra_body", {})["provider"] = self._openrouter_routing
        else:
            payload["provider"] = self._openrouter_routing

    def call(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model_name: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
    ):
        model = model_name or self.model_name
        if system_prompt is None:
            system_prompt = (
                "You are a hardware verification assistant specializing in "
                "formal verification and lemma generalization for PDR/IC3. "
                "Respond ONLY with valid JSON, no other text."
            )
        temp = 0.3 if temperature is None else temperature

        if self._client is not None:
            return self._call_openai(prompt, system_prompt, model, temp, reasoning_effort)
        return self._call_direct(prompt, system_prompt, model, temp, reasoning_effort)

    def _call_openai(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
        temperature: float,
        reasoning_effort: str | None = None,
    ):
        start = time.time()
        kwargs = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 32768,
        }
        thinking_mode = self._apply_thinking_mode(kwargs, reasoning_effort)
        self._apply_openrouter_routing(kwargs)

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"API call failed after {elapsed:.0f}ms: {e}") from e

        elapsed = (time.time() - start) * 1000
        choice = response.choices[0]
        text = choice.message.content or ""
        reasoning = getattr(choice.message, "reasoning_content", None) or ""
        if not text.strip() and reasoning:
            text = reasoning
        usage = response.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        token_count = getattr(usage, "total_tokens", 0) or 0

        stats: dict[str, Any] = {
            "provider": self.provider,
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
            "max_tokens": 32768,
        }
        thinking_mode = "n/a"
        if self._supports_thinking:
            effort = (reasoning_effort or "none").lower()
            if effort in ("none", "", "off", "disabled"):
                payload["thinking"] = {"type": "disabled"}
                thinking_mode = "disabled"
            else:
                payload["thinking"] = {"type": "enabled"}
                thinking_mode = effort if effort in ("high", "max") else "high"
                payload["reasoning_effort"] = thinking_mode

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
            text = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            if not text.strip() and reasoning:
                text = reasoning
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            token_count = usage.get("total_tokens", 0)
            self.last_call_stats = {
                "provider": self.provider,
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
    """Extract JSON object from LLM response. Strips markdown fencing."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    for marker in ('"block_disjuncts"', '"source_cti_id"', '"type"', '"actions"'):
        idx = text.find(marker)
        if idx == -1:
            continue
        depth = 0
        start = idx
        while start > 0:
            start -= 1
            if text[start] == "}":
                depth += 1
            elif text[start] == "{":
                if depth == 0:
                    break
                depth -= 1
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if start < end:
            return text[start:end]

    return text
