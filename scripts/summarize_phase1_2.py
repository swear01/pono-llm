#!/usr/bin/env python3
"""Build the canonical Phase 1+2 machine-readable research summary."""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter
from pathlib import Path

from experiment_manifest import (
    validate_capture_archive,
    validate_replay_matrix,
)


CANONICAL_DATE = "2026-07-11"
SOURCE_FILES = (
    "phase1_2_corrected_full21_matrix_final.csv",
    "phase1_2_corrected_static_full21_v3.csv",
    "phase1_2_llm_houdini_full21.csv",
    "phase1_2_nonlinear_reliability.json",
    "phase1_2_frozen_v2/manifest.json",
    "phase1_2_frozen_v2/integrity.json",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def summarize_config(rows: list[dict]) -> dict:
    return {
        "verdict_counts": dict(
            sorted(Counter(row["verdict"] for row in rows).items())
        ),
        "sat_benchmark_ids": sorted(
            row["benchmark_id"] for row in rows if row["verdict"] == "sat"
        ),
        "unsat_benchmark_ids": sorted(
            row["benchmark_id"] for row in rows if row["verdict"] == "unsat"
        ),
    }


def indexed_configs(rows: list[dict], expected_ids: set[str]) -> dict[str, list[dict]]:
    identities = {
        (row["benchmark_id"], row["config"], row["trial"]) for row in rows
    }
    if len(identities) != len(rows):
        raise ValueError("matrix contains duplicate replay identities")
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["config"], []).append(row)
    for config, config_rows in grouped.items():
        ids = {row["benchmark_id"] for row in config_rows}
        if ids != expected_ids:
            raise ValueError(
                f"{config} benchmark IDs differ from the canonical corpus"
            )
    return grouped


def benchmark_hashes(rows: list[dict]) -> dict[str, str]:
    hashes: dict[str, set[str]] = {}
    for row in rows:
        digest = row.get("benchmark_content_sha256", "")
        if not _SHA256.fullmatch(digest):
            raise ValueError(
                f"missing/invalid benchmark hash for {row.get('benchmark_id', '?')}"
            )
        hashes.setdefault(row["benchmark_id"], set()).add(digest)
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError("matrix rows disagree on benchmark content hashes")
    return {benchmark_id: next(iter(values)) for benchmark_id, values in hashes.items()}


def build_summary(artifact_dir: Path) -> dict:
    replay = read_csv(
        artifact_dir / "phase1_2_corrected_full21_matrix_final.csv"
    )
    static = read_csv(
        artifact_dir / "phase1_2_corrected_static_full21_v3.csv"
    )
    houdini = read_csv(artifact_dir / "phase1_2_llm_houdini_full21.csv")
    reliability = json.loads(
        (artifact_dir / "phase1_2_nonlinear_reliability.json").read_text()
    )
    capture = validate_capture_archive(artifact_dir / "phase1_2_frozen_v2")

    replay_hashes = {
        benchmark_id: record["content_sha256"]
        for benchmark_id, record in capture["records"].items()
    }
    corpus_ids = set(replay_hashes)
    validate_replay_matrix(
        replay,
        replay_hashes,
        [
            "baseline",
            "llm-linear",
            "llm-two-tier",
            "portfolio",
            "static-linear",
            "static-oracle",
        ],
        1,
        benchmark_manifest_sha256=capture["manifest_sha256"],
    )
    validate_replay_matrix(
        static,
        replay_hashes,
        ["static-linear", "static-oracle", "static-quadratic-oracle"],
        1,
        benchmark_manifest_sha256=capture["manifest_sha256"],
    )
    validate_replay_matrix(
        houdini,
        replay_hashes,
        ["llm-houdini-cert"],
        1,
        benchmark_manifest_sha256=capture["manifest_sha256"],
    )
    capture_rows = [
        row
        for row in replay + houdini
        if row.get("candidate_capture", "")
    ]
    for row in capture_rows:
        if row.get("capture_manifest_sha256", "") != capture["manifest_sha256"]:
            raise ValueError("matrix/capture manifest hashes differ")
        if row.get("capture_integrity_sha256", "") != capture["integrity_sha256"]:
            raise ValueError("matrix/capture integrity hashes differ")
    replay_configs = indexed_configs(replay, corpus_ids)
    static_configs = indexed_configs(static, corpus_ids)
    houdini_configs = indexed_configs(houdini, corpus_ids)

    selected = {
        name: replay_configs[name]
        for name in ("baseline", "llm-linear", "llm-two-tier", "portfolio")
    }
    selected.update({
        name: static_configs[name]
        for name in (
            "static-linear",
            "static-oracle",
            "static-quadratic-oracle",
        )
    })
    selected["llm-houdini-cert"] = houdini_configs["llm-houdini-cert"]
    configs = {name: summarize_config(rows) for name, rows in selected.items()}

    baseline = configs["baseline"]
    static_quadratic = configs["static-quadratic-oracle"]
    llm_portfolio = configs["portfolio"]
    deterministic_unsat = sorted(
        set(baseline["unsat_benchmark_ids"])
        | set(static_quadratic["unsat_benchmark_ids"])
    )
    deterministic_sat = baseline["sat_benchmark_ids"]
    matched = (
        deterministic_unsat == llm_portfolio["unsat_benchmark_ids"]
        and deterministic_sat == llm_portfolio["sat_benchmark_ids"]
    )
    if not matched:
        raise ValueError("deterministic and LLM portfolios do not match")

    houdini_rows = selected["llm-houdini-cert"]
    quadratic_rows = selected["static-quadratic-oracle"]
    return {
        "schema": "pono-llm-phase1-2-summary-v1",
        "date": CANONICAL_DATE,
        "claim_boundary": (
            "No current full21 solve is LLM-specific relative to the tested "
            "engine + deterministic affine/quadratic portfolio."
        ),
        "corpus_size": len(corpus_ids),
        "configs": configs,
        "deterministic_portfolio": {
            "sat_benchmark_ids": deterministic_sat,
            "unsat_benchmark_ids": deterministic_unsat,
        },
        "matched_set_equal": matched,
        "llm_specific_unsat_benchmark_ids": sorted(
            set(llm_portfolio["unsat_benchmark_ids"])
            - set(deterministic_unsat)
        ),
        "timing": {
            "llm_houdini_cert": {
                "median_certificate_sec": statistics.median(
                    float(row["certificate_time_sec"]) for row in houdini_rows
                ),
                "median_generation_sec": statistics.median(
                    float(row["candidate_generation_sec"])
                    for row in houdini_rows
                ),
                "total_certificate_sec": sum(
                    float(row["certificate_time_sec"]) for row in houdini_rows
                ),
                "total_generation_sec": sum(
                    float(row["candidate_generation_sec"])
                    for row in houdini_rows
                ),
                "total_end_to_end_sec": sum(
                    float(row["end_to_end_sec"]) for row in houdini_rows
                ),
                "total_tokens": sum(
                    int(row["llm_total_tokens"]) for row in houdini_rows
                ),
            },
            "static_quadratic_oracle": {
                "median_end_to_end_sec": statistics.median(
                    float(row["end_to_end_sec"]) for row in quadratic_rows
                ),
                "total_end_to_end_sec": sum(
                    float(row["end_to_end_sec"]) for row in quadratic_rows
                ),
            },
        },
        "nonlinear_reliability": reliability,
        "source_files": [f"artifacts/{path}" for path in SOURCE_FILES],
    }


def main() -> int:
    print(json.dumps(build_summary(Path("artifacts")), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
