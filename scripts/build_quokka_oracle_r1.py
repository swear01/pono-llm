#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "60301cb79ba594945f2049990421f5d5d4d95afc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def insertion_points(path: Path) -> list[int]:
    lines = path.read_text(errors="replace").splitlines()
    loops: list[tuple[int, int]] = []
    depth = 0
    stack: list[tuple[int, int]] = []
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        is_loop = ((stripped.startswith("while") or stripped.startswith("for")) and "(" in stripped) or (
            stripped.startswith("do") and ("{" in stripped or len(stripped) <= 3)
        )
        if is_loop:
            first_body = line_number + 1
            if not stripped.startswith("do") and "{" not in line:
                for offset in range(line_number, min(line_number + 3, len(lines))):
                    if "{" in lines[offset]:
                        first_body = offset + 2
                        break
            stack.append((first_body, depth))
        depth += line.count("{") - line.count("}")
        closed = [index for index, (_, entry_depth) in enumerate(stack) if depth <= entry_depth]
        for index in closed:
            loops.append(stack[index])
        for index in reversed(closed):
            stack.pop(index)
    return sorted({first_body - 1 for first_body, _ in loops if first_body > 1})


def valid_condition(condition: str) -> bool:
    if any(operator in condition for operator in ("++", "--", "+=", "-=", "*=", "/=", "%=")):
        return False
    for index, char in enumerate(condition):
        if char == "=":
            before = condition[index - 1] if index else ""
            after = condition[index + 1] if index + 1 < len(condition) else ""
            if before not in "<>=!" and after != "=":
                return False
    return True


def build(upstream: Path, output: Path, uautomizer_zip: Path, java_archive: Path) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip()
    if head != UPSTREAM_COMMIT:
        raise ValueError(f"upstream commit mismatch: {head}")
    timing = json.loads((upstream / "Dataset/timing_uautomizer.json").read_text())
    programs = upstream / "Dataset/evaluation_all"
    rows = []
    for record in timing:
        program = programs / record["filename"]
        if not program.is_file():
            continue
        points = set(insertion_points(program))
        for index, invariant in enumerate(record.get("invariants", [])):
            condition = invariant["invariant"]
            row = {
                "task_id": hashlib.sha256(
                    f"{record['filename']}\0{index}\0{invariant['line']}\0{condition}".encode()
                ).hexdigest(),
                "filename": record["filename"],
                "program_sha256": sha256(program),
                "invariant_index": index,
                "insertion_line": invariant["line"],
                "invariant": condition,
                "invariant_sha256": hashlib.sha256(condition.encode()).hexdigest(),
                "valid_insertion_point": invariant["line"] in points,
                "valid_condition": valid_condition(condition),
            }
            row["eligible"] = row["valid_insertion_point"] and row["valid_condition"]
            rows.append(row)
    eligible = sorted((row for row in rows if row["eligible"]), key=lambda row: (row["program_sha256"], row["task_id"]))
    manifest = {
        "schema": "external-quokka-oracle-r1-upstream-v1",
        "upstream_url": "https://github.com/Anjiang-Wei/Quokka.git",
        "upstream_commit": UPSTREAM_COMMIT,
        "timing_entry_count": len(timing),
        "ground_truth_task_count": len({row["filename"] for row in rows}),
        "ground_truth_entry_count": len(rows),
        "eligible_entry_count": len(eligible),
        "insertion_match_ratio": sum(row["valid_insertion_point"] for row in rows) / len(rows),
        "smoke_selection_rule": "first 25 eligible entries sorted by (program_sha256, task_id)",
        "smoke_task_ids": [row["task_id"] for row in eligible[:25]],
        "entries": rows,
        "uautomizer": {
            "archive_url": "https://gitlab.com/sosy-lab/sv-comp/archives-2023/raw/svcomp23/2023/uautomizer.zip",
            "archive_sha256": sha256(uautomizer_zip),
            "reported_version": "2329fc70",
        },
        "java": {"archive_sha256": sha256(java_archive), "runtime": "Temurin 11.0.31+11 JRE"},
    }
    paths = ["README.md", "build.sh", "baselines/batch_invariant_generation.py", "baselines/print_results.py",
             "baselines/prompt.yaml", "baselines/reqs.txt", "Dataset/properties/unreach-call.prp",
             "Dataset/timing_uautomizer.json", "Dataset/timing_esbmc.json"]
    paths += sorted(str(path.relative_to(upstream)) for path in programs.glob("*.c"))
    manifest["recursive_files"] = {name: sha256(upstream / name) for name in paths}
    output.mkdir(parents=True, exist_ok=True)
    (output / "upstream_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    environment = {
        "schema": "external-quokka-oracle-r1-environment-v1",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_affinity": "0",
        "memory_limit_bytes": 15 * 1024**3,
        "timeout_seconds": 600,
        "uautomizer_archive_sha256": manifest["uautomizer"]["archive_sha256"],
        "java_archive_sha256": manifest["java"]["archive_sha256"],
        "apt_install_attempt": "failed: dpkg lock permission denied; no system package was changed",
    }
    (output / "environment.json").write_text(json.dumps(environment, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/external_quokka_oracle_r1")
    parser.add_argument("--uautomizer-zip", type=Path, required=True)
    parser.add_argument("--java-archive", type=Path, required=True)
    args = parser.parse_args()
    build(args.upstream, args.output, args.uautomizer_zip, args.java_archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
