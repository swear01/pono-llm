#!/usr/bin/env python3
"""Merge independent replay matrices and summarize solve reliability."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


TIMING_FIELDS = (
    "proof_time_sec",
    "certificate_time_sec",
    "model_checker_time_sec",
    "candidate_generation_sec",
    "candidate_processing_sec",
    "offline_time_sec",
    "end_to_end_sec",
)


def read_rows(paths: list[Path]) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    fieldnames: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    for path in paths:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"matrix has no CSV header: {path}")
            for field in reader.fieldnames:
                if field not in fieldnames:
                    fieldnames.append(field)
            for row in reader:
                row["source_matrix"] = path.as_posix()
                capture_identity = (
                    row.get("capture_manifest_sha256", "") or path.as_posix()
                )
                key = (
                    capture_identity,
                    row.get("benchmark_id", ""),
                    row.get("config", ""),
                    row.get("trial", ""),
                )
                if key in seen:
                    raise ValueError(f"duplicate replay row {key} in {path}")
                seen.add(key)
                rows.append(row)
    if "source_matrix" not in fieldnames:
        fieldnames.append("source_matrix")
    return rows, fieldnames


def _numbers(rows: list[dict], field: str) -> list[float]:
    values = []
    for row in rows:
        raw = row.get(field, "")
        if raw not in ("", None):
            values.append(float(raw))
    return values


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize(rows: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["benchmark_id"], row["config"])].append(row)

    summaries = []
    for (benchmark_id, config), group in sorted(groups.items()):
        verdicts = Counter(row["verdict"] for row in group)
        record = {
            "benchmark_id": benchmark_id,
            "circuit": group[0].get("circuit", ""),
            "config": config,
            "runs": len(group),
            "verdict_counts": dict(sorted(verdicts.items())),
            "unsat_rate": verdicts.get("unsat", 0) / len(group),
            "capture_count": len({
                value
                for row in group
                if (value := row.get("capture_manifest_sha256", ""))
            }),
            "candidate_hash_count": len({
                value
                for row in group
                if (value := row.get("candidate_sha256", ""))
            }),
            "unsupported_candidate_total": sum(
                int(row.get("unsupported_candidate_count", 0) or 0)
                for row in group
            ),
        }
        for field in TIMING_FIELDS:
            values = _numbers(group, field)
            record[field] = {
                "min": min(values) if values else None,
                "median": statistics.median(values) if values else None,
                "p95_nearest_rank": _nearest_rank(values, 0.95),
                "max": max(values) if values else None,
            }
        tokens = _numbers(group, "llm_total_tokens")
        record["llm_total_tokens"] = {
            "min": min(tokens) if tokens else None,
            "median": statistics.median(tokens) if tokens else None,
            "max": max(tokens) if tokens else None,
        }
        summaries.append(record)

    return {
        "schema": "pono-llm-reliability-summary-v1",
        "row_count": len(rows),
        "groups": summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrices", nargs="+")
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args()

    rows, fieldnames = read_rows([Path(value) for value in args.matrices])
    with open(args.out_csv, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    Path(args.out_json).write_text(
        json.dumps(summarize(rows), indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
