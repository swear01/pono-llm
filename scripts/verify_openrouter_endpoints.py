#!/usr/bin/env python3
"""Audit OpenRouter deepseek-v4-flash endpoints vs repo provider policy."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "llm_worker"))

from openrouter_routing import (  # noqa: E402
    DEFAULT_IGNORE,
    DEFAULT_ONLY,
    DEFAULT_QUANTIZATIONS,
    MINIMAL_ONLY,
)

ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints"


def fetch_endpoints() -> list[dict]:
    with urllib.request.urlopen(ENDPOINTS_URL, timeout=30) as resp:
        data = json.load(resp)
    return data["data"]["endpoints"]


def slug_from_tag(tag: str) -> str:
    return tag.split("/")[0].lower() if tag else ""


def print_table(endpoints: list[dict]) -> None:
    rows = []
    for e in endpoints:
        p = e.get("pricing") or {}
        rows.append(
            (
                e.get("provider_name"),
                e.get("tag"),
                e.get("quantization"),
                float(p.get("prompt", 0)) * 1e6,
                float(p.get("completion", 0)) * 1e6,
                e.get("uptime_last_1d"),
                e.get("status"),
            )
        )
    rows.sort(key=lambda r: r[3] + r[4])
    print(f"{'provider':14} {'tag':22} {'quant':8} {'in':>7} {'out':>7} {'up1d':>6} {'st':>3}")
    for r in rows:
        print(f"{r[0]:14} {str(r[1]):22} {str(r[2]):8} {r[3]:7.3f} {r[4]:7.3f} {r[5] or 0:6.1f} {r[6]:3}")


def check_policy(endpoints: list[dict]) -> int:
    errors: list[str] = []
    slugs = {slug_from_tag(e.get("tag", "")) for e in endpoints}
    fp4 = [e for e in endpoints if (e.get("quantization") or "").lower() == "fp4"]

    for e in fp4:
        slug = slug_from_tag(e.get("tag", ""))
        if slug not in DEFAULT_IGNORE:
            errors.append(f"fp4 provider {slug!r} should be in DEFAULT_IGNORE")

    for slug in DEFAULT_ONLY:
        if slug not in slugs:
            errors.append(f"default only slug {slug!r} not in live endpoints (may be transient)")

    if "fp4" in DEFAULT_QUANTIZATIONS:
        errors.append("DEFAULT_QUANTIZATIONS must not include fp4")

    for slug in MINIMAL_ONLY:
        if slug not in DEFAULT_ONLY:
            errors.append(f"minimal slug {slug!r} must be subset of DEFAULT_ONLY")

    if errors:
        print("POLICY CHECK FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("POLICY CHECK OK")
    print(f"  default only ({len(DEFAULT_ONLY)}): {', '.join(DEFAULT_ONLY)}")
    print(f"  minimal ({len(MINIMAL_ONLY)}): {', '.join(MINIMAL_ONLY)}")
    print(f"  ignore ({len(DEFAULT_IGNORE)}): {', '.join(DEFAULT_IGNORE)}")
    if fp4:
        print(f"  fp4 endpoints blocked: {', '.join(slug_from_tag(e.get('tag','')) for e in fp4)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-policy", action="store_true", help="Validate routing policy vs live endpoints")
    args = parser.parse_args()

    endpoints = fetch_endpoints()
    print(f"Fetched {len(endpoints)} endpoints for deepseek/deepseek-v4-flash\n")
    print_table(endpoints)
    print()
    if args.check_policy:
        return check_policy(endpoints)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
