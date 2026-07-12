#!/usr/bin/env python3
"""Select a portable, deduplicated, stratified Gate 2 benchmark manifest."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

SELECTION_SEED = "pono-llm-gate2-v1"


def is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def row_stratum(row: dict) -> tuple[str, str, str, str]:
    return (
        row.get("producer", "unknown"),
        row.get("suite", "unknown"),
        row.get("arithmetic_class", "unknown"),
        row.get("size_bucket", "unknown"),
    )


def stable_rank(benchmark_id: str) -> str:
    return hashlib.sha256(f"{SELECTION_SEED}:{benchmark_id}".encode()).hexdigest()


def eligible_rows(rows: list[dict]) -> list[dict]:
    return [
        row
        for row in rows
        if row.get("parse_status") == "ok"
        and is_true(row.get("software_origin", ""))
        and not is_true(row.get("has_array", ""))
    ]


def deduplicate_content(rows: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        digest = row.get("content_sha256", "")
        if not digest:
            raise ValueError(f"missing content hash for {row.get('benchmark_id', '?')}")
        by_hash[digest].append(row)
    unique = []
    duplicates = {}
    for digest, group in sorted(by_hash.items()):
        ordered = sorted(group, key=lambda row: row["benchmark_id"])
        unique.append(ordered[0])
        if len(ordered) > 1:
            duplicates[digest] = [row["benchmark_id"] for row in ordered]
    return unique, duplicates


def stratified_select(rows: list[dict], target: int) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[row_stratum(row)].append(row)
    for group in groups.values():
        group.sort(key=lambda row: (stable_rank(row["benchmark_id"]), row["benchmark_id"]))

    selected = []
    strata = sorted(groups)
    while strata and len(selected) < target:
        remaining = []
        for stratum in strata:
            group = groups[stratum]
            if group:
                selected.append(group.pop(0))
                if len(selected) >= target:
                    break
            if group:
                remaining.append(stratum)
        strata = remaining
    return selected


def build_manifest(rows: list[dict], feature_file: Path, target: int) -> dict:
    eligible = eligible_rows(rows)
    unique, duplicates = deduplicate_content(eligible)
    selected = stratified_select(unique, min(target, len(unique)))
    stratum_counts = Counter("/".join(row_stratum(row)) for row in selected)
    return {
        "schema": "pono-llm-gate2-manifest-v1",
        "feature_file": feature_file.name,
        "feature_sha256": hashlib.sha256(feature_file.read_bytes()).hexdigest(),
        "selection_seed": SELECTION_SEED,
        "target": target,
        "eligible_before_dedup": len(eligible),
        "duplicate_content_groups": len(duplicates),
        "duplicate_instances_removed": len(eligible) - len(unique),
        "unique_eligible": len(unique),
        "selected_count": len(selected),
        "selected_strata": dict(sorted(stratum_counts.items())),
        "duplicates": duplicates,
        "benchmarks": [
            {
                "benchmark_id": row["benchmark_id"],
                "content_sha256": row["content_sha256"],
                "producer": row["producer"],
                "suite": row["suite"],
                "arithmetic_class": row["arithmetic_class"],
                "size_bucket": row["size_bucket"],
            }
            for row in selected
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features")
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", type=int, default=500)
    args = parser.parse_args()
    if args.target <= 0:
        parser.error("--target must be positive")

    feature_file = Path(args.features)
    with feature_file.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    manifest = build_manifest(rows, feature_file, args.target)
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite manifest: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        key: manifest[key]
        for key in (
            "eligible_before_dedup",
            "duplicate_instances_removed",
            "unique_eligible",
            "selected_count",
        )
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
