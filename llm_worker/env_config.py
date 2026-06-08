"""Load repo .env and resolve LLM provider / API keys."""

from __future__ import annotations

import os
from pathlib import Path

PROVIDERS = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-pro",
        "supports_thinking": True,
    },
    "openrouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "default_model": "deepseek/deepseek-v4-flash",
        "supports_thinking": False,
    },
}

DEFAULT_PROVIDER = "openrouter"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_env() -> Path | None:
    """Load first existing .env (repo root, then cwd). Returns path or None."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    for candidate in (repo_root() / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return candidate
    return None


def normalize_provider(name: str | None) -> str:
    if isinstance(name, str) and name.strip():
        provider = name.strip().lower()
    else:
        provider = (os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider {provider!r}; expected one of: "
            + ", ".join(sorted(PROVIDERS))
        )
    return provider


def get_llm_provider(name: str | None = None) -> str:
    return normalize_provider(name)


def get_api_key(provider: str | None = None) -> str | None:
    prov = normalize_provider(provider)
    env_name = PROVIDERS[prov]["api_key_env"]
    value = os.environ.get(env_name)
    return value.strip() if value else None


def require_api_key(provider: str | None = None) -> str:
    prov = normalize_provider(provider)
    key = get_api_key(prov)
    if not key:
        env_name = PROVIDERS[prov]["api_key_env"]
        raise RuntimeError(
            f"No API key for provider {prov!r}. Set {env_name} in .env or the environment."
        )
    return key


def default_model(provider: str | None = None) -> str:
    prov = normalize_provider(provider)
    return PROVIDERS[prov]["default_model"]


def any_llm_api_key_configured() -> bool:
    return any(get_api_key(p) for p in PROVIDERS)
