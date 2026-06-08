"""Backward-compatible re-exports; prefer llm_client.py for new code."""

from llm_client import (  # noqa: F401
    DEEPSEEK_BASE_URL,
    DEFAULT_MODEL,
    DeepSeekClient,
    LLMClient,
    create_llm_client,
    extract_json,
    get_api_key,
)

__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEFAULT_MODEL",
    "DeepSeekClient",
    "LLMClient",
    "create_llm_client",
    "extract_json",
    "get_api_key",
]
