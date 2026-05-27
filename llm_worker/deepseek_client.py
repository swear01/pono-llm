"""
DeepSeek V4 Pro API client via OpenRouter (or direct DeepSeek API).

Supports both:
- OpenRouter:    base_url="https://openrouter.ai/api/v1"
- DeepSeek direct: base_url="https://api.deepseek.com/v1"

Reads API key from DEEPSEEK_API_KEY or OPENROUTER_API_KEY env variable.
"""

import os
import time
import json

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# OpenRouter model IDs for DeepSeek V4
# See: https://openrouter.ai/models
#   deepseek/deepseek-v4-pro      — DeepSeek V4 Pro (paid)
#   deepseek/deepseek-v4-flash    — DeepSeek V4 Flash (paid)
#   deepseek/deepseek-v4-flash:free — DeepSeek V4 Flash (free)
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
# Fallback: direct DeepSeek model name
DEEPSEEK_DIRECT_MODEL = "deepseek-v4-pro"


def get_api_key():
    """Get API key from env, trying multiple common names."""
    for var in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        key = os.environ.get(var)
        if key:
            return key
    return None


def detect_provider(api_key: str):
    """Detect whether we're using OpenRouter or direct DeepSeek.

    OpenRouter keys typically start with 'sk-or-'.
    Direct DeepSeek keys typically start with 'sk-'.
    """
    if api_key and api_key.startswith("sk-or-"):
        return "openrouter"
    return "deepseek-direct"


def get_base_url(provider: str):
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    return "https://api.deepseek.com/v1"


def get_model_name(provider: str, requested_model: str = None):
    """Resolve model name based on provider.

    OpenRouter uses 'deepseek/deepseek-chat' as the canonical ID.
    Direct DeepSeek uses 'deepseek-chat'.
    """
    if requested_model:
        return requested_model
    if provider == "openrouter":
        return DEFAULT_MODEL
    return DEEPSEEK_DIRECT_MODEL


class DeepSeekClient:
    """Client for DeepSeek V4 Pro via OpenRouter or direct API.

    Uses OpenAI-compatible interface.
    """

    def __init__(self,
                 api_key: str = None,
                 model_name: str = None,
                 provider: str = None):
        self.api_key = api_key or get_api_key()
        if not self.api_key:
            raise RuntimeError(
                "No API key found. Set DEEPSEEK_API_KEY or OPENROUTER_API_KEY "
                "environment variable.")

        self.provider = provider or detect_provider(self.api_key)
        self.model_name = get_model_name(self.provider, model_name)
        self.base_url = get_base_url(self.provider)
        self._client = None

        if OpenAI is not None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

        print(f"[deepseek] provider={self.provider} "
              f"base_url={self.base_url} "
              f"model={self.model_name}")

    def call(self, prompt: str, system_prompt: str = None, model_name: str = None):
        """Call LLM API with a prompt.

        Returns:
            tuple: (response_json_text, token_count, latency_ms)
        """
        model = model_name or self.model_name
        if system_prompt is None:
            system_prompt = (
                "You are a hardware verification assistant specializing in "
                "formal verification and lemma generalization for PDR/IC3. "
                "Respond ONLY with valid JSON, no other text.")

        if self._client is not None:
            return self._call_openai(prompt, system_prompt, model)
        else:
            return self._call_direct(prompt, system_prompt, model)

    def _call_openai(self, prompt: str, system_prompt: str, model_name: str):
        """Use OpenAI-compatible client."""
        start = time.time()
        extra = {}
        if self.provider == "openrouter":
            extra["extra_headers"] = {
                "HTTP-Referer": "https://github.com/pono-llm",
                "X-Title": "pono-llm",
            }

        try:
            response = self._client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=32768,
                **extra,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            raise RuntimeError(f"API call failed after {elapsed:.0f}ms: {e}")

        elapsed = (time.time() - start) * 1000

        choice = response.choices[0]
        text = choice.message.content or ""
        # DeepSeek V4 reasoning models may leave content empty; fallback to reasoning_content
        reasoning = getattr(choice.message, 'reasoning_content', None)
        if not text.strip() and reasoning:
            text = reasoning
        token_count = response.usage.total_tokens if response.usage else 0

        # OpenRouter returns finish_reason, check for errors
        finish = getattr(choice, 'finish_reason', 'stop')
        if finish not in ('stop', 'length', None):
            raise RuntimeError(
                f"API returned finish_reason={finish}: {text[:200]}")

        return extract_json(text), token_count, elapsed

    def _call_direct(self, prompt: str, system_prompt: str, model_name: str):
        """Direct HTTP call when openai package is not available."""
        import urllib.request
        import urllib.error

        body = json.dumps({
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 32768,
        }).encode()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/pono-llm"
            headers["X-Title"] = "pono-llm"

        url = f"{self.base_url}/chat/completions"
        req = urllib.request.Request(url, data=body, headers=headers)

        start = time.time()
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read())
            elapsed = (time.time() - start) * 1000

            if "error" in data:
                raise RuntimeError(
                    f"API error: {data['error']}")

            choice = data["choices"][0]
            text = choice["message"].get("content", "") or ""
            # DeepSeek V4 reasoning models: fallback to reasoning_content if content empty
            if not text.strip():
                reasoning = choice["message"].get("reasoning_content", "")
                if reasoning:
                    text = reasoning
            token_count = data.get("usage", {}).get("total_tokens", 0)

            finish = choice.get("finish_reason", "stop")
            if finish not in ('stop', 'length', None):
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
    """Extract JSON object from LLM response. Strips markdown fencing.
    Searches for a JSON object containing expected candidate fields."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # If text starts with '{', try it directly
    if text.startswith("{") and text.endswith("}"):
        return text

    # Search for a JSON object containing candidate keys
    for marker in ('"candidates"', '"batch_id"', '"keep_literals"', '"drop_literals"', '"type"'):
        idx = text.find(marker)
        if idx == -1:
            continue
        # Find the enclosing '{' before this marker
        depth = 0
        start = idx
        while start > 0:
            start -= 1
            if text[start] == '}':
                depth += 1
            elif text[start] == '{':
                if depth == 0:
                    break
                depth -= 1
        # Find the matching '}'
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if start < end:
            return text[start:end]

    return text
