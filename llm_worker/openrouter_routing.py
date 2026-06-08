"""OpenRouter provider routing for deepseek/deepseek-v4-flash experiments.

Curated from OpenRouter /models/.../endpoints (2026-06):
- Drop fp4 (DeepInfra), overpriced (Venice), unstable/low-uptime mirrors.
- Prefer fp8 + official/unknown quant with high uptime.

See docs/plans/openrouter_provider_policy.md
"""

from __future__ import annotations

import json
import os
from typing import Any

# Provider slugs for OpenRouter `provider.only` (not tag suffixes like novita/fp8).
DEFAULT_ONLY: list[str] = [
    "novita",
    "deepseek",
    "baidu",
    "parasail",
    "alibaba",
    "streamlake",
    "atlas-cloud",
]

# Faster/cheaper core; fallbacks still allowed within this pool.
MINIMAL_ONLY: list[str] = [
    "novita",
    "deepseek",
    "baidu",
]

# Excluded from experiments (documented; use OPENROUTER_PROVIDER_IGNORE to extend).
DEFAULT_IGNORE: list[str] = [
    "deepinfra",      # fp4
    "venice",         # expensive
    "gmicloud",       # unstable
    "digitalocean",   # unstable
    "cloudflare",     # 384K context
    "morph",          # lower uptime
    "akashml",        # lower uptime
    "siliconflow",    # status -2 / ~94% up30m at audit time
]

# fp8 + full-precision-ish; excludes fp4/int quant mirrors.
DEFAULT_QUANTIZATIONS: list[str] = [
    "fp8",
    "fp16",
    "bf16",
    "fp32",
    "unknown",
]


def _parse_csv_slugs(value: str) -> list[str]:
    return [s.strip().lower() for s in value.split(",") if s.strip()]


def resolve_openrouter_provider_routing(
    *,
    preset: str | None = None,
) -> dict[str, Any]:
    """Build OpenRouter `provider` object for chat/completions extra_body."""
    preset_name = (
        preset
        or os.environ.get("OPENROUTER_ROUTING_PRESET", "default")
    ).strip().lower()

    if preset_name in ("minimal", "fast"):
        only = list(MINIMAL_ONLY)
    elif preset_name in ("default", "", "full"):
        only = list(DEFAULT_ONLY)
    else:
        raise ValueError(
            f"Unknown OPENROUTER_ROUTING_PRESET {preset_name!r}; "
            "use default, minimal, or full"
        )

    only_override = os.environ.get("OPENROUTER_PROVIDER_ONLY", "").strip()
    if only_override:
        only = _parse_csv_slugs(only_override)

    ignore = list(DEFAULT_IGNORE)
    ignore_override = os.environ.get("OPENROUTER_PROVIDER_IGNORE", "").strip()
    if ignore_override:
        ignore = _parse_csv_slugs(ignore_override)

    quant_override = os.environ.get("OPENROUTER_QUANTIZATIONS", "").strip()
    quantizations = (
        _parse_csv_slugs(quant_override)
        if quant_override
        else list(DEFAULT_QUANTIZATIONS)
    )

    allow_fallbacks = os.environ.get("OPENROUTER_ALLOW_FALLBACKS", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    sort_mode = os.environ.get("OPENROUTER_PROVIDER_SORT", "throughput").strip() or "throughput"

    routing: dict[str, Any] = {
        "sort": sort_mode,
        "only": only,
        "ignore": ignore,
        "quantizations": quantizations,
        "allow_fallbacks": allow_fallbacks,
    }
    return routing


def routing_summary(routing: dict[str, Any]) -> str:
    return json.dumps(
        {
            "sort": routing.get("sort"),
            "only": routing.get("only"),
            "ignore": routing.get("ignore"),
            "quantizations": routing.get("quantizations"),
            "allow_fallbacks": routing.get("allow_fallbacks"),
        },
        sort_keys=True,
    )
