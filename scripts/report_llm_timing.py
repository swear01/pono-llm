#!/usr/bin/env python3
"""Summarize latency and prompt size from sidecar llm_log.jsonl."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_entries(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def summarize(entries: list[dict]) -> dict:
    if not entries:
        return {"count": 0}

    latencies = [float(e.get("latency_ms", 0)) for e in entries]
    user_bytes = [int(e.get("user_prompt_bytes", 0)) for e in entries]
    prompt_tokens = [
        int(e["prompt_tokens"])
        for e in entries
        if e.get("prompt_tokens") is not None
    ]

    out = {
        "count": len(entries),
        "latency_ms": {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
        },
        "user_prompt_bytes": {
            "min": min(user_bytes),
            "max": max(user_bytes),
            "mean": int(statistics.mean(user_bytes)),
        },
    }
    if prompt_tokens:
        out["prompt_tokens"] = {
            "min": min(prompt_tokens),
            "max": max(prompt_tokens),
            "mean": int(statistics.mean(prompt_tokens)),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Report LLM timing from llm_log.jsonl")
    parser.add_argument("log_path", nargs="?", default="/tmp/pono_llm_log.jsonl")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    path = Path(args.log_path)
    entries = load_entries(path)
    summary = summarize(entries)

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(f"log: {path}")
    print(f"entries: {summary.get('count', 0)}")
    if summary.get("count", 0) == 0:
        return 1

    lat = summary["latency_ms"]
    ub = summary["user_prompt_bytes"]
    print(f"latency_ms: min={lat['min']:.0f} max={lat['max']:.0f} "
          f"mean={lat['mean']:.0f} median={lat['median']:.0f}")
    print(f"user_prompt_bytes: min={ub['min']} max={ub['max']} mean={ub['mean']}")
    if "prompt_tokens" in summary:
        pt = summary["prompt_tokens"]
        print(f"prompt_tokens: min={pt['min']} max={pt['max']} mean={pt['mean']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
