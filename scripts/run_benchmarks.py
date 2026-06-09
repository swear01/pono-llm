#!/usr/bin/env python3
"""
Unified benchmark runner for pono + LLM evaluation.

Phases:
  test     - Run built-in tests (make check + tests/python + schema + sidecar)
  download - Download HWMCC benchmarks (2020/2024/2025)
  baseline       - Run baseline pono on all filtered benchmarks
  baseline-patch - Reconcile suspended run from nohup.log (trust timeout/memout, re-run error/unknown)
                   Resume with: --phase baseline --skip-partial (reads results_baseline_partial.csv)
  llm            - Run +LLM pono on interesting (medium/slow/timeout) benchmarks
  report   - Generate markdown report from CSV results
  hwmcc    - download + baseline + llm + report (full pipeline)
  all      - test + download + baseline + llm + report

Usage:
  python3 scripts/run_benchmarks.py --all --hwmcc-dir ~/hwmcc_benchmarks --parallel 4
  python3 scripts/run_benchmarks.py --phase test
  python3 scripts/run_benchmarks.py --phase download --hwmcc-dir ~/hwmcc_benchmarks
  python3 scripts/run_benchmarks.py --phase hwmcc --hwmcc-dir ~/hwmcc_benchmarks --parallel 8

Recommended workflow (see docs/hwmcc_experiment_tiers.md):
  Tier 0: scripts/smoke_p040.sh
  Tier 1: --phase baseline (full HWMCC, no LLM)
  Tier 2: --phase report + --phase find-solvable
  Tier 3: --phase llm --parallel 8
  Legacy full pipeline: --phase hwmcc (= download + baseline + llm + report)

Interrupted baseline (suspend -> patch -> resume):
  python3 scripts/run_benchmarks.py --phase baseline-patch \\
    --output-dir OUT --baseline-log OUT/nohup.log --parallel 8
  python3 scripts/run_benchmarks.py --phase baseline --skip-partial \\
    --output-dir OUT --hwmcc-dir ~/hwmcc_benchmarks --parallel 8
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid


def _llm_worker_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "llm_worker"


def _load_repo_env() -> pathlib.Path | None:
    worker = _llm_worker_dir()
    if str(worker) not in sys.path:
        sys.path.insert(0, str(worker))
    from env_config import load_env

    return load_env()


def _resolve_llm_provider(cli_provider: str = "") -> str:
    _load_repo_env()
    from env_config import get_llm_provider

    return get_llm_provider(cli_provider or None)


def _resolve_llm_model(cli_model: str = "", cli_provider: str = "") -> str:
    _load_repo_env()
    from env_config import default_model, get_llm_provider

    if cli_model:
        return cli_model
    return default_model(get_llm_provider(cli_provider or None))


def _llm_api_key_configured(cli_provider: str = "") -> bool:
    _load_repo_env()
    from env_config import get_api_key, get_llm_provider

    return bool(get_api_key(get_llm_provider(cli_provider or None)))
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields
from typing import Optional

# ── download source definitions ──────────────────────────────────────────

HWMCC_SOURCES: dict[int, dict[str, str]] = {
    2020: {
        "benchmarks": "https://hwmcc.github.io/2020/hwmcc20benchmarks.tar.xz",
        "status_bv": "https://hwmcc.github.io/2020/hwmcc20-bv-all.csv",
        "status_array": "https://hwmcc.github.io/2020/hwmcc20-array-all.csv",
        "benchmarks_format": "tar.xz",
    },
    2024: {
        "benchmarks_bv": "https://zenodo.org/records/14156844/files/benchmarks_btor2_bv.tar.gz",
        "benchmarks_array": "https://zenodo.org/records/14156844/files/benchmarks_btor2_array.tar.gz",
        "status_bv": "https://zenodo.org/records/14156844/files/hwmcc24_results_btor2_bv.csv",
        "status_array": "https://zenodo.org/records/14156844/files/hwmcc24_results_btor2_array.csv",
        "benchmarks_format": "tar.gz",
    },
    2025: {
        "benchmarks_bv": "https://zenodo.org/records/17428464/files/hwmcc25-benchmarks-wordlevel-bv.tar.gz",
        "benchmarks_array": "https://zenodo.org/records/17428464/files/hwmcc25-benchmarks-wordlevel-array.tar.gz",
        "status_bv": "https://zenodo.org/records/17428464/files/hwmcc25-wordlevel-bv.csv",
        "status_array": "https://zenodo.org/records/17428464/files/hwmcc25-wordlevel-array.csv",
        "benchmarks_format": "tar.gz",
    },
}


# ── data classes ─────────────────────────────────────────────────────────

@dataclass
class BenchEntry:
    """A single benchmark record."""

    path: str
    year: int
    track: str  # "bv" or "array"
    expected: str  # "sat" or "unsat"


@dataclass
class RunResult:
    """Result from a single pono run."""

    benchmark: str
    year: int
    track: str
    expected: str
    mode: str  # "baseline" or "llm"
    result: str  # "sat", "unsat", "timeout", "error"
    wall_time: float  # seconds
    category: str  # "fast", "medium", "slow", "timeout"
    match: bool  # result matches expected
    llm_accepted: int = 0
    llm_rejected: int = 0
    llm_errors: int = 0
    llm_requests: int = 0
    llm_candidates: int = 0
    llm_schema_fail: int = 0
    llm_parse_fail: int = 0
    llm_vocab_fail: int = 0
    llm_induction_fail: int = 0
    llm_rejected_initial: int = 0
    llm_missing_block: int = 0
    llm_lookup_miss: int = 0
    llm_attempt_mismatch: int = 0
    llm_budget_skip: int = 0
    llm_predicates_added: int = 0
    llm_batch_timeouts: int = 0
    llm_batch_waits: int = 0
    llm_batch_wait_ms_total: int = 0
    llm_batch_wait_ms_max: int = 0


RESULT_FIELDS = [f.name for f in fields(RunResult)]

# Keys from engines/llm_generalizer.cpp LLM_STATS line (minus accepted/rejected/errors).
_LLM_STAT_KEY_MAP: dict[str, str] = {
    "requests": "llm_requests",
    "candidates": "llm_candidates",
    "schema_fail": "llm_schema_fail",
    "parse_fail": "llm_parse_fail",
    "vocab_fail": "llm_vocab_fail",
    "induction_fail": "llm_induction_fail",
    "rejected_initial": "llm_rejected_initial",
    "missing_block": "llm_missing_block",
    "lookup_miss": "llm_lookup_miss",
    "attempt_mismatch": "llm_attempt_mismatch",
    "budget_skip": "llm_budget_skip",
    "predicates_added": "llm_predicates_added",
    "batch_timeouts": "llm_batch_timeouts",
    "batch_waits": "llm_batch_waits",
    "batch_wait_ms_total": "llm_batch_wait_ms_total",
    "batch_wait_ms_max": "llm_batch_wait_ms_max",
}


# ── CLI ──────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Unified benchmark runner for pono + LLM",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run all phases: test + download + baseline + llm + report",
    )
    p.add_argument(
        "--phase",
        choices=[
            "test", "download", "baseline", "baseline-patch", "llm", "report",
            "hwmcc", "all", "find-solvable",
        ],
        default="hwmcc",
        help="Which phase(s) to run",
    )
    p.add_argument(
        "--hwmcc-dir",
        type=pathlib.Path,
        default=pathlib.Path.home() / "hwmcc_benchmarks",
        help="Root directory for HWMCC benchmarks",
    )
    p.add_argument(
        "--hwmcc-years",
        default="2020,2024,2025",
        help="Comma-separated HWMCC years to process",
    )
    p.add_argument(
        "--pono-bin",
        type=pathlib.Path,
        default=None,
        help="Path to pono binary (default: ./build/pono)",
    )
    p.add_argument(
        "--engine",
        default="ic3ia",
        help="Pono engine to use",
    )
    p.add_argument(
        "--bound",
        type=int,
        default=100000,
        help="Bound (-k) value",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=1000,
        help="Timeout per benchmark in seconds",
    )
    p.add_argument(
        "--parallel",
        type=int,
        default=8,
        help="Max parallel workers (default 8 for 32-core / 125GiB hosts)",
    )
    p.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path("./bench_results"),
        help="Directory for CSV/output files",
    )
    p.add_argument(
        "--fast-threshold",
        type=float,
        default=30.0,
        help="Runtime below this (seconds) is 'fast' (skipped for +llm)",
    )
    p.add_argument(
        "--medium-threshold",
        type=float,
        default=500.0,
        help="Runtime below this (seconds) is 'medium'",
    )
    p.add_argument(
        "--sidecar-path",
        type=pathlib.Path,
        default=None,
        help="Path to sidecar.py (default: <repo>/llm_worker/sidecar.py)",
    )
    p.add_argument(
        "--prompt-dir",
        type=pathlib.Path,
        default=None,
        help="Path to prompt directory (default: <repo>/llm_worker/prompts)",
    )
    p.add_argument(
        "--llm-accepted-budget",
        type=int,
        default=50,
        help="Max accepted LLM lemmas per benchmark",
    )
    p.add_argument(
        "--llm-max-requests",
        type=int,
        default=0,
        help="Max LLM requests per sidecar (0 = unlimited)",
    )
    p.add_argument(
        "--llm-provider",
        choices=["", "deepseek", "openrouter"],
        default="",
        help="LLM API provider (default: LLM_PROVIDER from .env or deepseek)",
    )
    p.add_argument(
        "--llm-model",
        default="",
        help="LLM model name (default: provider default; see --llm-provider)",
    )
    p.add_argument(
        "--llm-phase",
        choices=["competition", "a", "b"],
        default="competition",
        help=(
            "LLM target set from results_baseline.csv: "
            "a=non-fast solved (algorithm validity), "
            "b=timeout+memout (seek new solves), "
            "competition=legacy competition filter"
        ),
    )
    p.add_argument(
        "--snapshot-max-clauses",
        type=int,
        default=0,
        help="Frame snapshot mode for +LLM (0=digest/Track A, >0=legacy tail-N)",
    )
    p.add_argument(
        "--llm-drain-sec",
        type=int,
        default=300,
        help="Seconds to drain sidecar after each +LLM benchmark",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Even if baseline is medium/slow/timeout, skip +llm phase",
    )
    p.add_argument(
        "--memory-limit",
        type=float,
        default=14.0,
        help="Memory limit per benchmark in GB (soft; 14 fits 8-way on 125GiB)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of benchmarks (0=all, useful for testing)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be done without executing",
    )
    p.add_argument(
        "--find-solvable",
        action="store_true",
        help="Find IC3IA-solvable non-fast benchmarks that have refinement cycles",
    )
    p.add_argument(
        "--find-max",
        type=int,
        default=0,
        help="Max benchmarks to probe in find-solvable (0=all collected entries)",
    )
    p.add_argument(
        "--baseline-log",
        type=pathlib.Path,
        default=None,
        help="Nohup log for baseline-patch (default: <output-dir>/nohup.log)",
    )
    p.add_argument(
        "--skip-partial",
        action="store_true",
        help="Skip benchmarks already in results_baseline_partial.csv when resuming baseline",
    )
    p.add_argument(
        "--partial-csv",
        type=pathlib.Path,
        default=None,
        help="Partial baseline CSV for --skip-partial (default: <output-dir>/results_baseline_partial.csv)",
    )
    p.add_argument(
        "--run-id",
        default="",
        help="LLM run archive ID (default: timestamp YYYYMMDD_HHMMSS)",
    )
    p.add_argument(
        "--archive-full-requests",
        action="store_true",
        help="Always archive requests.jsonl even when req_n=0 (debug; larger)",
    )
    return p.parse_args()


# ── utilities ────────────────────────────────────────────────────────────


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def download_file(url: str, dest: pathlib.Path) -> None:
    log(f"  downloading {url} ...")
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _report(count, block_size, total_size):
        pct = min(100, int(count * block_size * 100 / total_size)) if total_size > 0 else 0
        if pct % 20 == 0:
            print(f"    {pct}%", end="", flush=True)

    urllib.request.urlretrieve(url, str(dest), reporthook=_report)
    print("")
    log(f"  downloaded -> {dest}")


def extract_tarball(tarball: pathlib.Path, dest_dir: pathlib.Path) -> None:
    log(f"  extracting {tarball.name} -> {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    mode = "r:xz" if tarball.suffix == ".xz" else "r:gz"
    with tarfile.open(tarball, mode) as tf:
        tf.extractall(path=dest_dir)
    log(f"  extraction complete")


def collect_btor2_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Recursively find all .btor2 files under root."""
    return sorted(root.rglob("*.btor2"))


# ── Phase: test ──────────────────────────────────────────────────────────


def _can_import_pono(root: pathlib.Path) -> bool:
    """Return True if pono Python bindings are importable."""
    build_python = root / "build" / "python"
    if not build_python.is_dir():
        return False
    env = os.environ.copy()
    env["PYTHONPATH"] = str(build_python) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-c", "import pono"],
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
    )
    return r.returncode == 0


def run_phase_test(args: argparse.Namespace) -> bool:
    """Run built-in tests: make check, schema tests, optional sidecar E2E."""
    log("=== Phase: test ===")
    root = repo_root()
    build_dir = root / "build"
    ok = True

    if not (build_dir / "Makefile").exists():
        log("ERROR: build directory not configured. Run ./configure.sh first.")
        return False

    log("Running make check ...")
    r = subprocess.run(["make", "-C", str(build_dir), "check"],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log("make check FAILED:")
        log(r.stderr[-2000:] if len(r.stderr) > 2000 else r.stderr)
        ok = False
    else:
        log("make check PASSED")

    python_tests = root / "tests" / "python"
    if python_tests.is_dir():
        if _can_import_pono(root):
            log("Running pytest tests/python ...")
            env = os.environ.copy()
            build_python = root / "build" / "python"
            env["PYTHONPATH"] = str(build_python) + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run(
                [sys.executable, "-m", "pytest", str(python_tests), "-q"],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(root),
                env=env,
            )
            if r.returncode != 0:
                log("pytest tests/python FAILED:")
                log(r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout)
                log(r.stderr[-2000:] if len(r.stderr) > 2000 else r.stderr)
                ok = False
            else:
                log("pytest tests/python PASSED")
        else:
            log(
                "SKIP tests/python (Python bindings not built; "
                "run ./configure.sh --python)"
            )
    else:
        log("tests/python not found, skipping")

    llm_worker_tests = root / "llm_worker" / "tests"
    if llm_worker_tests.is_dir():
        log("Running pytest llm_worker/tests ...")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(llm_worker_tests), "-q"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("pytest llm_worker/tests FAILED:")
            log(r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout)
            log(r.stderr[-2000:] if len(r.stderr) > 2000 else r.stderr)
            ok = False
        else:
            log("pytest llm_worker/tests PASSED")
    else:
        log("llm_worker/tests not found, skipping")

    sidecar_test = root / "test_sidecar.py"
    if sidecar_test.exists():
        if not _llm_api_key_configured():
            log("SKIP test_sidecar.py --with-llm (no LLM API key in .env / environment)")
        else:
            log("Running test_sidecar.py --with-llm ...")
            env = os.environ.copy()
            r = subprocess.run(
                [sys.executable, str(sidecar_test), "--with-llm"],
                capture_output=True, text=True, timeout=300,
                env=env, cwd=str(root),
            )
            if "PASS" not in r.stdout and r.returncode != 0:
                log("test_sidecar.py FAILED:")
                log(r.stdout[-1000:])
                log(r.stderr[-1000:])
                ok = False
            else:
                log("test_sidecar.py PASSED")
    else:
        log("test_sidecar.py not found, skipping")

    phase_l_tests = root / "scripts" / "tests"
    if phase_l_tests.is_dir():
        log("Running pytest scripts/tests (Phase L harness) ...")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(phase_l_tests), "-q"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("pytest scripts/tests FAILED:")
            log(r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout)
            log(r.stderr[-2000:] if len(r.stderr) > 2000 else r.stderr)
            ok = False
        else:
            log("pytest scripts/tests PASSED")
    else:
        log("scripts/tests not found, skipping Phase L harness tests")

    return ok


# ── Phase: download ──────────────────────────────────────────────────────


def run_phase_download(args: argparse.Namespace) -> bool:
    """Download HWMCC benchmarks and status CSVs."""
    log("=== Phase: download ===")
    years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
    base = args.hwmcc_dir
    base.mkdir(parents=True, exist_ok=True)

    for year in years:
        src = HWMCC_SOURCES.get(year)
        if not src:
            log(f"WARNING: no source definition for HWMCC {year}, skipping")
            continue
        year_dir = base / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        log(f"--- HWMCC {year} ---")

        if year == 2020:
            _download_2020(src, year_dir)
        else:
            _download_modern(year, src, year_dir)

    log("Phase download complete.")
    return True


def _download_2020(src: dict[str, str], year_dir: pathlib.Path) -> None:
    tarball = year_dir / "benchmarks.tar.xz"
    if not tarball.exists():
        download_file(src["benchmarks"], tarball)
    # 2020 tarball extracts to hwmcc20/ subdirectory
    extract_dir = year_dir / "hwmcc20"
    if not extract_dir.exists() or not any(extract_dir.rglob("*.btor2")):
        extract_tarball(tarball, year_dir)

    for key in ["status_bv", "status_array"]:
        if key in src:
            dst = year_dir / pathlib.Path(src[key]).name
            if not dst.exists():
                download_file(src[key], dst)


def _download_modern(year: int, src: dict[str, str], year_dir: pathlib.Path) -> None:
    for kind in ["bv", "array"]:
        bench_key = f"benchmarks_{kind}"
        status_key = f"status_{kind}"
        if bench_key not in src:
            continue
        tarball = year_dir / pathlib.Path(src[bench_key]).name
        if not tarball.exists():
            download_file(src[bench_key], tarball)
        # tarballs extract to year_dir (e.g. 2024/btor2/bv/...)
        if not any(year_dir.rglob("*.btor2")):
            extract_tarball(tarball, year_dir)

        if status_key in src:
            dst = year_dir / pathlib.Path(src[status_key]).name
            if not dst.exists():
                download_file(src[status_key], dst)


# ── Phase: filter ────────────────────────────────────────────────────────


def parse_status_2020(csv_path: pathlib.Path) -> dict[str, str]:
    """Parse 2020 semicolon-delimited multi-solver CSV.
    Returns dict[benchmark_name] -> 'sat'|'unsat'.
    Format: benchmark;solver;status;bound;real;time;mem;solver;status;bound;... (repeating)
    """
    expected: dict[str, str] = {}
    if not csv_path.exists():
        return expected
    with csv_path.open() as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        # Find indices of 'status' columns (position of each status field)
        status_indices = [i for i, h in enumerate(header) if h == "status"]
        for row in reader:
            if len(row) < 2:
                continue
            bench = row[0].strip()
            if not bench or bench in expected:
                continue
            for si in status_indices:
                if si < len(row) and row[si].strip() in ("sat", "uns"):
                    expected[bench] = "sat" if row[si].strip() == "sat" else "unsat"
                    break
    return expected


def parse_status_modern(csv_path: pathlib.Path) -> dict[str, str]:
    """Parse 2024/2025 comma-delimited CSV.
    Format: benchmark,solver/config,status?,result,time_real,time_cpu,memory
    """
    expected: dict[str, str] = {}
    if not csv_path.exists():
        return expected
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        # Detect column naming: 2024 uses 'solver', 2025 uses 'config'
        solver_col = "solver" if "solver" in reader.fieldnames else "config"
        for row in reader:
            bench = row.get("benchmark", "").strip()
            result = row.get("result", "").strip()
            if not bench or bench in expected:
                continue
            if result in ("sat", "unsat"):
                expected[bench] = result
    return expected


def build_expected_map(hwmcc_dir: pathlib.Path, years: list[int]) -> dict[str, str]:
    """Build map from key 'year/track/benchmark_name' -> expected (sat/unsat)."""
    expected: dict[str, str] = {}

    for year in years:
        year_dir = hwmcc_dir / str(year)

        if year == 2020:
            for track, csv_name in [("bv", "hwmcc20-bv-all.csv"), ("array", "hwmcc20-array-all.csv")]:
                csv_path = year_dir / csv_name
                if csv_path.exists():
                    result = parse_status_2020(csv_path)
                    for bench, exp in result.items():
                        expected[f"{year}/{track}/{bench}"] = exp
        else:
            for track in ["bv", "array"]:
                candidates = sorted(year_dir.glob(f"*{track}*.csv"))
                if not candidates:
                    candidates = sorted(year_dir.glob(f"*results*{track}*.csv"))
                if not candidates:
                    continue
                csv_path = candidates[0]
                result = parse_status_modern(csv_path)
                for bench, exp in result.items():
                    expected[f"{year}/{track}/{bench}"] = exp

    return expected


def match_benchmark_to_expected(
    btor2_path: pathlib.Path,
    hwmcc_dir: pathlib.Path,
    year: int,
    expected_map: dict[str, str],
    *,
    verbose: bool = False,
) -> Optional[BenchEntry]:
    """Try to match a .btor2 file to an expected result."""
    year_dir = hwmcc_dir / str(year)
    rel = str(btor2_path.relative_to(year_dir))

    # Determine track from path structure
    track = "bv"
    parts = pathlib.PurePosixPath(rel).parts
    if "array" in (p.lower() for p in parts):
        track = "array"

    basename = btor2_path.name
    stem = btor2_path.stem  # name without .btor2

    for (exp_year, exp_track, exp_bench) in _iter_expected_keys(expected_map):
        if exp_year != str(year):
            continue
        exp_val = expected_map[f"{exp_year}/{exp_track}/{exp_bench}"]
        # Try exact relative path match
        if exp_bench == rel:
            return BenchEntry(path=str(btor2_path), year=year, track=exp_track, expected=exp_val)
        # Try basename match
        if exp_bench.endswith(basename) or exp_bench.endswith(stem):
            return BenchEntry(path=str(btor2_path), year=year, track=exp_track, expected=exp_val)
        # 2020: stem-only match
        if exp_bench.rsplit("/", 1)[-1] == stem:
            return BenchEntry(path=str(btor2_path), year=year, track=exp_track, expected=exp_val)

    return None


def _iter_expected_keys(expected_map: dict[str, str]):
    for k in expected_map:
        parts = k.split("/", 2)
        if len(parts) == 3:
            yield parts[0], parts[1], parts[2]


# ── competition classification ────────────────────────────────────────────

@dataclass
class CompEntry:
    """Per-benchmark competition result for pono."""
    result: str  # "sat", "unsat", "timeout", "mem"
    wall_time: float
    category: str  # "fast", "medium", "slow", "timeout"


def load_competition_classification(
    hwmcc_dir: pathlib.Path,
) -> dict[str, CompEntry]:
    """Build map from 'year/track/benchmark_name' -> CompEntry from competition CSVs."""
    comp_map: dict[str, CompEntry] = {}

    # 2024 / 2025
    for year in [2024, 2025]:
        for track in ["bv", "array"]:
            csv_files = sorted((hwmcc_dir / str(year)).glob(f"*{track}*.csv"))
            if not csv_files:
                csv_files = sorted((hwmcc_dir / str(year)).glob(f"*results*{track}*.csv"))
            if not csv_files:
                continue
            with csv_files[0].open() as f:
                reader = csv.DictReader(f)
                # 2024 uses 'solver' column, 2025 uses 'config'
                solver_col = "solver" if "solver" in reader.fieldnames else "config"
                for row in reader:
                    solver = row.get(solver_col, "").strip()
                    if solver != "pono":
                        continue
                    bench = row.get("benchmark", "").strip()
                    result = row.get("result", "").strip()
                    try:
                        wall_time = float(row.get("time_real", 0))
                    except (ValueError, TypeError):
                        wall_time = 0
                    if result == "none" or result == "":
                        result, wall_time = "timeout", 3600.0
                        cat = "timeout"
                    elif result == "unknown":
                        cat = "unknown"  # finished but couldn't decide
                    elif wall_time < 30:
                        cat = "fast"
                    elif wall_time < 500:
                        cat = "medium"
                    else:
                        cat = "slow"
                    comp_map[f"{year}/{track}/{bench}"] = CompEntry(
                        result=result, wall_time=wall_time, category=cat,
                    )

    # 2020
    for track in ["bv", "array"]:
        csv_path = hwmcc_dir / "2020" / f"hwmcc20-{track}-all.csv"
        if not csv_path.exists():
            continue
        rows = list(csv.reader(csv_path.open(), delimiter=";"))
        header = rows[0]
        solver_positions = [i for i, h in enumerate(header) if h == "solver"]
        pono_offset = None
        for si in solver_positions:
            if si < len(rows[1]) and rows[1][si].strip() == "pono":
                pono_offset = si
                break
        if pono_offset is None:
            for r in rows[2:15]:
                for si in solver_positions:
                    if si < len(r) and r[si].strip() == "pono":
                        pono_offset = si
                        break
                if pono_offset:
                    break
        if pono_offset is None:
            continue
        for row in rows[1:]:
            if len(row) < 2:
                continue
            bench = row[0].strip()
            if not bench:
                continue
            status = row[pono_offset + 1].strip() if pono_offset + 1 < len(row) else ""
            real_str = row[pono_offset + 3].strip() if pono_offset + 3 < len(row) else "0"
            try:
                wall_time = float(real_str)
            except (ValueError, TypeError):
                wall_time = 0
            result = status
            if result == "time" or result == "":
                result, wall_time = "timeout", 3600.0
                cat = "timeout"
            elif result == "uns":
                result = "unsat"
                if wall_time < 30:
                    cat = "fast"
                elif wall_time < 500:
                    cat = "medium"
                else:
                    cat = "slow"
            elif result == "unk":
                cat = "unknown"
            else:
                if wall_time < 30:
                    cat = "fast"
                elif wall_time < 500:
                    cat = "medium"
                else:
                    cat = "slow"
            comp_map[f"2020/{track}/{bench}"] = CompEntry(
                result=result, wall_time=wall_time, category=cat,
            )

    return comp_map


def match_entry_to_competition(
    entry: BenchEntry,
    comp_map: dict[str, CompEntry],
) -> Optional[CompEntry]:
    """Match a BenchEntry to its competition classification."""
    basename = pathlib.Path(entry.path).name
    stem = pathlib.Path(entry.path).stem

    # Exact key match
    key = f"{entry.year}/{entry.track}/{basename}"
    if key in comp_map:
        return comp_map[key]
    key = f"{entry.year}/{entry.track}/{stem}"
    if key in comp_map:
        return comp_map[key]

    # Search by basename across year and both tracks
    for k, v in comp_map.items():
        parts = k.split("/", 2)
        if len(parts) != 3:
            continue
        cy, ct, cb = parts
        if cy == str(entry.year):
            if cb.endswith(basename) or cb.endswith(stem) or cb.rsplit("/", 1)[-1] == stem:
                return v
    return None


def collect_benchmarks(
    hwmcc_dir: pathlib.Path,
    years: list[int],
    *,
    verbose: bool = False,
) -> list[BenchEntry]:
    """Collect all benchmarks with known expected answers, excluding
    those where pono's competition result was 'unknown'."""
    log("Building expected answer map from status CSVs ...")
    expected_map = build_expected_map(hwmcc_dir, years)
    log(f"  {len(expected_map)} unique benchmarks with known answers")

    comp_map = load_competition_classification(hwmcc_dir)

    entries: list[BenchEntry] = []
    skipped_unknown = 0
    for year in years:
        year_dir = hwmcc_dir / str(year)
        if not year_dir.exists():
            log(f"  WARNING: {year_dir} does not exist, skipping")
            continue
        btor2_files = collect_btor2_files(year_dir)
        log(f"  HWMCC {year}: {len(btor2_files)} .btor2 files found")
        for f in btor2_files:
            entry = match_benchmark_to_expected(f, hwmcc_dir, year, expected_map, verbose=verbose)
            if not entry:
                continue
            # Filter out benchmarks where pono returned "unknown" in competition
            ce = match_entry_to_competition(entry, comp_map)
            if ce and ce.category == "unknown":
                skipped_unknown += 1
                continue
            entries.append(entry)
    if skipped_unknown:
        log(f"  Skipped {skipped_unknown} benchmarks (pono competition result was 'unknown')")
    log(f"Total: {len(entries)} benchmarks with known answers")
    return entries


# ── Phase: run pono ──────────────────────────────────────────────────────


def _parse_pono_stdout(stdout: str | None, returncode: int) -> str:
    """Parse pono stdout. BTOR2 prints 'sat|unsat|unknown|error' then 'bN' on the next line."""
    text = (stdout or "").strip()
    if not text:
        return "unknown" if returncode == 0 else "error"
    first = text.splitlines()[0].strip().lower()
    if first in ("sat", "unsat", "unknown", "error"):
        return first
    return "unknown" if returncode == 0 else "error"


def _category_from_run(result: str, wall_time: float) -> str:
    if result in ("timeout", "error", "memout"):
        return result
    if wall_time < 30:
        return "fast"
    if wall_time < 500:
        return "medium"
    return "slow"


def _parse_llm_stats(stderr: str) -> dict[str, int]:
    """Parse LLM_STATS line from pono stderr into field-name -> int."""
    stats: dict[str, int] = {
        "llm_accepted": 0,
        "llm_rejected": 0,
        "llm_errors": 0,
    }
    for field_name in _LLM_STAT_KEY_MAP.values():
        stats[field_name] = 0

    last_line = ""
    for line in stderr.splitlines():
        if line.strip().startswith("LLM_STATS"):
            last_line = line.strip()

    if not last_line:
        return stats

    for part in last_line.split():
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        try:
            int_val = int(val)
        except ValueError:
            continue
        if key == "accepted":
            stats["llm_accepted"] = int_val
        elif key == "rejected":
            stats["llm_rejected"] = int_val
        elif key == "errors":
            stats["llm_errors"] = int_val
        elif key in _LLM_STAT_KEY_MAP:
            stats[_LLM_STAT_KEY_MAP[key]] = int_val
    return stats


def _parse_llm_batch_waits_from_stderr(stderr: str) -> dict[str, int]:
    """Sum LLM_BATCH_WAIT lines when pono exits without LLM_STATS (e.g. harness kill)."""
    waits = 0
    total_ms = 0
    max_ms = 0
    timeouts = 0
    for line in stderr.splitlines():
        line = line.strip()
        if not line.startswith("LLM_BATCH_WAIT"):
            continue
        waits += 1
        wait_ms = 0
        ok = 1
        for part in line.split():
            if part.startswith("wait_ms="):
                try:
                    wait_ms = int(part.split("=", 1)[1])
                except ValueError:
                    wait_ms = 0
            elif part.startswith("ok="):
                try:
                    ok = int(part.split("=", 1)[1])
                except ValueError:
                    ok = 1
        total_ms += wait_ms
        if wait_ms > max_ms:
            max_ms = wait_ms
        if ok == 0:
            timeouts += 1
    return {
        "llm_batch_waits": waits,
        "llm_batch_wait_ms_total": total_ms,
        "llm_batch_wait_ms_max": max_ms,
        "llm_batch_timeouts": timeouts,
    }


def _fallback_llm_stats_from_artifacts(
    stderr: str,
    log_path: str = "",
    req_path: str = "",
) -> dict[str, int]:
    """Fill gaps when LLM_STATS is missing but sidecar/pono artifacts exist."""
    stats = _parse_llm_stats(stderr)
    has_llm_stats = any(
        line.strip().startswith("LLM_STATS") for line in stderr.splitlines()
    )
    if has_llm_stats:
        return stats

    if req_path and _count_jsonl_lines(req_path) > 0:
        stats["llm_requests"] = _count_jsonl_lines(req_path)
    elif log_path and _count_jsonl_lines(log_path) > 0:
        stats["llm_requests"] = _count_jsonl_lines(log_path)

    batch = _parse_llm_batch_waits_from_stderr(stderr)
    for key, val in batch.items():
        if stats.get(key, 0) == 0:
            stats[key] = val
    return stats


def _bench_slug(entry: BenchEntry) -> str:
    """Stable archive directory name per benchmark."""
    stem = re.sub(r"[^\w.-]+", "_", pathlib.Path(entry.path).stem)
    return f"{entry.year}_{entry.track}_{stem}"


def _count_jsonl_lines(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    with open(path) as f:
        return sum(1 for _ in f)


def _archive_llm_artifacts(
    tmpdir: str,
    dest: pathlib.Path,
    *,
    pono_stderr: str,
    req_n: int,
    archive_full_requests: bool,
) -> None:
    """Copy per-benchmark LLM artifacts from tmpdir to persistent archive."""
    dest.mkdir(parents=True, exist_ok=True)

    def _copy_if_exists(name: str) -> None:
        src = os.path.join(tmpdir, name)
        if os.path.isfile(src):
            shutil.copy2(src, dest / name)

    if req_n > 0 or archive_full_requests:
        _copy_if_exists("requests.jsonl")
    _copy_if_exists("llm_log.jsonl")
    _copy_if_exists("responses.jsonl")
    _copy_if_exists("sidecar_stderr.log")
    (dest / "pono_stderr.log").write_text(pono_stderr or "")


def _write_run_manifest(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _run_result_llm_summary(r: RunResult) -> dict:
    """Compact LLM stats for run_manifest.json."""
    return {
        "benchmark": r.benchmark,
        "slug": _bench_slug(BenchEntry(
            path=r.benchmark, year=r.year, track=r.track, expected=r.expected,
        )),
        "result": r.result,
        "wall_time": round(r.wall_time, 2),
        "match": r.match,
        "llm_accepted": r.llm_accepted,
        "llm_rejected": r.llm_rejected,
        "llm_requests": r.llm_requests,
        "llm_batch_timeouts": r.llm_batch_timeouts,
        "llm_batch_waits": r.llm_batch_waits,
        "llm_batch_wait_ms_total": r.llm_batch_wait_ms_total,
        "llm_batch_wait_ms_max": r.llm_batch_wait_ms_max,
        "llm_rejected_initial": r.llm_rejected_initial,
        "llm_induction_fail": r.llm_induction_fail,
    }


def run_pono(
    entry: BenchEntry,
    pono_bin: pathlib.Path,
    engine: str,
    bound: int,
    timeout: int,
    mode: str,
    req_path: str = "",
    resp_path: str = "",
    log_path: str = "",
    accepted_budget: int = 50,
    memory_limit_gb: float = 40.0,
    llm_parallel_samples: int = 1,
    llm_reasoning_effort: str = "none",
    llm_batch_wait_sec: int = 300,
    llm_snapshot_max_clauses: int = 0,
    llm_model: str = "",
) -> tuple[RunResult, str]:
    """Run pono on a single benchmark. Returns (RunResult, stderr text)."""
    cmd = [
        str(pono_bin),
        "-e", engine,
        "-k", str(bound),
    ]
    if mode == "baseline":
        cmd.extend(["--llm-gen-mode", "none"])
    else:
        cmd.extend([
            "--llm-gen-mode", "async-cti",
            "--llm-accepted-budget", str(accepted_budget),
            "--llm-parallel-samples", str(llm_parallel_samples),
            "--llm-reasoning-effort", llm_reasoning_effort,
            "--llm-batch-wait-sec", str(llm_batch_wait_sec),
            "--llm-snapshot-max-clauses", str(llm_snapshot_max_clauses),
            "--llm-req-path", req_path,
            "--llm-resp-path", resp_path,
            "--llm-log", log_path,
        ])
        if llm_model:
            cmd.extend(["--llm-model", llm_model])
    cmd.append(entry.path)

    t0 = time.time()
    memout = threading.Event()
    limit_bytes = int(memory_limit_gb * 1024 * 1024 * 1024)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        wall = time.time() - t0
        return RunResult(
            benchmark=entry.path, year=entry.year, track=entry.track,
            expected=entry.expected, mode=mode,
            result="error", wall_time=wall, category="error", match=False,
        ), ""

    def _mem_monitor():
        """Kill proc if RSS exceeds limit, checking every 5s."""
        while proc.poll() is None and not memout.is_set():
            memout.wait(5)
            try:
                with open(f"/proc/{proc.pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss_kb = int(line.split()[1])
                            if rss_kb * 1024 > limit_bytes:
                                proc.kill()
                                return
                            break
            except (FileNotFoundError, ProcessLookupError, ValueError):
                return  # process already gone

    monitor = threading.Thread(target=_mem_monitor, daemon=True)

    try:
        monitor.start()
        stdout, stderr = proc.communicate(timeout=timeout)
        wall = time.time() - t0
        monitor.join(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        wall = time.time() - t0
        result = "timeout"
    else:
        if memout.is_set() or proc.returncode == -9:
            result = "memout"
            wall = time.time() - t0
        else:
            result = _parse_pono_stdout(stdout, proc.returncode)

    llm_stats: dict[str, int] = {}
    if mode == "llm":
        try:
            llm_stats = _fallback_llm_stats_from_artifacts(
                stderr or "", log_path=log_path, req_path=req_path
            )
        except Exception:
            llm_stats = {}

    category = _category_from_run(result, wall)

    match = (result == entry.expected)

    run_result = RunResult(
        benchmark=entry.path,
        year=entry.year,
        track=entry.track,
        expected=entry.expected,
        mode=mode,
        result=result,
        wall_time=wall,
        category=category,
        match=match,
        llm_accepted=llm_stats.get("llm_accepted", 0),
        llm_rejected=llm_stats.get("llm_rejected", 0),
        llm_errors=llm_stats.get("llm_errors", 0),
        llm_requests=llm_stats.get("llm_requests", 0),
        llm_candidates=llm_stats.get("llm_candidates", 0),
        llm_schema_fail=llm_stats.get("llm_schema_fail", 0),
        llm_parse_fail=llm_stats.get("llm_parse_fail", 0),
        llm_vocab_fail=llm_stats.get("llm_vocab_fail", 0),
        llm_induction_fail=llm_stats.get("llm_induction_fail", 0),
        llm_rejected_initial=llm_stats.get("llm_rejected_initial", 0),
        llm_missing_block=llm_stats.get("llm_missing_block", 0),
        llm_lookup_miss=llm_stats.get("llm_lookup_miss", 0),
        llm_attempt_mismatch=llm_stats.get("llm_attempt_mismatch", 0),
        llm_budget_skip=llm_stats.get("llm_budget_skip", 0),
        llm_predicates_added=llm_stats.get("llm_predicates_added", 0),
        llm_batch_timeouts=llm_stats.get("llm_batch_timeouts", 0),
        llm_batch_waits=llm_stats.get("llm_batch_waits", 0),
        llm_batch_wait_ms_total=llm_stats.get("llm_batch_wait_ms_total", 0),
        llm_batch_wait_ms_max=llm_stats.get("llm_batch_wait_ms_max", 0),
    )
    return run_result, stderr or ""


def _run_one_baseline(job: tuple[BenchEntry, pathlib.Path, str, int, int]) -> RunResult:
    entry, pono_bin, engine, bound, timeout = job
    result, _ = run_pono(entry, pono_bin, engine, bound, timeout, "baseline")
    return result


def parse_baseline_nohup_log(log_path: pathlib.Path) -> dict[str, tuple[str, float]]:
    """Parse harness log -> basename -> (logged_result, wall_time)."""
    import re

    text = log_path.read_text()
    current: str | None = None
    out: dict[str, tuple[str, float]] = {}
    for line in text.splitlines():
        m = re.search(r"\[worker \d+\] starting: (.+\.btor2)", line)
        if m:
            current = m.group(1)
            continue
        m = re.search(r"\[worker \d+\] done: (\S+) ([\d.]+)s", line)
        if m and current:
            out[current] = (m.group(1), float(m.group(2)))
            current = None
    return out


def merge_baseline_results(
    entries: list[BenchEntry],
    partial: list[RunResult],
    new_results: list[RunResult],
) -> list[RunResult]:
    """Merge partial + new rows in collect_benchmarks order."""
    by_path: dict[str, RunResult] = {r.benchmark: r for r in partial}
    by_path.update({r.benchmark: r for r in new_results})
    merged: list[RunResult] = []
    missing: list[str] = []
    for entry in entries:
        row = by_path.get(entry.path)
        if row is None:
            missing.append(entry.path)
            continue
        merged.append(row)
    if missing:
        log(f"  WARNING: {len(missing)} benchmarks missing after merge")
    return merged


def _basename_entry_map(entries: list[BenchEntry]) -> dict[str, BenchEntry]:
    out: dict[str, BenchEntry] = {}
    for entry in entries:
        name = pathlib.Path(entry.path).name
        if name in out:
            log(f"  WARNING: duplicate basename {name}; using {entry.path}")
        out[name] = entry
    return out


def run_phase_baseline_patch(
    args: argparse.Namespace,
    entries: list[BenchEntry],
    log_path: pathlib.Path,
) -> list[RunResult]:
    """Rebuild completed baseline rows from log; re-run misclassified error/unknown cases."""
    logged = parse_baseline_nohup_log(log_path)
    log(f"=== Phase: baseline-patch ({len(logged)} completed in log) ===")
    if not logged:
        log(f"No completed benchmarks found in {log_path}")
        return []

    by_name = _basename_entry_map(entries)
    trusted: list[RunResult] = []
    to_rerun: list[BenchEntry] = []
    missing: list[str] = []

    for name, (logged_result, wall_time) in logged.items():
        entry = by_name.get(name)
        if not entry:
            missing.append(name)
            continue
        if logged_result in ("timeout", "memout"):
            trusted.append(RunResult(
                benchmark=entry.path,
                year=entry.year,
                track=entry.track,
                expected=entry.expected,
                mode="baseline",
                result=logged_result,
                wall_time=wall_time,
                category=_category_from_run(logged_result, wall_time),
                match=(logged_result == entry.expected),
            ))
        elif logged_result in ("error", "unknown"):
            to_rerun.append(entry)
        else:
            log(f"  WARNING: unexpected logged result {logged_result!r} for {name}")

    if missing:
        log(f"  WARNING: {len(missing)} log entries not in benchmark list (skipped)")

    log(f"  trusted from log: {len(trusted)} (timeout/memout)")
    log(f"  re-run queue: {len(to_rerun)} (error/unknown)")

    rerun_results: list[RunResult] = []
    if to_rerun:
        pono_bin = _resolve_pono(args)
        from queue import Queue
        from concurrent.futures import ThreadPoolExecutor, as_completed

        q: Queue[BenchEntry | None] = Queue()
        for entry in to_rerun:
            q.put(entry)
        for _ in range(args.parallel):
            q.put(None)

        def _worker() -> list[RunResult]:
            local: list[RunResult] = []
            while True:
                entry = q.get()
                if entry is None:
                    break
                name = pathlib.Path(entry.path).name
                log(f"  patch re-run: {name}")
                result, _ = run_pono(
                    entry, pono_bin, args.engine, args.bound, args.timeout, "baseline",
                    memory_limit_gb=args.memory_limit,
                )
                local.append(result)
                log(f"  patch done: {name} -> {result.result} {result.wall_time:.1f}s")
            return local

        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futs = [pool.submit(_worker) for _ in range(args.parallel)]
            for fut in as_completed(futs):
                rerun_results.extend(fut.result())

    results = trusted + rerun_results
    log(f"baseline-patch total rows: {len(results)}")
    return results


def run_phase_baseline(
    args: argparse.Namespace,
    entries: list[BenchEntry],
    *,
    total_count: int | None = None,
) -> list[RunResult]:
    """Run baseline pono on all entries in parallel using subprocess workers."""
    total = total_count if total_count is not None else len(entries)
    log(f"=== Phase: baseline ({len(entries)} to run, {total} total) ===")
    pono_bin = str(_resolve_pono(args))

    results: list[RunResult] = []
    from queue import Queue
    from threading import Thread

    q: Queue = Queue()
    for e in entries:
        q.put(e)

    def _worker(worker_id: int):
        while True:
            try:
                entry = q.get(timeout=1)
            except Exception:
                return
            log(f"  [worker {worker_id}] starting: {pathlib.Path(entry.path).name}")
            try:
                r, _ = run_pono(entry, pathlib.Path(pono_bin), args.engine,
                                args.bound, args.timeout, "baseline",
                                memory_limit_gb=args.memory_limit)
            except Exception:
                r = RunResult(
                    benchmark=entry.path, year=entry.year, track=entry.track,
                    expected=entry.expected, mode="baseline",
                    result="error", wall_time=0, category="error", match=False,
                )
            log(f"  [worker {worker_id}] done: {r.result} {r.wall_time:.1f}s")
            results.append(r)
            done = len(results)
            skipped = total - len(entries)
            overall = skipped + done
            if done % 10 == 0 or done == len(entries) or done <= 3:
                log(f"  baseline progress: {overall}/{total}")

    log(f"Starting {args.parallel} workers ...")
    threads = [Thread(target=_worker, args=(i,), daemon=True)
               for i in range(args.parallel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


# ── Phase: +llm ──────────────────────────────────────────────────────────

P040_BASENAME = "qspiflash_dualflexpress_divfive-p040.btor2"


def _find_p040_in_baseline(baseline_results: list[RunResult]) -> RunResult | None:
    for row in baseline_results:
        name = pathlib.Path(row.benchmark).name
        if name == P040_BASENAME or name.endswith("p040.btor2"):
            return row
    return None


def select_llm_targets_by_phase(
    baseline_results: list[RunResult],
    phase: str,
    *,
    fast_threshold: float = 30.0,
    include_p040: bool = True,
) -> list[RunResult]:
    """Select +LLM targets from baseline CSV rows (phase a or b)."""
    if phase == "a":
        targets = [
            r for r in baseline_results
            if r.result in ("sat", "unsat") and r.wall_time >= fast_threshold
        ]
        label = f"phase A (non-fast solved, >={fast_threshold}s)"
    elif phase == "b":
        targets = [
            r for r in baseline_results
            if r.result in ("timeout", "memout")
        ]
        label = "phase B (timeout + memout)"
    else:
        raise ValueError(f"select_llm_targets_by_phase: unsupported phase {phase!r}")

    if include_p040:
        p040 = _find_p040_in_baseline(baseline_results)
        if p040 is None:
            log("  WARNING: p040 control benchmark not found in baseline results")
        elif p040.benchmark not in {t.benchmark for t in targets}:
            targets.append(p040)
            log(f"  Added p040 control: {pathlib.Path(p040.benchmark).name}")

    log(f"  LLM {label}: {len(targets)} targets")
    by_result: dict[str, int] = {}
    for t in targets:
        by_result[t.result] = by_result.get(t.result, 0) + 1
    log(f"  Baseline result breakdown: {by_result}")
    return targets


def llm_results_csv_path(args: argparse.Namespace) -> pathlib.Path:
    if args.llm_phase == "a":
        return args.output_dir / "results_llm_phase_a.csv"
    if args.llm_phase == "b":
        return args.output_dir / "results_llm_phase_b.csv"
    return args.output_dir / "results_llm.csv"


def _run_one_llm(job_data: dict) -> RunResult:
    entry = job_data["entry"]
    pono_bin = job_data["pono_bin"]
    engine = job_data["engine"]
    bound = job_data["bound"]
    timeout = job_data["timeout"]
    accepted_budget = job_data["accepted_budget"]
    tmpdir = job_data["tmpdir"]
    sidecar_path = job_data["sidecar_path"]
    prompt_dir = job_data["prompt_dir"]

    req_path = os.path.join(tmpdir, "requests.jsonl")
    resp_path = os.path.join(tmpdir, "responses.jsonl")
    log_path = os.path.join(tmpdir, "llm_log.jsonl")
    sidecar_stderr = os.path.join(tmpdir, "sidecar_stderr.log")
    llm_model = job_data.get("llm_model", "")
    llm_provider = job_data.get("llm_provider", "")

    # Start sidecar
    env = os.environ.copy()
    sidecar_cmd = [
        sys.executable, sidecar_path,
        "--req-path", req_path,
        "--resp-path", resp_path,
        "--log-path", log_path,
        "--prompt-dir", prompt_dir,
        "--poll-interval", "0.5",
        "--max-requests", str(job_data.get("llm_max_requests", 50)),
        "--max-inflight-requests", str(job_data.get("llm_max_inflight", 8)),
        "--snapshot-max-clauses", str(job_data.get("snapshot_max_clauses", 0)),
    ]
    if llm_provider:
        sidecar_cmd.extend(["--provider", llm_provider])
    if llm_model:
        sidecar_cmd.extend(["--model", llm_model])
    sidecar_proc = subprocess.Popen(
        sidecar_cmd,
        stdout=subprocess.DEVNULL,
        stderr=open(sidecar_stderr, "w"),
        env=env,
    )

    time.sleep(1)

    result, pono_stderr = run_pono(
        entry, pono_bin, engine, bound, timeout,
        mode="llm",
        req_path=req_path, resp_path=resp_path, log_path=log_path,
        accepted_budget=accepted_budget,
        memory_limit_gb=job_data.get("memory_limit", 14.0),
        llm_parallel_samples=job_data.get("llm_parallel_samples", 1),
        llm_reasoning_effort=job_data.get("llm_reasoning_effort", "none"),
        llm_batch_wait_sec=job_data.get("llm_batch_wait_sec", 300),
        llm_snapshot_max_clauses=job_data.get("snapshot_max_clauses", 0),
        llm_model=llm_model,
    )

    # Drain sidecar before stopping
    drain_sec = job_data.get("drain_sec", 300)
    deadline = time.time() + drain_sec
    req_n = 0
    while time.time() < deadline:
        req_n = _count_jsonl_lines(req_path)
        log_n = _count_jsonl_lines(log_path)
        if req_n > 0 and log_n >= req_n:
            break
        time.sleep(2)
    else:
        req_n = _count_jsonl_lines(req_path)

    # Stop sidecar
    try:
        sidecar_proc.terminate()
        sidecar_proc.wait(timeout=10)
    except Exception:
        sidecar_proc.kill()

    archive_dir = job_data.get("archive_dir")
    if archive_dir:
        try:
            _archive_llm_artifacts(
                tmpdir,
                pathlib.Path(archive_dir),
                pono_stderr=pono_stderr,
                req_n=req_n,
                archive_full_requests=job_data.get("archive_full_requests", False),
            )
        except Exception as exc:
            log(f"  WARNING: archive failed for {pathlib.Path(entry.path).name}: {exc}")

    return result


def run_phase_llm(
    args: argparse.Namespace,
    baseline_results: list[RunResult],
    comp_map: dict[str, CompEntry],
) -> list[RunResult]:
    """Run +LLM on a target subset of baseline benchmarks."""
    llm_provider = _resolve_llm_provider(args.llm_provider)
    llm_model = _resolve_llm_model(args.llm_model, args.llm_provider)
    if not _llm_api_key_configured(args.llm_provider):
        log(
            f"ERROR: no API key configured for LLM provider {llm_provider!r}. "
            "Set keys in .env (see .env.sample)."
        )
        return []
    log(f"LLM provider={llm_provider} model={llm_model}")

    if args.llm_phase in ("a", "b"):
        log(f"=== Phase: +LLM (subset --llm-phase {args.llm_phase}) ===")
        targets = select_llm_targets_by_phase(
            baseline_results,
            args.llm_phase,
            fast_threshold=args.fast_threshold,
        )
        targets_path = args.output_dir / f"llm_targets_phase_{args.llm_phase}.json"
        targets_path.parent.mkdir(parents=True, exist_ok=True)
        targets_path.write_text(json.dumps({
            "llm_phase": args.llm_phase,
            "fast_threshold": args.fast_threshold,
            "target_count": len(targets),
            "targets": [
                {
                    "benchmark": t.benchmark,
                    "name": pathlib.Path(t.benchmark).name,
                    "expected": t.expected,
                    "baseline_result": t.result,
                    "baseline_wall_time": t.wall_time,
                    "baseline_category": t.category,
                }
                for t in targets
            ],
        }, indent=2) + "\n")
        log(f"  Target list saved to {targets_path}")
    else:
        # Legacy: competition medium/slow/timeout filter
        comp_by_path: dict[str, CompEntry] = {}
        matched = 0
        for br in baseline_results:
            entry = BenchEntry(path=br.benchmark, year=br.year, track=br.track, expected=br.expected)
            ce = match_entry_to_competition(entry, comp_map)
            if ce:
                comp_by_path[br.benchmark] = ce
                matched += 1

        targets = [r for r in baseline_results
                   if comp_by_path.get(r.benchmark)
                   and comp_by_path[r.benchmark].category in ("medium", "slow", "timeout")]

        fast_paths = {r.benchmark for r in baseline_results if r.category == "fast"}
        skipped_fast_baseline = [t for t in targets if t.benchmark in fast_paths]
        targets = [t for t in targets if t.benchmark not in fast_paths]
        if skipped_fast_baseline:
            targets = targets + skipped_fast_baseline

        log(f"=== Phase: +LLM ({len(targets)} benchmarks, competition filter) ===")
        log(f"  (matched {matched} of {len(baseline_results)} baseline results to competition data)")
        by_cat: dict[str, int] = {}
        for t in targets:
            ce = comp_by_path.get(t.benchmark)
            if ce:
                by_cat[ce.category] = by_cat.get(ce.category, 0) + 1
        log(f"  Competition classification: medium={by_cat.get('medium',0)}, slow={by_cat.get('slow',0)}, timeout={by_cat.get('timeout',0)}")

    if not targets:
        log("No benchmarks qualify for +LLM phase")
        return []

    pono_bin = _resolve_pono(args)
    sidecar_path = _resolve_sidecar(args)
    prompt_dir = _resolve_prompt_dir(args)

    run_id = args.run_id or time.strftime("%Y%m%d_%H%M%S")
    if args.llm_phase in ("a", "b") and not args.run_id:
        run_id = f"{run_id}_phase_{args.llm_phase}"
    archive_root = args.output_dir / "runs" / run_id
    manifest_path = archive_root / "run_manifest.json"
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_run_manifest(manifest_path, {
        "run_id": run_id,
        "phase": f"llm_{args.llm_phase}" if args.llm_phase in ("a", "b") else "llm",
        "llm_phase": args.llm_phase,
        "status": "running",
        "started_at": started_at,
        "parallel": args.parallel,
        "snapshot_max_clauses": args.snapshot_max_clauses,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_drain_sec": args.llm_drain_sec,
        "memory_limit_gb": args.memory_limit,
        "engine": args.engine,
        "bound": args.bound,
        "timeout": args.timeout,
        "target_count": len(targets),
        "archive_root": str(archive_root),
        "benchmarks": [],
    })
    log(f"LLM archive: {archive_root}")

    # Create temp dir for sidecar IPC files
    base_tmp = pathlib.Path(tempfile.mkdtemp(prefix="pono_bench_"))
    results: list[RunResult] = []
    done = 0

    # Build jobs
    jobs: list[dict] = []
    for br in targets:
        entry = BenchEntry(
            path=br.benchmark,
            year=br.year,
            track=br.track,
            expected=br.expected,
        )
        tmpdir = str(base_tmp / str(uuid.uuid4())[:8])
        pathlib.Path(tmpdir).mkdir(parents=True)
        slug = _bench_slug(entry)
        jobs.append(dict(
            entry=entry,
            pono_bin=pono_bin,
            engine=args.engine,
            bound=args.bound,
            timeout=args.timeout,
            accepted_budget=args.llm_accepted_budget,
            tmpdir=tmpdir,
            sidecar_path=str(sidecar_path),
            prompt_dir=str(prompt_dir),
            llm_max_requests=args.llm_max_requests,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_batch_wait_sec=300,
            llm_max_inflight=8,
            llm_parallel_samples=1,
            memory_limit=args.memory_limit,
            drain_sec=args.llm_drain_sec,
            snapshot_max_clauses=args.snapshot_max_clauses,
            archive_dir=str(archive_root / slug),
            archive_full_requests=args.archive_full_requests,
        ))

    log(f"Starting {args.parallel} workers (each with own sidecar) ...")
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = [ex.submit(_run_one_llm, j) for j in jobs]
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                results.append(r)
                log(f"  llm progress: {done}/{len(targets)}  result={r.result}  time={r.wall_time:.1f}s  match={r.match}")
            except Exception as exc:
                idx = futs.index(fut)
                j = jobs[idx] if idx >= 0 else None
                if j:
                    log(f"  ERROR: {j['entry'].path}: {type(exc).__name__}: {exc}")
                else:
                    log(f"  ERROR: {type(exc).__name__}: {exc}")

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_run_manifest(manifest_path, {
        "run_id": run_id,
        "phase": "llm",
        "status": "done",
        "started_at": started_at,
        "finished_at": finished_at,
        "parallel": args.parallel,
        "snapshot_max_clauses": args.snapshot_max_clauses,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_drain_sec": args.llm_drain_sec,
        "memory_limit_gb": args.memory_limit,
        "engine": args.engine,
        "bound": args.bound,
        "timeout": args.timeout,
        "target_count": len(targets),
        "completed_count": len(results),
        "archive_root": str(archive_root),
        "benchmarks": [_run_result_llm_summary(r) for r in results],
    })
    log(f"Run manifest: {manifest_path}")

    # Cleanup (per-job archives already copied)
    try:
        shutil.rmtree(base_tmp, ignore_errors=True)
    except Exception:
        pass

    return results


# ── Phase: report ────────────────────────────────────────────────────────


def save_results(results: list[RunResult], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow({field: getattr(r, field) for field in RESULT_FIELDS})


def load_results(path: pathlib.Path) -> list[RunResult]:
    results: list[RunResult] = []
    if not path.exists():
        return results
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            kwargs: dict = {
                "benchmark": row["benchmark"],
                "year": int(row["year"]),
                "track": row["track"],
                "expected": row["expected"],
                "mode": row["mode"],
                "result": row["result"],
                "wall_time": float(row["wall_time"]),
                "category": row["category"],
                "match": row["match"].lower() == "true",
            }
            for field_name in RESULT_FIELDS:
                if field_name in kwargs:
                    continue
                if field_name.startswith("llm_"):
                    kwargs[field_name] = int(row.get(field_name, 0) or 0)
            results.append(RunResult(**kwargs))
    return results


def _count(results: list[RunResult], **filters) -> int:
    cnt = 0
    for r in results:
        ok = True
        for k, v in filters.items():
            if getattr(r, k) != v:
                ok = False
                break
        if ok:
            cnt += 1
    return cnt


def _avg_time(results: list[RunResult]) -> float:
    times = [r.wall_time for r in results if r.result != "timeout"]
    return sum(times) / len(times) if times else 0


def save_classification(
    comp_map: dict[str, CompEntry],
    entries: list[BenchEntry],
    path: pathlib.Path,
) -> None:
    """Save competition classification to CSV for reference."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["benchmark_path", "year", "track", "expected",
                         "comp_result", "comp_time", "comp_category"])
        for e in entries:
            ce = match_entry_to_competition(e, comp_map)
            if ce:
                writer.writerow([e.path, e.year, e.track, e.expected,
                                ce.result, f"{ce.wall_time:.1f}", ce.category])
            else:
                writer.writerow([e.path, e.year, e.track, e.expected,
                                "no_data", "", ""])
    log(f"Classification saved to {path}")


def generate_markdown(
    baseline: list[RunResult],
    llm_results: list[RunResult],
    args: argparse.Namespace,
    output_path: pathlib.Path,
    comp_map: Optional[dict[str, CompEntry]] = None,
) -> None:
    """Generate a markdown report."""
    lines: list[str] = []
    a = lines.append

    a("# Pono + LLM Benchmark Report")
    a("")
    a(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    a(f"**Engine:** `{args.engine}` | **Bound:** `{args.bound}` | **Timeout:** `{args.timeout}s`")
    a(f"**Years:** {args.hwmcc_years} | **Parallel workers:** {args.parallel}")
    a("")

    # ── overall stats ──
    a("## Overall Statistics")
    a("")
    total_baseline = len(baseline)
    solved_baseline = _count(baseline, match=True)
    fast_n = _count(baseline, category="fast")
    medium_n = _count(baseline, category="medium")
    slow_n = _count(baseline, category="slow")
    timeout_n = _count(baseline, category="timeout")
    error_n = _count(baseline, result="error")

    a(f"| Metric | Baseline (our machine) | +LLM |")
    a(f"|--------|------------------------|------|")
    a(f"| Total benchmarks | {total_baseline} | {len(llm_results)} |")
    a(f"| Solved (match expected) | {solved_baseline} | {_count(llm_results, match=True)} |")
    a(f"| Avg time (non-timeout) | {_avg_time(baseline):.1f}s | {_avg_time(llm_results):.1f}s |")
    a("")

    # ── classification ──
    a("## Classification (Baseline - Our Machine)")
    a("")
    a(f"| Category | Count | Description |")
    a(f"|----------|-------|-------------|")
    a(f"| fast (<30s) | {fast_n} | Skipped for +LLM |")
    a(f"| medium (30-500s) | {medium_n} | Ran +LLM |")
    a(f"| slow (>500s) | {slow_n} | Ran +LLM |")
    a(f"| timeout | {timeout_n} | Ran +LLM |")
    if error_n:
        a(f"| error | {error_n} | Skipped |")
    a("")

    # ── Competition classification (used to filter +LLM) ──
    if comp_map:
        a("## +LLM Selection (based on Competition Results)")
        a("")
        a("Benchmarks were selected for +LLM based on their **competition classification** (HWMCC 2020/2024/2025), not our baseline timing.")
        a("")
        by_cat_comp: dict[int, dict[str, int]] = {}
        for r in baseline:
            entry = BenchEntry(path=r.benchmark, year=r.year, track=r.track, expected=r.expected)
            ce = match_entry_to_competition(entry, comp_map)
            if ce:
                d = by_cat_comp.setdefault(r.year, {})
                d[ce.category] = d.get(ce.category, 0) + 1
        for y in sorted(by_cat_comp):
            d = by_cat_comp[y]
            total_y = sum(d.values())
            qual = sum(v for k, v in d.items() if k in ("medium", "slow", "timeout"))
            a(f"- **{y}**: {total_y} benchmarks → {qual} qualify for +LLM (fast={d.get('fast',0)}, medium={d.get('medium',0)}, slow={d.get('slow',0)}, timeout={d.get('timeout',0)})")
        a("")

    # ── per-year breakdown ──
    years = sorted(set(r.year for r in baseline))
    a("## Per-Year Breakdown (Our Machine)")
    a("")
    a(f"| Year | Total | Solved | Fast | Medium | Slow | Timeout |")
    a(f"|------|-------|--------|------|--------|------|---------|")
    for y in years:
        yr = [r for r in baseline if r.year == y]
        a(f"| {y} | {len(yr)} | {_count(yr, match=True)} | {_count(yr, category='fast')} | {_count(yr, category='medium')} | {_count(yr, category='slow')} | {_count(yr, category='timeout')} |")
    a("")

    # ── per-track breakdown ──
    a("## Per-Track Breakdown (Our Machine)")
    a("")
    a(f"| Track | Total | Solved | Fast | Medium | Slow | Timeout |")
    a(f"|-------|-------|--------|------|--------|------|---------|")
    for tr in ["bv", "array"]:
        trr = [r for r in baseline if r.track == tr]
        if trr:
            a(f"| {tr} | {len(trr)} | {_count(trr, match=True)} | {_count(trr, category='fast')} | {_count(trr, category='medium')} | {_count(trr, category='slow')} | {_count(trr, category='timeout')} |")
    a("")

    # ── +LLM comparison (with competition data) ──
    if llm_results:
        a("## Baseline vs +LLM Comparison")
        a("")
        a("Benchmarks that ran in both baseline and +LLM mode:")
        a("")
        a("| Benchmark | Year | Track | Expected | BL Result | BL Time | LLM Result | LLM Time | Delta | Comp Cat | LLM Acc | LLM Rej |")
        a("|-----------|------|-------|----------|-----------|---------|------------|----------|-------|----------|---------|---------|")

        bl_map = {r.benchmark: r for r in baseline}
        for lr in sorted(llm_results, key=lambda x: x.wall_time, reverse=True):
            br = bl_map.get(lr.benchmark)
            if br:
                if lr.result != "timeout" and br.result != "timeout":
                    delta_str = f"{lr.wall_time - br.wall_time:+.1f}s"
                else:
                    delta_str = "N/A"
                # Get competition category
                comp_cat = ""
                if comp_map:
                    entry = BenchEntry(path=lr.benchmark, year=lr.year, track=lr.track, expected=lr.expected)
                    ce = match_entry_to_competition(entry, comp_map)
                    if ce:
                        comp_cat = ce.category
                a(f"| {pathlib.Path(lr.benchmark).name} | {lr.year} | {lr.track} | {lr.expected} | {br.result} | {br.wall_time:.1f}s | {lr.result} | {lr.wall_time:.1f}s | {delta_str} | {comp_cat} | {lr.llm_accepted} | {lr.llm_rejected} |")

        # Changed results
        improved = []
        for lr in llm_results:
            br = bl_map.get(lr.benchmark)
            if br and br.match is False and lr.match is True:
                improved.append((br, lr))
        if improved:
            a("")
            a("### Benchmarks where +LLM flipped result to correct")
            a("")
            for br, lr in improved:
                a(f"- `{pathlib.Path(lr.benchmark).name}`: {br.result} -> {lr.result} (expected {lr.expected})")
            a("")

    # ── slow/timeout benchmarks ──
    slow_timeout = [r for r in baseline if r.category in ("slow", "timeout")]
    if slow_timeout:
        a("## Hard Benchmarks (Baseline: slow + timeout)")
        a("")
        for r in sorted(slow_timeout, key=lambda x: x.wall_time, reverse=True):
            a(f"- `{pathlib.Path(r.benchmark).name}` [{r.year}/{r.track}] expected={r.expected} result={r.result} time={r.wall_time:.1f}s")
        a("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")
    log(f"Report written to {output_path}")


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_pono(args: argparse.Namespace) -> pathlib.Path:
    if args.pono_bin:
        p = args.pono_bin
    else:
        p = repo_root() / "build" / "pono"
    if not p.is_file():
        raise FileNotFoundError(f"pono binary not found: {p}")
    return p


def _resolve_sidecar(args: argparse.Namespace) -> pathlib.Path:
    if args.sidecar_path:
        p = args.sidecar_path
    else:
        p = repo_root() / "llm_worker" / "sidecar.py"
    if not p.is_file():
        raise FileNotFoundError(f"sidecar.py not found: {p}")
    return p


def _resolve_prompt_dir(args: argparse.Namespace) -> pathlib.Path:
    if args.prompt_dir:
        p = args.prompt_dir
    else:
        p = repo_root() / "llm_worker" / "prompts"
    if not p.is_dir():
        raise FileNotFoundError(f"prompt dir not found: {p}")
    return p


# ── Phase: find-solvable ──────────────────────────────────────────────────


def run_find_solvable(args: argparse.Namespace) -> list[dict]:
    """Find IC3IA-solvable benchmarks with refinement cycles, excluding too-fast cases."""
    log("=== Phase: find-solvable ===")
    years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
    comp_map = load_competition_classification(args.hwmcc_dir)
    entries = collect_benchmarks(args.hwmcc_dir, years)
    if args.limit > 0:
        entries = entries[:args.limit]
    if args.find_max > 0:
        entries = entries[:args.find_max]

    baseline_by_path: dict[str, RunResult] = {}
    baseline_path = args.output_dir / "results_baseline.csv"
    if baseline_path.exists():
        for row in load_results(baseline_path):
            baseline_by_path[row.benchmark] = row
        log(f"  Loaded baseline CSV for pre-filter: {len(baseline_by_path)} rows")

    log(
        f"Scanning {len(entries)} benchmarks "
        f"(fast_threshold={args.fast_threshold}s, need blocking_phases>0)..."
    )
    pono_bin = str(_resolve_pono(args))
    results: list[dict] = []
    skipped_hard = 0
    skipped_fast = 0

    for e in entries:
        name = pathlib.Path(e.path).name
        ce = match_entry_to_competition(e, comp_map)
        comp_note = (
            f"comp: {ce.result} {ce.wall_time:.0f}s {ce.category}"
            if ce else "comp: n/a"
        )

        br = baseline_by_path.get(e.path)
        if br and br.result in ("timeout", "memout", "error"):
            skipped_hard += 1
            continue
        if br and br.result in ("sat", "unsat") and br.wall_time < args.fast_threshold:
            skipped_fast += 1
            continue

        log(f"  testing: {name} ({comp_note})")
        cmd = [pono_bin, "-v", "2", "-e", args.engine, "-k", str(args.bound), e.path]
        probe_timeout = min(args.timeout, 300)
        if br and br.result in ("sat", "unsat"):
            probe_timeout = min(args.timeout, max(probe_timeout, int(br.wall_time) + 30))
        try:
            t0 = time.time()
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=probe_timeout,
            )
            wall_time = time.time() - t0
            stdout_text = _parse_pono_stdout(proc.stdout, proc.returncode)
            stderr_text = proc.stderr or ""
            if stdout_text in ("sat", "unsat"):
                blocking_phases = len([l for l in stderr_text.splitlines()
                                      if "Blocking phase at frame" in l])
                if blocking_phases <= 0:
                    log(f"    ✅ solved but 0 blocking phases (too simple)")
                elif wall_time < args.fast_threshold:
                    log(f"    ✅ solved in {wall_time:.1f}s but too fast (<{args.fast_threshold}s)")
                else:
                    results.append({
                        "name": name,
                        "path": e.path,
                        "expected": e.expected,
                        "blocking_phases": blocking_phases,
                        "wall_time": round(wall_time, 2),
                        "comp_category": ce.category if ce else "",
                    })
                    log(f"    ✅ solved in {wall_time:.1f}s, {blocking_phases} blocking phases")
            else:
                log(f"    ❌ result={stdout_text}")
        except subprocess.TimeoutExpired:
            log(f"    ⏱ timeout ({probe_timeout}s)")
        except Exception as exc:
            log(f"    ❌ error: {exc}")

    if skipped_hard or skipped_fast:
        log(
            f"  Pre-skipped from baseline: {skipped_hard} hard "
            f"(timeout/memout/error), {skipped_fast} fast (<{args.fast_threshold}s)"
        )

    if results:
        results.sort(key=lambda r: r["blocking_phases"], reverse=True)
        log(f"\nFound {len(results)} candidates (non-fast, blocking_phases>0):")
        for r in results[:15]:
            log(
                f"  {r['name']:55s} {r['expected']:5s} "
                f"{r['blocking_phases']:4d} blocking  {r['wall_time']:6.1f}s  "
                f"({r['comp_category'] or 'n/a'})"
            )

    return results


# ── main ─────────────────────────────────────────────────────────────────


def main() -> int:
    args = parse_args()
    env_path = _load_repo_env()
    if env_path:
        log(f"Loaded .env from {env_path}")

    if args.all:
        args.phase = "all"

    phases = ["test", "download", "baseline", "llm", "report"]
    if args.find_solvable:
        todo = ["find-solvable"]
    elif args.phase == "all":
        todo = phases[:]
    elif args.phase == "hwmcc":
        todo = ["download", "baseline", "llm", "report"]
    elif args.phase == "find-solvable" or args.find_solvable:
        todo = ["find-solvable"]
    else:
        todo = [args.phase]

    if args.dry_run:
        log(f"Dry run. Phases: {todo}")
        return 0

    # ── phase: baseline-patch ──
    if "baseline-patch" in todo:
        years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
        entries = collect_benchmarks(args.hwmcc_dir, years)
        if args.limit > 0:
            entries = entries[:args.limit]
        log_path = args.baseline_log or (args.output_dir / "nohup.log")
        if not log_path.exists():
            log(f"Baseline log not found: {log_path}")
            return 1
        args.output_dir.mkdir(parents=True, exist_ok=True)
        patch_results = run_phase_baseline_patch(args, entries, log_path)
        partial_path = args.output_dir / "results_baseline_partial.csv"
        save_results(patch_results, partial_path)
        logged = parse_baseline_nohup_log(log_path)
        pending = len(entries) - len(logged)
        manifest = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "baseline_log": str(log_path),
            "logged_completed": len(logged),
            "patched_rows": len(patch_results),
            "pending_benchmarks": max(pending, 0),
            "total_benchmarks": len(entries),
        }
        manifest_path = args.output_dir / "baseline_patch_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        log(f"Partial results saved to {partial_path}")
        log(f"Manifest saved to {manifest_path} (pending={pending})")
        return 0

    # ── phase: find-solvable ──
    if "find-solvable" in todo:
        run_phase_download(args)  # need CSVs for competition data
        candidates = run_find_solvable(args)
        candidates_path = args.output_dir / "candidates.json"
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_path.write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "find_max": args.find_max,
            "hwmcc_years": args.hwmcc_years,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }, indent=2) + "\n")
        log(f"Candidates saved to {candidates_path}")
        return 0

    # ── phase: test ──
    if "test" in todo:
        ok = run_phase_test(args)
        if not ok:
            return 1

    # ── phase: download ──
    if "download" in todo:
        if not run_phase_download(args):
            return 1

    # ── collect benchmarks (needed by baseline/llm/report) ──
    entries: list[BenchEntry] = []
    if any(p in todo for p in ["baseline", "llm", "report"]):
        years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
        entries = collect_benchmarks(args.hwmcc_dir, years)
        if args.limit > 0:
            entries = entries[:args.limit]
        if not entries:
            log("No benchmarks with known answers found. Did you run --phase download first?")
            return 1

    baseline_results: list[RunResult] = []
    llm_results: list[RunResult] = []
    comp_map: dict[str, CompEntry] = {}

    # ── load competition classification (needed for llm filtering + report) ──
    if any(p in todo for p in ["llm", "report"]) and not args.no_llm:
        comp_map = load_competition_classification(args.hwmcc_dir)
        log(f"Loaded competition classification: {len(comp_map)} pono entries")

    # ── phase: baseline ──
    if "baseline" in todo:
        partial_results: list[RunResult] = []
        entries_to_run = entries
        if args.skip_partial:
            partial_path = args.partial_csv or (args.output_dir / "results_baseline_partial.csv")
            if partial_path.exists():
                partial_results = load_results(partial_path)
                skip_paths = {r.benchmark for r in partial_results}
                entries_to_run = [e for e in entries if e.path not in skip_paths]
                log(
                    f"Resuming baseline: skipping {len(partial_results)} from {partial_path}, "
                    f"{len(entries_to_run)} remaining"
                )
            else:
                log(f"--skip-partial set but {partial_path} not found; running all benchmarks")

        new_results = run_phase_baseline(
            args, entries_to_run, total_count=len(entries),
        )
        if partial_results:
            baseline_results = merge_baseline_results(entries, partial_results, new_results)
        else:
            baseline_results = new_results
        save_results(baseline_results, args.output_dir / "results_baseline.csv")
        log(f"Baseline results saved to {args.output_dir / 'results_baseline.csv'}")

    # ── phase: llm ──
    if "llm" in todo:
        if not baseline_results:
            baseline_results = load_results(args.output_dir / "results_baseline.csv")
        if args.no_llm:
            log("--no-llm flag set, skipping +LLM phase")
        else:
            llm_results = run_phase_llm(args, baseline_results, comp_map)
            if llm_results:
                llm_csv = llm_results_csv_path(args)
                save_results(llm_results, llm_csv)
                log(f"+LLM results saved to {llm_csv}")

    # ── phase: report ──
    if "report" in todo:
        if not baseline_results:
            baseline_results = load_results(args.output_dir / "results_baseline.csv")
        if not llm_results:
            llm_results = load_results(args.output_dir / "results_llm.csv")
        if not comp_map:
            comp_map = load_competition_classification(args.hwmcc_dir)
        # Save classification for reference
        save_classification(comp_map, entries, args.output_dir / "classification.csv")
        generate_markdown(baseline_results, llm_results, args,
                          args.output_dir / "report.md", comp_map=comp_map)

    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
