"""
DeepSeek API client (OpenAI-compatible HTTP API).

Reads API key from DEEPSEEK_API_KEY environment variable.
Uses the official `openai` Python package as HTTP client (not OpenAI models).
"""

import json
import os
import time

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-pro"


def get_api_key():
    """Return DEEPSEEK_API_KEY from the environment."""
    return os.environ.get("DEEPSEEK_API_KEY")


class DeepSeekClient:
    """Client for DeepSeek chat completions via OpenAI-compatible SDK."""

    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or get_api_key()
        if not self.api_key:
            raise RuntimeError(
                "No API key found. Set DEEPSEEK_API_KEY environment variable.")

        self.model_name = model_name or DEFAULT_MODEL
        self.base_url = DEEPSEEK_BASE_URL
        self._client = None

        if OpenAI is not None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

        print(f"[deepseek] base_url={self.base_url} model={self.model_name}")
        self.last_call_stats = {}

    def _apply_thinking_mode(self, kwargs: dict, reasoning_effort: str = None) -> str:
        """Map reasoning_effort to DeepSeek V4 thinking API.

        Official API: reasoning_effort is only high|max (no 'none').
        Non-thinking: extra_body thinking.type=disabled (see api-docs thinking_mode).
        """
        effort = (reasoning_effort or "none").lower()
        if effort in ("none", "", "off", "disabled"):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            return "disabled"
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        if effort in ("high", "max", "low", "medium", "xhigh"):
            kwargs["reasoning_effort"] = effort
        else:
            kwargs["reasoning_effort"] = "high"
        return effort

    def call(self,
             prompt: str,
             system_prompt: str = None,
             model_name: str = None,
             reasoning_effort: str = None,
             temperature: float = None):
        """Call DeepSeek API with a prompt.

        Returns:
            tuple: (response_json_text, token_count, latency_ms)
        """
        model = model_name or self.model_name
        if system_prompt is None:
            system_prompt = (
                "You are a hardware verification assistant specializing in "
                "formal verification and lemma generalization for PDR/IC3. "
                "Respond ONLY with valid JSON, no other text.")
        temp = 0.3 if temperature is None else temperature

        if self._client is not None:
            return self._call_openai(prompt, system_prompt, model, temp, reasoning_effort)
        return self._call_direct(prompt, system_prompt, model, temp, reasoning_effort)

    def _call_openai(self,
                     prompt: str,
                     system_prompt: str,
                     model_name: str,
                     temperature: float,
                     reasoning_effort: str = None):
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

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"API call failed after {elapsed:.0f}ms: {e}")

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

        self.last_call_stats = {
            "thinking_mode": thinking_mode,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": token_count,
            "reasoning_chars": len(reasoning),
            "content_chars": len(text),
            "latency_ms": elapsed,
        }

        finish = getattr(choice, "finish_reason", "stop")
        if finish not in ("stop", "length", None):
            raise RuntimeError(
                f"API returned finish_reason={finish}: {text[:200]}")

        return extract_json(text), token_count, elapsed

    def _call_direct(self,
                     prompt: str,
                     system_prompt: str,
                     model_name: str,
                     temperature: float,
                     reasoning_effort: str = None):
        """Direct HTTP call when openai package is not available."""
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
        thinking_mode = "disabled"
        effort = (reasoning_effort or "none").lower()
        if effort in ("none", "", "off", "disabled"):
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["thinking"] = {"type": "enabled"}
            thinking_mode = effort if effort in ("high", "max") else "high"
            payload["reasoning_effort"] = thinking_mode
        body = json.dumps(payload).encode()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
                    f"API returned finish_reason={finish}: {text[:200]}")

            return extract_json(text), token_count, elapsed
        except urllib.error.HTTPError as e:
            elapsed = (time.time() - start) * 1000
            error_body = e.read().decode()
            raise RuntimeError(
                f"HTTP error {e.code} after {elapsed:.0f}ms: {error_body}")
        except urllib.error.URLError as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"URL error after {elapsed:.0f}ms: {e}")


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
