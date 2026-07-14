#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(directory: Path) -> dict[str, object]:
    manifest = json.loads((directory / "upstream_manifest.json").read_text())
    summary = json.loads((directory / "smoke_summary.json").read_text())
    integrity = json.loads((directory / "recursive_integrity.json").read_text())
    if manifest.get("upstream_commit") != "60301cb79ba594945f2049990421f5d5d4d95afc":
        raise ValueError("upstream commit mismatch")
    if len(manifest.get("smoke_task_ids", [])) != 25 or len(set(manifest["smoke_task_ids"])) != 25:
        raise ValueError("smoke selection mismatch")
    raw = directory / "smoke/raw_results.json"
    if summary.get("raw_results_file_sha256") != sha256(raw):
        raise ValueError("raw result hash mismatch")
    if summary.get("decision") != "STOP" or summary.get("full_population_authorized") is not False:
        raise ValueError("unexpected smoke decision")
    expected_files = {str(path.relative_to(directory)) for path in directory.rglob("*")
                      if path.is_file() and path.name != "recursive_integrity.json"}
    if set(integrity.get("files", {})) != expected_files:
        raise ValueError("recursive integrity file set mismatch")
    for name, expected in integrity["files"].items():
        if sha256(directory / name) != expected:
            raise ValueError(f"recursive integrity mismatch: {name}")
    raw_rows = json.loads(raw.read_text())
    if len(raw_rows) != 50 or sum(len(row["arms"]) for row in raw_rows) != 150:
        raise ValueError("raw invocation count mismatch")
    if any(row.get("silent_fallback") or row.get("llm_calls") for row in raw_rows):
        raise ValueError("fallback or LLM call recorded")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path,
                        default=ROOT / "artifacts/external_quokka_oracle_r1")
    args = parser.parse_args()
    summary = validate(args.directory)
    print(f"valid {args.directory}: {summary['decision']}, {summary['invocation_count']} invocations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
