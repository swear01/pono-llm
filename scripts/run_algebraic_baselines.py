#!/usr/bin/env python3
"""Run reproducible Z3/PolySAT arms on a frozen Gate 4B C2 query corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

import z3


POLYSAT_COMMIT = "16fb86b636047fd79ad5827f768b6f26d8812948"
POLYSAT_OPTIONS = (
    "sat.smt=true",
    "tactic.default_tactic=smt",
    "smt.bv.solver=1",
)


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _solver_result(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if value in {"sat", "unsat", "unknown"}:
            return value
    return "error"


def python_worker(query_path: Path, timeout_ms: int) -> dict:
    assertions = z3.parse_smt2_file(str(query_path))
    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(*assertions)
    start = time.perf_counter()
    result = solver.check()
    elapsed = time.perf_counter() - start
    reason = solver.reason_unknown() if result == z3.unknown else ""
    return {
        "result": str(result),
        "solver_time_sec": elapsed,
        "reason_unknown": reason,
        "statistics": str(solver.statistics()),
        "z3_version": z3.get_version_string(),
    }


def _run_command(
    command: list[str], *, timeout_sec: float, environment: dict[str, str] | None = None
) -> dict:
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(prefix="algebraic-time-", delete=False) as handle:
        metrics_path = Path(handle.name)
    wrapped = [
        "/usr/bin/time",
        "-v",
        "-o",
        str(metrics_path),
        "--",
        "/usr/bin/timeout",
        "--kill-after=2s",
        f"{timeout_sec}s",
        *command,
    ]
    try:
        completed = subprocess.run(
            wrapped,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5.0,
            env=environment,
            check=False,
        )
        timed_out = False
    except subprocess.TimeoutExpired as error:
        completed = None
        timed_out = True
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
    elapsed = time.perf_counter() - started
    metrics_text = metrics_path.read_text() if metrics_path.exists() else ""
    metrics_path.unlink(missing_ok=True)
    parsed_metrics = {}
    for line in metrics_text.splitlines():
        if ": " not in line:
            continue
        key, value = line.strip().split(": ", 1)
        parsed_metrics[key] = value
    max_rss = parsed_metrics.get("Maximum resident set size (kbytes)")
    user_time = parsed_metrics.get("User time (seconds)")
    system_time = parsed_metrics.get("System time (seconds)")
    if timed_out:
        return {
            "result": "timeout",
            "returncode": None,
            "wall_time_sec": elapsed,
            "child_user_time_sec": float(user_time) if user_time else None,
            "child_system_time_sec": float(system_time) if system_time else None,
            "max_rss_kib": int(max_rss) if max_rss else None,
            "stdout": stdout,
            "stderr": stderr,
        }
    stdout = completed.stdout
    stderr = completed.stderr
    result = _solver_result(stdout)
    if completed.returncode == 124 and result == "error":
        result = "timeout"
    return {
        "result": result,
        "returncode": completed.returncode,
        "wall_time_sec": elapsed,
        "child_user_time_sec": float(user_time) if user_time else None,
        "child_system_time_sec": float(system_time) if system_time else None,
        "max_rss_kib": int(max_rss) if max_rss else None,
        "stdout": stdout,
        "stderr": stderr,
    }


def _executable_version(
    executable: Path,
    *,
    accepted_returncodes: frozenset[int] = frozenset({0}),
    environment: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
        check=False,
    )
    if completed.returncode not in accepted_returncodes or not completed.stdout.strip():
        raise ValueError(
            f"cannot query solver version for {executable}: "
            f"exit={completed.returncode}, stderr={completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def solver_arms(local_z3: Path, polysat_z3: Path) -> list[dict]:
    for executable in (local_z3, polysat_z3):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"solver executable is unavailable: {executable}")
    pinned_version = _executable_version(polysat_z3)
    resource_path = getattr(z3.z3core, "_z3_lib_resource_path", None)
    if resource_path is None:
        raise ValueError("Python Z3 does not expose its native library path")
    python_z3_library = Path(resource_path) / "libz3.so"
    if not python_z3_library.is_file():
        raise ValueError(f"Python Z3 library is unavailable: {python_z3_library}")
    return [
        {
            "id": "python-z3-default",
            "kind": "python",
            "executable": Path(sys.executable),
            "version": z3.get_version_string(),
            "z3_library": str(python_z3_library),
            "z3_library_sha256": file_sha256(python_z3_library),
            "options": [],
        },
        {
            "id": "local-z3-cli-default",
            "kind": "cli",
            "executable": local_z3,
            "version": _executable_version(local_z3),
            "options": ["-st"],
        },
        {
            "id": "local-z3-intblast",
            "kind": "cli",
            "executable": local_z3,
            "version": _executable_version(local_z3),
            "options": [
                "sat.smt=true",
                "tactic.default_tactic=smt",
                "smt.bv.solver=2",
                "-st",
            ],
        },
        {
            "id": "pinned-z3-default",
            "kind": "cli",
            "executable": polysat_z3,
            "version": pinned_version,
            "source_commit": POLYSAT_COMMIT,
            "options": ["-st"],
        },
        {
            "id": "pinned-z3-polysat",
            "kind": "cli",
            "executable": polysat_z3,
            "version": pinned_version,
            "source_commit": POLYSAT_COMMIT,
            "options": [*POLYSAT_OPTIONS, "-st"],
        },
        {
            "id": "pinned-z3-intblast",
            "kind": "cli",
            "executable": polysat_z3,
            "version": pinned_version,
            "source_commit": POLYSAT_COMMIT,
            "options": [
                "sat.smt=true",
                "tactic.default_tactic=smt",
                "smt.bv.solver=2",
                "-st",
            ],
        },
    ]


def validate_polysat_source(source: Path, executable: Path) -> dict:
    source = source.resolve()
    executable = executable.resolve()
    if not (source / ".git").exists():
        raise ValueError(f"PolySAT source is not a Git checkout: {source}")
    revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if revision.returncode != 0 or revision.stdout.strip() != POLYSAT_COMMIT:
        raise ValueError(
            f"PolySAT source revision is not pinned commit {POLYSAT_COMMIT}: "
            f"{revision.stdout.strip() or revision.stderr.strip()}"
        )
    status = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("PolySAT source has tracked or staged modifications")
    if not executable.is_relative_to(source):
        raise ValueError("PolySAT executable is outside the pinned source checkout")
    return {
        "source": str(source),
        "source_commit": POLYSAT_COMMIT,
        "tracked_source_clean": True,
    }


def polysat_activation_probe(polysat_z3: Path) -> dict:
    query = "\n".join(
        (
            "(set-logic QF_BV)",
            "(declare-fun x () (_ BitVec 16))",
            "(assert (= (bvmul x x) #x0002))",
            "(check-sat)",
            "",
        )
    )
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="polysat-activation-", suffix=".smt2", delete=False
    ) as handle:
        handle.write(query)
        query_path = Path(handle.name)
    command = [
        str(polysat_z3),
        *POLYSAT_OPTIONS,
        "timeout=10",
        "-st",
        str(query_path),
    ]
    try:
        outcome = _run_command(command, timeout_sec=2.0)
    finally:
        query_path.unlink(missing_ok=True)
    evidence = bool(re.search(r":polysat-[A-Za-z0-9-]+", outcome["stdout"]))
    if outcome["result"] != "unknown" or not evidence:
        raise ValueError(
            "pinned PolySAT activation probe did not produce unknown plus "
            ":polysat-* statistics"
        )
    return {
        "query": query,
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "command": command[:-1] + ["<temporary-query>"],
        "polysat_statistics_present": evidence,
        **outcome,
    }


def run_baselines(
    corpus_directory: Path,
    output_path: Path,
    *,
    benchmark_root: Path,
    local_z3: Path,
    polysat_z3: Path,
    polysat_source: Path,
    trials: int,
    timeout_sec: float,
) -> dict:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite solver matrix: {output_path}")
    manifest_path = corpus_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "pono-modular-algebraic-c2-corpus-v1":
        raise ValueError("unsupported C2 corpus schema")
    source_provenance = validate_polysat_source(polysat_source, polysat_z3)
    arms = solver_arms(local_z3, polysat_z3)
    activation_probe = polysat_activation_probe(polysat_z3)
    arm_metadata = []
    for arm in arms:
        executable = arm["executable"]
        arm_metadata.append(
            {
                **{key: value for key, value in arm.items() if key not in {"executable", "kind"}},
                "executable": str(executable),
                "executable_sha256": file_sha256(executable),
                "kind": arm["kind"],
            }
        )
    rows = []
    for query in manifest.get("queries", []):
        query_path = corpus_directory / query["query"]
        if file_sha256(query_path) != query["query_sha256"]:
            raise ValueError(f"query hash mismatch: {query_path}")
        model_path = benchmark_root / query["benchmark_id"]
        if file_sha256(model_path) != query["benchmark_content_sha256"]:
            raise ValueError(f"benchmark hash mismatch: {model_path}")
        for arm in arms:
            for trial in range(trials):
                if arm["kind"] == "python":
                    command = [
                        str(arm["executable"]),
                        str(Path(__file__).resolve()),
                        "--python-worker",
                        str(query_path),
                        "--timeout-ms",
                        str(int(timeout_sec * 1000)),
                    ]
                else:
                    command = [
                        str(arm["executable"]),
                        *arm["options"],
                        f"timeout={int(timeout_sec * 1000)}",
                        str(query_path),
                    ]
                outcome = _run_command(
                    command,
                    timeout_sec=timeout_sec + 5.0,
                )
                if arm["kind"] == "python" and outcome["returncode"] == 0:
                    try:
                        worker_report = json.loads(outcome["stdout"])
                    except json.JSONDecodeError:
                        outcome["result"] = "error"
                        outcome["stderr"] += "\ninvalid JSON from Python Z3 worker"
                    else:
                        outcome["result"] = worker_report["result"]
                        outcome["solver_time_sec"] = worker_report[
                            "solver_time_sec"
                        ]
                        outcome["reason_unknown"] = worker_report[
                            "reason_unknown"
                        ]
                        outcome["solver_statistics"] = worker_report[
                            "statistics"
                        ]
                polysat_evidence = bool(
                    re.search(r":polysat-[A-Za-z0-9-]+", outcome["stdout"])
                )
                if arm["id"] == "pinned-z3-polysat" and outcome["result"] in {
                    "sat",
                    "unsat",
                    "unknown",
                } and not polysat_evidence:
                    outcome["result"] = "configuration-unverified"
                    outcome["stderr"] += (
                        "\nmissing :polysat-* statistics; PolySAT use is not evidenced"
                    )
                rows.append(
                    {
                        "benchmark_id": query["benchmark_id"],
                        "query_sha256": query["query_sha256"],
                        "role": query["role"],
                        "counts_toward_h5a": query["counts_toward_h5a"],
                        "obligation": "C2",
                        "arm": arm["id"],
                        "trial": trial,
                        "command": command,
                        "polysat_statistics_present": polysat_evidence,
                        **outcome,
                    }
                )
    report = {
        "schema": "pono-modular-algebraic-solver-matrix-v1",
        "corpus_manifest_sha256": file_sha256(manifest_path),
        "trials": trials,
        "solver_timeout_sec": timeout_sec,
        "process_timeout_sec": timeout_sec + 5.0,
        "polysat_source": source_provenance,
        "polysat_activation_probe": activation_probe,
        "arms": arm_metadata,
        "rows": rows,
    }
    report["report_sha256"] = canonical_sha256(report)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_directory", nargs="?", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--benchmark-root", type=Path)
    parser.add_argument("--local-z3", type=Path, default=Path.home() / ".local/bin/z3")
    parser.add_argument("--polysat-z3", type=Path)
    parser.add_argument("--polysat-source", type=Path)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--python-worker", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    args = parser.parse_args(argv)
    if args.python_worker is not None:
        try:
            report = python_worker(args.python_worker, args.timeout_ms)
        except (OSError, ValueError, z3.Z3Exception) as error:
            print(json.dumps({"result": "error", "error": str(error)}))
            return 2
        print(json.dumps(report, sort_keys=True))
        return 0 if report["result"] in {"sat", "unsat", "unknown"} else 2
    if (
        args.corpus_directory is None
        or args.output is None
        or args.benchmark_root is None
        or args.polysat_z3 is None
        or args.polysat_source is None
    ):
        parser.error(
            "corpus_directory, output, --benchmark-root, --polysat-z3, and "
            "--polysat-source are required"
        )
    if args.trials <= 0 or args.timeout_sec <= 0:
        parser.error("--trials and --timeout-sec must be positive")
    try:
        report = run_baselines(
            args.corpus_directory,
            args.output,
            benchmark_root=args.benchmark_root,
            local_z3=args.local_z3,
            polysat_z3=args.polysat_z3,
            polysat_source=args.polysat_source,
            trials=args.trials,
            timeout_sec=args.timeout_sec,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    counts: dict[str, dict[str, int]] = {}
    for row in report["rows"]:
        arm = counts.setdefault(row["arm"], {})
        arm[row["result"]] = arm.get(row["result"], 0) + 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
