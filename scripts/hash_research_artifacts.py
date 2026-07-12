#!/usr/bin/env python3
"""Regenerate canonical Phase 1+2 and Gate 2 artifact hash manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

PHASE_FILES = (
    "README.md",
    "phase1_2_corrected_full21_matrix_final.csv",
    "phase1_2_corrected_static_full21_v3.csv",
    "phase1_2_corrected_static_full21_v3.log",
    "phase1_2_llm_houdini_full21.csv",
    "phase1_2_llm_houdini_full21.log",
    "phase1_2_nonlinear_manifest.txt",
    "phase1_2_nonlinear_reliability.csv",
    "phase1_2_nonlinear_reliability.json",
    "phase1_2_static_quadratic_nonlinear.csv",
    "phase1_2_static_quadratic_nonlinear.log",
    "phase1_2_summary_v1.json",
)

GATE2_FILES = (
    "README.md",
    "gate2_features.csv",
    "gate2_features.summary.json",
    "gate2_manifest.json",
    "gate2_baseline_screen_10s.csv",
    "gate2_baseline_screen_survivors.json",
    "gate2_baseline_screen_survivors_le10k.json",
    "gate2_baseline_screen_survivors_le100k.json",
    "gate2_static_quadratic_le10k_70s.csv",
    "gate2_llm_targets.json",
    "gate2_llm_houdini_70s.csv",
    "gate2_llm_linear_refine_70s.csv",
    "gate2_llm_linear_cap0_70s.csv",
    "gate2_static_linear_cap200_refine_70s.csv",
    "gate2_static_ranked_cap20_refine_70s.csv",
    "gate2_static_ranked_cap20_refine_70s.log",
    "gate2_up_matched_matrix.csv",
    "gate2_up_manifest.json",
    "gate2_up_llm_vs_ranked_5trials.csv",
    "gate2_up_llm_vs_ranked_5trials.log",
    "gate2_up_show_invar.log",
    "gate2_up_invar.txt",
    "gate2_up_cert_check.txt",
    "gate2_up_static_cap200.jsonl",
    "gate2_up_static_cap200_show_invar.log",
    "gate2_up_static_cap200_invar.txt",
    "gate2_up_static_cap200_cert_check.txt",
    "gate2_up_static_ranked_cap15.csv",
    "gate2_up_static_ranked_cap15.log",
    "gate2_up_static_ranked_cap16.csv",
    "gate2_up_static_ranked_cap16.log",
    "gate2_up_static_ranked_cap16.jsonl",
    "gate2_up_static_ranked_cap16_show_invar.log",
    "gate2_up_static_ranked_cap16_invar.txt",
    "gate2_up_static_ranked_cap16_cert_check.txt",
    "gate2_up_static_linear_cap192_v2.csv",
    "gate2_summary_v1.json",
)


def tree_files(relative: str) -> list[str]:
    directory = ARTIFACTS / relative
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return [
        path.relative_to(ARTIFACTS).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    ]


def file_record(relative: str) -> dict:
    path = ARTIFACTS / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    data = path.read_bytes()
    return {
        "path": f"artifacts/{relative}",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write_manifest(output: str, schema: str, relative_files: list[str]) -> None:
    duplicates = [
        path for path in set(relative_files) if relative_files.count(path) > 1
    ]
    if duplicates:
        raise ValueError(f"duplicate artifact paths: {sorted(duplicates)}")
    payload = {
        "schema": schema,
        "canonical_date": "2026-07-12",
        "files": [file_record(path) for path in sorted(relative_files)],
    }
    destination = ARTIFACTS / output
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(destination)


def main() -> int:
    phase_files = list(PHASE_FILES)
    phase_files += tree_files("phase1_2_frozen_v2")
    for index in range(1, 6):
        prefix = f"phase1_2_nonlinear_capture_{index:02d}"
        phase_files += tree_files(prefix)
        phase_files += [f"{prefix}_matrix.csv", f"{prefix}_matrix.log"]
    write_manifest(
        "phase1_2_artifact_hashes.json",
        "pono-llm-phase1-2-artifact-hashes-v1",
        phase_files,
    )

    gate2_files = list(GATE2_FILES) + tree_files("gate2_llm_capture_v3")
    write_manifest(
        "gate2_artifact_hashes.json",
        "pono-llm-gate2-artifact-hashes-v1",
        gate2_files,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
