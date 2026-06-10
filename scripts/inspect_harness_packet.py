#!/usr/bin/env python3
"""Inspect Q4 harness_packet + task card metrics from batch JSONL requests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "llm_worker"))

from harness_preprocess import build_harness_packet, harness_metrics, render_task_card


def load_requests(path: Path, max_lines: int = 0) -> list[dict]:
    out: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != "{":
                continue
            out.append(json.loads(line))
            if max_lines and len(out) >= max_lines:
                break
    return out


def inspect_request(req: dict, sample_id: int = 0, emit_packet: bool = False) -> dict:
    metrics = harness_metrics(req, sample_id=sample_id)
    card_preview = render_task_card(req, sample_id=sample_id)
    preview_lines = card_preview.splitlines()[:12]
    result = {
        "batch_id": req.get("batch_id") or req.get("cti_id"),
        "frame_idx": req.get("frame_idx"),
        "attempt": req.get("attempt"),
        "metrics": metrics,
        "task_card_preview": preview_lines,
    }
    if emit_packet:
        result["harness_packet"] = build_harness_packet(req, sample_id=sample_id)
    return result


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {}
    n = len(rows)
    keys = rows[0]["metrics"].keys()
    agg: dict[str, float] = {}
    for key in keys:
        vals = [r["metrics"][key] for r in rows if isinstance(r["metrics"].get(key), (int, float))]
        if vals:
            agg[f"{key}_mean"] = round(sum(vals) / len(vals), 2)
    agg["requests"] = n
    return agg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_jsonl", help="Path to pono_llm_requests.jsonl")
    parser.add_argument("--sample-id", type=int, default=0)
    parser.add_argument("--max-lines", type=int, default=0)
    parser.add_argument("--emit-packet", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    path = Path(args.request_jsonl)
    if not path.is_file():
        print(f"ERROR: not found: {path}", file=sys.stderr)
        return 1

    reqs = load_requests(path, max_lines=args.max_lines)
    rows = [inspect_request(r, args.sample_id, emit_packet=args.emit_packet) for r in reqs]
    report = {"requests": rows, "aggregate": aggregate(rows)}

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Inspected {len(rows)} request(s) from {path}")
    for row in rows:
        m = row["metrics"]
        print(
            f"  {row.get('batch_id')} frame={row.get('frame_idx')} attempt={row.get('attempt')} "
            f"bytes={m.get('user_prompt_bytes')} init_cov={m.get('init_table_coverage_pct')}% "
            f"init_safe_cand={m.get('init_safe_candidates')}/{m.get('candidate_count')}"
        )
    if report["aggregate"]:
        print("\nAggregate:")
        for k, v in sorted(report["aggregate"].items()):
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
