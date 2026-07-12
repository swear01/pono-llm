#!/usr/bin/env python3
"""Build a portable manifest of benchmarks not decided by a baseline matrix."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from experiment_manifest import validate_replay_matrix


def build_survivor_manifest(
    rows: list[dict],
    matrix: Path,
    benchmark_hashes: dict[str, str],
    benchmark_manifest_sha256: str,
    feature_rows: list[dict] | None = None,
    max_nodes: int | None = None,
) -> dict:
    contract = validate_replay_matrix(
        rows,
        benchmark_hashes,
        ["baseline"],
        1,
        benchmark_manifest_sha256=benchmark_manifest_sha256,
    )

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["benchmark_id"]].append(row)

    survivors = []
    verdict_counts = Counter()
    for benchmark_id, group in sorted(grouped.items()):
        verdicts = {row["verdict"] for row in group}
        verdict_counts.update(row["verdict"] for row in group)
        decisive = verdicts & {"sat", "unsat"}
        if decisive == {"sat", "unsat"}:
            raise ValueError(f"baseline trials disagree on {benchmark_id}")
        row_hashes = {
            row.get("benchmark_content_sha256", "") for row in group
            if row.get("benchmark_content_sha256", "")
        }
        if len(row_hashes) > 1:
            raise ValueError(f"baseline trials use different content for {benchmark_id}")
        matrix_hash = next(iter(row_hashes), "")
        manifest_hash = benchmark_hashes.get(benchmark_id, "")
        if matrix_hash and manifest_hash and matrix_hash != manifest_hash:
            raise ValueError(f"matrix/manifest content hash mismatch for {benchmark_id}")
        content_sha256 = matrix_hash or manifest_hash
        if not content_sha256:
            raise ValueError(f"missing benchmark content hash for {benchmark_id}")
        if not decisive:
            survivors.append({
                "benchmark_id": benchmark_id,
                "content_sha256": content_sha256,
                "screen_verdicts": sorted(verdicts),
            })

    excluded_by_size = []
    if feature_rows is not None:
        if max_nodes is None:
            raise ValueError("max_nodes is required when feature_rows are provided")
        features = {}
        for row in feature_rows:
            benchmark_id = row["benchmark_id"]
            if benchmark_id in features:
                raise ValueError(f"duplicate feature row for {benchmark_id}")
            features[benchmark_id] = row
        for benchmark_id, digest in benchmark_hashes.items():
            feature = features.get(benchmark_id)
            if feature is None:
                raise ValueError(f"missing feature row for {benchmark_id}")
            if feature.get("content_sha256") != digest:
                raise ValueError(
                    f"feature/model content hash mismatch for {benchmark_id}"
                )
        retained = []
        for survivor in survivors:
            feature = features.get(survivor["benchmark_id"])
            if feature is None:
                raise ValueError(
                    f"missing feature row for {survivor['benchmark_id']}"
                )
            node_count = int(feature["node_count"])
            if node_count > max_nodes:
                excluded_by_size.append({
                    "benchmark_id": survivor["benchmark_id"],
                    "node_count": node_count,
                })
            else:
                retained.append(survivor)
        survivors = retained

    return {
        "schema": "pono-llm-gate2-survivors-v1",
        "source_matrix": matrix.name,
        "source_matrix_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
        "source_matrix_contract_sha256": contract["matrix_contract_sha256"],
        "benchmark_manifest_sha256": benchmark_manifest_sha256,
        "source_benchmark_count": len(grouped),
        "source_row_count": len(rows),
        "source_verdict_counts": dict(sorted(verdict_counts.items())),
        "max_nodes": max_nodes if max_nodes is not None else "",
        "excluded_by_size_count": len(excluded_by_size),
        "excluded_by_size": excluded_by_size,
        "selected_count": len(survivors),
        "benchmarks": survivors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix")
    parser.add_argument("--out", required=True)
    parser.add_argument("--features")
    parser.add_argument("--max-nodes", type=int)
    parser.add_argument("--benchmark-manifest", required=True)
    args = parser.parse_args()
    if (args.features is None) != (args.max_nodes is None):
        parser.error("--features and --max-nodes must be supplied together")
    if args.max_nodes is not None and args.max_nodes <= 0:
        parser.error("--max-nodes must be positive")

    matrix = Path(args.matrix)
    with matrix.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    feature_rows = None
    if args.features:
        with Path(args.features).open(newline="") as handle:
            feature_rows = list(csv.DictReader(handle))
    benchmark_manifest_path = Path(args.benchmark_manifest)
    benchmark_manifest = json.loads(benchmark_manifest_path.read_text())
    benchmark_rows = benchmark_manifest.get("benchmarks", [])
    benchmark_hashes = {
        row["benchmark_id"]: row["content_sha256"]
        for row in benchmark_rows
    }
    if len(benchmark_hashes) != len(benchmark_rows):
        raise ValueError("benchmark manifest contains duplicate benchmark IDs")
    benchmark_manifest_sha256 = hashlib.sha256(
        benchmark_manifest_path.read_bytes()
    ).hexdigest()
    manifest = build_survivor_manifest(
        rows,
        matrix,
        benchmark_hashes,
        benchmark_manifest_sha256,
        feature_rows,
        args.max_nodes,
    )
    if args.features:
        feature_path = Path(args.features)
        manifest["feature_file"] = feature_path.name
        manifest["feature_sha256"] = hashlib.sha256(
            feature_path.read_bytes()
        ).hexdigest()
    manifest["benchmark_manifest"] = benchmark_manifest_path.name
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite survivor manifest: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "source_benchmark_count": manifest["source_benchmark_count"],
        "source_verdict_counts": manifest["source_verdict_counts"],
        "selected_count": manifest["selected_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
