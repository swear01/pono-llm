#!/usr/bin/env python3
"""Select new Gate 2 models that survive the deterministic portfolio."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from experiment_manifest import validate_capture_archive, validate_replay_matrix


PRIOR_CONFIGS = (
    "baseline",
    "llm-linear",
    "llm-two-tier",
    "portfolio",
    "static-linear",
    "static-oracle",
)
DETERMINISTIC_CONFIGS = ("static-quadratic-oracle",)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def build_target_manifest(
    survivor_manifest: dict,
    survivor_manifest_sha256: str,
    prior_rows: list[dict],
    prior_hashes: dict[str, str],
    prior_manifest_sha256: str,
    deterministic_rows: list[dict],
) -> dict:
    survivor_rows = survivor_manifest.get("benchmarks", [])
    survivor_by_id = {
        row["benchmark_id"]: row for row in survivor_rows
    }
    survivor_ids = set(survivor_by_id)
    if len(survivor_ids) != len(survivor_rows):
        raise ValueError("survivor manifest contains duplicate benchmark IDs")
    for benchmark_id, row in survivor_by_id.items():
        if not row.get("content_sha256"):
            raise ValueError(f"survivor is missing content hash: {benchmark_id}")

    validate_replay_matrix(
        prior_rows,
        prior_hashes,
        PRIOR_CONFIGS,
        1,
        benchmark_manifest_sha256=prior_manifest_sha256,
    )
    deterministic_contract = validate_replay_matrix(
        deterministic_rows,
        {
            benchmark_id: row["content_sha256"]
            for benchmark_id, row in survivor_by_id.items()
        },
        DETERMINISTIC_CONFIGS,
        1,
        benchmark_manifest_sha256=survivor_manifest_sha256,
    )

    prior_ids = {row["benchmark_id"] for row in prior_rows}
    for row in prior_rows:
        benchmark_id = row["benchmark_id"]
        if benchmark_id not in survivor_by_id:
            continue
        digest = row.get("benchmark_content_sha256", "")
        if not digest:
            raise ValueError(f"prior matrix is missing content hash: {benchmark_id}")
        if digest != survivor_by_id[benchmark_id]["content_sha256"]:
            raise ValueError(f"prior/survivor content hash mismatch: {benchmark_id}")
    deterministic_by_id: dict[str, set[str]] = {}
    deterministic_hashes: dict[str, set[str]] = {}
    for row in deterministic_rows:
        benchmark_id = row["benchmark_id"]
        deterministic_by_id.setdefault(benchmark_id, set()).add(row["verdict"])
        digest = row.get("benchmark_content_sha256", "")
        if not digest:
            raise ValueError(
                f"deterministic matrix is missing content hash: {benchmark_id}"
            )
        deterministic_hashes.setdefault(benchmark_id, set()).add(digest)
    for benchmark_id, verdicts in deterministic_by_id.items():
        if {"sat", "unsat"} <= verdicts:
            raise ValueError(
                f"deterministic trials disagree on {benchmark_id}"
            )

    missing = sorted(survivor_ids - deterministic_by_id.keys())
    if missing:
        raise ValueError(
            "deterministic matrix is missing survivor IDs: " + ", ".join(missing)
        )
    for benchmark_id in survivor_ids:
        hashes = deterministic_hashes[benchmark_id]
        expected = survivor_by_id[benchmark_id]["content_sha256"]
        if hashes != {expected}:
            raise ValueError(
                f"deterministic/survivor content hash mismatch: {benchmark_id}"
            )
    deterministic_decisive = {
        benchmark_id
        for benchmark_id, verdicts in deterministic_by_id.items()
        if verdicts & {"sat", "unsat"}
    }
    targets = sorted(survivor_ids - prior_ids - deterministic_decisive)
    return {
        "schema": "pono-llm-gate2-llm-targets-v1",
        "deterministic_matrix_contract_sha256": deterministic_contract[
            "matrix_contract_sha256"
        ],
        "source_survivor_count": len(survivor_ids),
        "prior_corpus_overlap_count": len(survivor_ids & prior_ids),
        "deterministic_decisive_count": len(
            survivor_ids & deterministic_decisive
        ),
        "selected_count": len(targets),
        "benchmarks": [
            {
                "benchmark_id": benchmark_id,
                "content_sha256": survivor_by_id[benchmark_id]["content_sha256"],
            }
            for benchmark_id in targets
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("survivors")
    parser.add_argument("--prior-matrix", required=True)
    parser.add_argument("--prior-capture", required=True)
    parser.add_argument("--deterministic-matrix", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    survivor_path = Path(args.survivors)
    prior_path = Path(args.prior_matrix)
    prior_capture_path = Path(args.prior_capture)
    deterministic_path = Path(args.deterministic_matrix)
    prior_capture = validate_capture_archive(prior_capture_path)
    prior_hashes = {
        benchmark_id: record["content_sha256"]
        for benchmark_id, record in prior_capture["records"].items()
    }
    manifest = build_target_manifest(
        json.loads(survivor_path.read_text()),
        file_sha256(survivor_path),
        matrix_rows(prior_path),
        prior_hashes,
        prior_capture["manifest_sha256"],
        matrix_rows(deterministic_path),
    )
    manifest.update({
        "source_survivors": survivor_path.name,
        "source_survivors_sha256": file_sha256(survivor_path),
        "prior_matrix": prior_path.name,
        "prior_matrix_sha256": file_sha256(prior_path),
        "prior_capture": prior_capture_path.name,
        "prior_capture_manifest_sha256": prior_capture["manifest_sha256"],
        "prior_capture_integrity_sha256": prior_capture["integrity_sha256"],
        "deterministic_matrix": deterministic_path.name,
        "deterministic_matrix_sha256": file_sha256(deterministic_path),
    })
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite LLM target manifest: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        key: manifest[key]
        for key in (
            "source_survivor_count",
            "prior_corpus_overlap_count",
            "deterministic_decisive_count",
            "selected_count",
        )
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
