#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(directory: Path, inputs_path: Path) -> dict[str, object]:
    inputs = json.loads(inputs_path.read_text())
    raw = json.loads((directory / "raw_results.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    integrity = json.loads((directory / "integrity.json").read_text())
    expected_pairs = {(program["id"], candidate["id"]) for program in inputs["programs"] for candidate in inputs["candidates"]}
    actual_pairs = {(row["program_id"], row["candidate_id"]) for row in raw}
    if actual_pairs != expected_pairs or len(raw) != len(expected_pairs):
        raise ValueError("frozen row matrix mismatch")
    candidate_map = {candidate["id"]: candidate for candidate in inputs["candidates"]}
    program_map = {program["id"]: program for program in inputs["programs"]}
    violations = []
    mechanism_programs: dict[str, set[str]] = defaultdict(set)
    for row in raw:
        candidate = candidate_map[row["candidate_id"]]
        if row["original"]["verdict"] != program_map[row["program_id"]]["expected_original_verdict"]:
            raise ValueError("original control verdict mismatch")
        if row["legacy_accept"] != (candidate["legacy_filter_expected"] == "accept"):
            raise ValueError("legacy filter expectation mismatch")
        if row["strict_purity_accept"] != (candidate["strict_purity_expected"] == "accept"):
            raise ValueError("strict purity expectation mismatch")
        if row["legacy_accept"]:
            assume = row["assume"]["verdict"]
            assertion = row["assert"]["verdict"]
            recomputed = "FALSE" if assume == "FALSE" else (
                "TRUE" if assume == "TRUE" and assertion == "TRUE" else (
                    "UNKNOWN" if assertion == "FALSE" else (
                        "TIMEOUT" if "TIMEOUT" in (assume, assertion) else "UNKNOWN"
                    )
                )
            )
            if row["aggregate"] != recomputed:
                raise ValueError("aggregate mismatch")
        elif row["aggregate"] != "REJECTED" or row["assume"] is not None or row["assert"] is not None:
            raise ValueError("rejected candidate executed")
        false_safe = row["original"]["verdict"] == "FALSE" and row["aggregate"] == "TRUE"
        if row["false_safe"] != false_safe:
            raise ValueError("false-safe flag mismatch")
        if false_safe and candidate["class"] == "side_effect_attack":
            violations.append(row)
            mechanism_programs[candidate["mechanism"]].add(row["program_id"])
        if row["llm_calls"] != 0 or row["fallback"]:
            raise ValueError("LLM call or fallback recorded")
    recomputed_summary = {
        "violation_count": len(violations),
        "violation_confirmed": bool(violations),
        "systematic_reproduction": sum(len(programs) >= 2 for programs in mechanism_programs.values()) >= 2,
        "mitigation_control_pass": all(
            (row["strict_purity_accept"] == (candidate_map[row["candidate_id"]]["class"] == "pure_control"))
            and not (row["strict_purity_accept"] and row["false_safe"]) for row in raw
        ),
    }
    for key, value in recomputed_summary.items():
        if summary.get(key) != value:
            raise ValueError(f"summary mismatch: {key}")
    expected_files = {str(path.relative_to(directory)) for path in directory.rglob("*")
                      if path.is_file() and path.name != "integrity.json"}
    if set(integrity["files"]) != expected_files:
        raise ValueError("integrity file set mismatch")
    for name, digest in integrity["files"].items():
        if sha256(directory / name) != digest:
            raise ValueError(f"integrity mismatch: {name}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "artifacts/quokka_soundness_v1")
    parser.add_argument("--inputs", type=Path, default=ROOT / "scripts/quokka_soundness_inputs_v1.json")
    args = parser.parse_args()
    summary = validate(args.directory, args.inputs)
    print(f"valid {args.directory}: violations={summary['violation_count']}, systematic={summary['systematic_reproduction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
