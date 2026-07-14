#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transform(source: bytes, line_after: int, condition: str, arm: str) -> bytes:
    lines = source.decode().splitlines(keepends=True)
    if arm == "original":
        return source
    removed: list[int] = []
    if arm == "assert":
        for index, line in enumerate(lines):
            stripped = line.strip()
            if (("__VERIFIER_assert(" in stripped and stripped.endswith(");")) or
                    (stripped.startswith("assert(") and stripped.endswith(");"))):
                removed.append(index)
        for index in reversed(removed):
            lines.pop(index)
    adjusted = line_after - sum(index < line_after for index in removed)
    if adjusted < 0 or adjusted > len(lines):
        raise ValueError("insertion line outside transformed source")
    reference = lines[adjusted - 1] if adjusted else ""
    indent = reference[:len(reference) - len(reference.lstrip(" \t"))]
    function = "__VERIFIER_assert" if arm == "assert" else "__VERIFIER_assume"
    lines.insert(adjusted, f"{indent}{function}({condition});\n")
    return "".join(lines).encode()


def parse_metrics(text: str) -> dict[str, float | int | None]:
    def number(label: str) -> float | None:
        match = re.search(rf"^\s*{re.escape(label)}:\s*([0-9.]+)$", text, re.MULTILINE)
        return float(match.group(1)) if match else None
    rss = number("Maximum resident set size (kbytes)")
    return {
        "user_cpu_sec": number("User time (seconds)"),
        "system_cpu_sec": number("System time (seconds)"),
        "peak_memory_kib": int(rss) if rss is not None else None,
    }


def verdict(stdout: bytes, returncode: int) -> str:
    if returncode == 124:
        return "TIMEOUT"
    for line in reversed(stdout.decode(errors="replace").splitlines()):
        if line.strip() in {"TRUE", "FALSE", "UNKNOWN"}:
            return line.strip()
    return "ERROR"


def run_arm(upstream: Path, java_bin: Path, source_path: Path, result_dir: Path,
            arm: str, timeout_sec: int) -> dict[str, object]:
    tool = upstream / "tools/uautomizer"
    stdout_path = result_dir / f"{arm}.stdout"
    stderr_path = result_dir / f"{arm}.stderr"
    metrics_path = result_dir / f"{arm}.time"
    command = [
        "/usr/bin/time", "-v", "-o", str(metrics_path),
        "taskset", "-c", "0", "timeout", "--signal=TERM", "--kill-after=5s", f"{timeout_sec}s",
        "python3", "-u", "Ultimate.py", "--spec", str(upstream / "Dataset/properties/unreach-call.prp"),
        "--file", str(source_path), "--architecture", "64bit", "--full-output",
    ]
    environment = dict(os.environ)
    environment["PATH"] = f"{tool}:{java_bin.parent}:{environment['PATH']}"
    started = time.monotonic()
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = subprocess.run(command, cwd=tool, env=environment, stdout=stdout_file, stderr=stderr_file)
    wall = time.monotonic() - started
    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    metrics = parse_metrics(metrics_path.read_text(errors="replace"))
    return {
        "arm": arm,
        "command": command,
        "exit_code": process.returncode,
        "verdict": verdict(stdout, process.returncode),
        "wall_time_sec": wall,
        **metrics,
        "stdout_sha256": sha256_bytes(stdout),
        "stderr_sha256": sha256_bytes(stderr),
        "source_sha256": sha256_bytes(source_path.read_bytes()),
    }


def classify(arms: dict[str, dict[str, object]]) -> str:
    q0, q1, q2 = (arms[name]["verdict"] for name in ("original", "assert", "assume"))
    if q0 == "FALSE" or q2 == "FALSE" or "ERROR" in (q0, q1, q2):
        return "INFRASTRUCTURE_FAILURE"
    if q1 != "TRUE":
        return "G2_INVALID_INVARIANT"
    if q2 != "TRUE":
        return "G3_CONSUMER_NO_CAPACITY"
    oracle_cost = max(float(arms["assert"]["wall_time_sec"]), float(arms["assume"]["wall_time_sec"]))
    if q0 != "TRUE" or oracle_cost < float(arms["original"]["wall_time_sec"]):
        return "PASS"
    return "G5_NEGATIVE_RUNTIME_UTILITY"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--java-bin", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts/external_quokka_oracle_r1/upstream_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/external_quokka_oracle_r1/smoke")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    selected = set(manifest["smoke_task_ids"])
    entries = sorted((row for row in manifest["entries"] if row["task_id"] in selected),
                     key=lambda row: (row["program_sha256"], row["task_id"]))
    args.output.mkdir(parents=True, exist_ok=True)
    all_results = []
    for trial in range(args.trials):
        for position, entry in enumerate(entries):
            result_dir = args.output / f"trial-{trial + 1}" / f"{position:02d}-{entry['task_id'][:12]}"
            result_dir.mkdir(parents=True, exist_ok=True)
            original = (args.upstream / "Dataset/evaluation_all" / entry["filename"]).read_bytes()
            sources = {}
            for arm in ("original", "assert", "assume"):
                data = transform(original, entry["insertion_line"], entry["invariant"], arm)
                path = result_dir / f"{arm}.c"
                path.write_bytes(data)
                sources[arm] = path
            arms = {arm: run_arm(args.upstream, args.java_bin, sources[arm], result_dir, arm, args.timeout)
                    for arm in ("original", "assert", "assume")}
            result = {"schema": "external-quokka-oracle-r1-task-v1", "trial": trial + 1,
                      "position": position, "entry": entry, "arms": arms, "classification": classify(arms),
                      "oracle_parallel_wall_sec": max(arms["assert"]["wall_time_sec"], arms["assume"]["wall_time_sec"]),
                      "oracle_total_work_wall_sec": arms["assert"]["wall_time_sec"] + arms["assume"]["wall_time_sec"],
                      "silent_fallback": False, "llm_calls": 0}
            (result_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            all_results.append(result)
            print(f"trial={trial + 1} task={position + 1}/25 {entry['filename']} {result['classification']}", flush=True)
    (args.output / "raw_results.json").write_text(json.dumps(all_results, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
