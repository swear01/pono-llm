#!/usr/bin/env python3
"""
Unified benchmark runner for pono + LLM evaluation.

Phases:
  test     - Run built-in tests (make check + tests/python + schema + sidecar)
  download - Download HWMCC benchmarks (2020/2024/2025)
  baseline - Run baseline pono on all filtered benchmarks
  llm      - Run +LLM pono on interesting (medium/slow/timeout) benchmarks
  report   - Generate markdown report from CSV results
  hwmcc    - download + baseline + llm + report (full pipeline)
  all      - test + download + baseline + llm + report

Usage:
  python3 scripts/run_benchmarks.py --all --hwmcc-dir ~/hwmcc_benchmarks --parallel 4
  python3 scripts/run_benchmarks.py --phase test
  python3 scripts/run_benchmarks.py --phase download --hwmcc-dir ~/hwmcc_benchmarks
  python3 scripts/run_benchmarks.py --phase hwmcc --hwmcc-dir ~/hwmcc_benchmarks --parallel 8
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


RESULT_FIELDS = [f.name for f in fields(RunResult)]


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
        choices=["test", "download", "baseline", "llm", "report", "hwmcc", "all"],
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
        default=4,
        help="Max parallel workers",
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
        "--llm-model",
        default="deepseek-v4-pro",
        help="LLM model name (passed to sidecar)",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Even if baseline is medium/slow/timeout, skip +llm phase",
    )
    p.add_argument(
        "--memory-limit",
        type=float,
        default=40.0,
        help="Memory limit per benchmark in GB (soft, monitor checks every 5s)",
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
        default=30,
        help="Max benchmarks to test in find-solvable phase",
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

    schema_test = root / "llm_worker" / "tests" / "test_ic3_frame_schema.py"
    if schema_test.exists():
        log("Running llm_worker/tests/test_ic3_frame_schema.py ...")
        r = subprocess.run(
            [sys.executable, str(schema_test)],
            capture_output=True, text=True, timeout=60,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("test_ic3_frame_schema.py FAILED:")
            log(r.stdout[-1000:])
            log(r.stderr[-1000:])
            ok = False
        else:
            log("test_ic3_frame_schema.py PASSED")
    else:
        log("test_ic3_frame_schema.py not found, skipping")

    thinking_test = root / "llm_worker" / "tests" / "test_deepseek_thinking.py"
    if thinking_test.exists():
        log("Running llm_worker/tests/test_deepseek_thinking.py ...")
        r = subprocess.run(
            [sys.executable, str(thinking_test)],
            capture_output=True, text=True, timeout=60,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("test_deepseek_thinking.py FAILED:")
            log(r.stdout[-1000:])
            log(r.stderr[-1000:])
            ok = False
        else:
            log("test_deepseek_thinking.py PASSED")
    else:
        log("test_deepseek_thinking.py not found, skipping")

    prompt_fmt_test = root / "llm_worker" / "tests" / "test_prompt_format.py"
    if prompt_fmt_test.exists():
        log("Running llm_worker/tests/test_prompt_format.py ...")
        r = subprocess.run(
            [sys.executable, str(prompt_fmt_test)],
            capture_output=True, text=True, timeout=60,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("test_prompt_format.py FAILED:")
            log(r.stdout[-1000:])
            log(r.stderr[-1000:])
            ok = False
        else:
            log("test_prompt_format.py PASSED")
    else:
        log("test_prompt_format.py not found, skipping")

    concurrency_test = root / "llm_worker" / "tests" / "test_sidecar_concurrency.py"
    if concurrency_test.exists():
        log("Running llm_worker/tests/test_sidecar_concurrency.py ...")
        r = subprocess.run(
            [sys.executable, str(concurrency_test)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(root),
        )
        if r.returncode != 0:
            log("test_sidecar_concurrency.py FAILED:")
            log(r.stdout[-1000:])
            log(r.stderr[-1000:])
            ok = False
        else:
            log("test_sidecar_concurrency.py PASSED")
    else:
        log("test_sidecar_concurrency.py not found, skipping")

    sidecar_test = root / "test_sidecar.py"
    if sidecar_test.exists():
        if not os.environ.get("DEEPSEEK_API_KEY"):
            log("SKIP test_sidecar.py --with-llm (DEEPSEEK_API_KEY not set)")
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


def _parse_llm_stats(stderr: str) -> tuple[int, int, int]:
    """Parse LLM accept/reject/error counts from pono stderr.
    Expects a line like: LLM_STATS accepted=5 rejected=10 errors=3 ..."""
    accepted = rejected = errors = 0
    for line in stderr.splitlines():
        if not line.strip().startswith("LLM_STATS"):
            continue
        for part in line.split():
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            try:
                int_val = int(val)
            except ValueError:
                continue
            if key == "accepted":
                accepted = int_val
            elif key == "rejected":
                rejected = int_val
            elif key == "errors":
                errors = int_val
    return accepted, rejected, errors


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
    llm_parallel_samples: int = 3,
    llm_reasoning_effort: str = "none",
) -> RunResult:
    """Run pono on a single benchmark. Returns RunResult."""
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
            "--llm-req-path", req_path,
            "--llm-resp-path", resp_path,
            "--llm-log", log_path,
        ])
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
    except Exception as exc:
        wall = time.time() - t0
        return RunResult(
            benchmark=entry.path, year=entry.year, track=entry.track,
            expected=entry.expected, mode=mode,
            result="error", wall_time=wall, category="error", match=False,
        )

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
            stdout_text = (stdout or "").strip().lower()
            if stdout_text in ("sat", "unsat"):
                result = stdout_text
            elif proc.returncode == 0:
                result = "unknown"
            else:
                result = "error"

    llm_acc = llm_rej = llm_err = 0
    if mode == "llm":
        try:
            llm_acc, llm_rej, llm_err = _parse_llm_stats(stderr)
        except Exception:
            pass

    # classification
    if result in ("timeout", "error"):
        category = result
    elif wall < 30:
        category = "fast"
    elif wall < 500:
        category = "medium"
    else:
        category = "slow"

    match = (result == entry.expected)

    return RunResult(
        benchmark=entry.path,
        year=entry.year,
        track=entry.track,
        expected=entry.expected,
        mode=mode,
        result=result,
        wall_time=wall,
        category=category,
        match=match,
        llm_accepted=llm_acc,
        llm_rejected=llm_rej,
        llm_errors=llm_err,
    )


def _run_one_baseline(job: tuple[BenchEntry, pathlib.Path, str, int, int]) -> RunResult:
    entry, pono_bin, engine, bound, timeout = job
    return run_pono(entry, pono_bin, engine, bound, timeout, "baseline")


def run_phase_baseline(args: argparse.Namespace, entries: list[BenchEntry]) -> list[RunResult]:
    """Run baseline pono on all entries in parallel using subprocess workers."""
    log(f"=== Phase: baseline ({len(entries)} benchmarks) ===")
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
                r = run_pono(entry, pathlib.Path(pono_bin), args.engine,
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
            if done % 10 == 0 or done == len(entries) or done <= 3:
                log(f"  baseline progress: {done}/{len(entries)}")

    log(f"Starting {args.parallel} workers ...")
    threads = [Thread(target=_worker, args=(i,), daemon=True)
               for i in range(args.parallel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


# ── Phase: +llm ──────────────────────────────────────────────────────────


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
    llm_model = job_data.get("llm_model", "deepseek-v4-pro")

    # Start sidecar
    env = os.environ.copy()
    sidecar_proc = subprocess.Popen(
        [
            sys.executable, sidecar_path,
            "--req-path", req_path,
            "--resp-path", resp_path,
            "--log-path", log_path,
            "--prompt-dir", prompt_dir,
            "--poll-interval", "0.5",
            "--max-requests", str(job_data.get("llm_max_requests", 50)),
            "--max-inflight-requests", str(job_data.get("llm_max_inflight", 8)),
            "--snapshot-max-clauses", str(job_data.get("snapshot_max_clauses", 50)),
            "--model", llm_model,
        ],
        stdout=subprocess.DEVNULL,
        stderr=open(sidecar_stderr, "w"),
        env=env,
    )

    time.sleep(1)

    result = run_pono(
        entry, pono_bin, engine, bound, timeout,
        mode="llm",
        req_path=req_path, resp_path=resp_path, log_path=log_path,
        accepted_budget=accepted_budget,
        memory_limit_gb=job_data.get("memory_limit", 40.0),
        llm_parallel_samples=job_data.get("llm_parallel_samples", 3),
        llm_reasoning_effort=job_data.get("llm_reasoning_effort", "none"),
    )

    # Drain sidecar before stopping
    drain_sec = job_data.get("drain_sec", 120)
    deadline = time.time() + drain_sec
    while time.time() < deadline:
        req_n = 0
        log_n = 0
        if os.path.isfile(req_path):
            with open(req_path) as f:
                req_n = sum(1 for _ in f)
        if os.path.isfile(log_path):
            with open(log_path) as f:
                log_n = sum(1 for _ in f)
        if req_n > 0 and log_n >= req_n:
            break
        time.sleep(2)

    # Stop sidecar
    try:
        sidecar_proc.terminate()
        sidecar_proc.wait(timeout=10)
    except Exception:
        sidecar_proc.kill()

    return result


def run_phase_llm(
    args: argparse.Namespace,
    baseline_results: list[RunResult],
    comp_map: dict[str, CompEntry],
) -> list[RunResult]:
    """Run +LLM on benchmarks classified as medium/slow/timeout in competition results."""
    # Build a lookup: (year, bench_abs_path) -> CompEntry
    comp_by_path: dict[str, CompEntry] = {}
    matched = 0
    for br in baseline_results:
        entry = BenchEntry(path=br.benchmark, year=br.year, track=br.track, expected=br.expected)
        ce = match_entry_to_competition(entry, comp_map)
        if ce:
            comp_by_path[br.benchmark] = ce
            matched += 1

    # Filter: only run +LLM on benchmarks that were medium/slow/timeout in competition
    targets = [r for r in baseline_results
               if comp_by_path.get(r.benchmark) and comp_by_path[r.benchmark].category in ("medium", "slow", "timeout")]

    # Also skip benchmarks that timed out in our baseline (our machine might be slower)
    fast_in_bl = [r for r in baseline_results if r.category == "fast"]
    fast_paths = {r.benchmark for r in fast_in_bl}
    skipped_fast_baseline = [t for t in targets if t.benchmark in fast_paths]
    targets = [t for t in targets if t.benchmark not in fast_paths]

    if skipped_fast_baseline:
        log(f"Note: {len(skipped_fast_baseline)} benchmarks were fast in our baseline but medium/slow/timeout in competition. Including them in +LLM anyway?")
        # Actually include them back - they're fast on our machine which is fine
        targets = targets + skipped_fast_baseline

    if not targets:
        log("No benchmarks qualify for +LLM phase")
        return []

    log(f"=== Phase: +LLM ({len(targets)} benchmarks, classified by competition results) ===")
    log(f"  (matched {matched} of {len(baseline_results)} baseline results to competition data)")

    # Show breakdown
    by_cat: dict[str, int] = {}
    for t in targets:
        ce = comp_by_path.get(t.benchmark)
        if ce:
            by_cat[ce.category] = by_cat.get(ce.category, 0) + 1
    log(f"  Competition classification: medium={by_cat.get('medium',0)}, slow={by_cat.get('slow',0)}, timeout={by_cat.get('timeout',0)}")
    pono_bin = _resolve_pono(args)
    sidecar_path = _resolve_sidecar(args)
    prompt_dir = _resolve_prompt_dir(args)

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
            llm_model=args.llm_model,
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

    # Cleanup
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
            results.append(RunResult(
                benchmark=row["benchmark"],
                year=int(row["year"]),
                track=row["track"],
                expected=row["expected"],
                mode=row["mode"],
                result=row["result"],
                wall_time=float(row["wall_time"]),
                category=row["category"],
                match=row["match"].lower() == "true",
                llm_accepted=int(row.get("llm_accepted", 0)),
                llm_rejected=int(row.get("llm_rejected", 0)),
                llm_errors=int(row.get("llm_errors", 0)),
            ))
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
    """Find IC3IA-solvable non-fast benchmarks that have refinement cycles."""
    log("=== Phase: find-solvable ===")
    years = [int(y.strip()) for y in args.hwmcc_years.split(",")]
    comp_map = load_competition_classification(args.hwmcc_dir)
    entries = collect_benchmarks(args.hwmcc_dir, years)

    # Filter: pono solved in competition, medium or slow (not fast)
    targets = []
    for e in entries:
        ce = match_entry_to_competition(e, comp_map)
        if not ce:
            continue
        if ce.category in ("medium",):
            targets.append((e, ce))
    targets = targets[:args.find_max]

    log(f"Testing {len(targets)} candidates (medium category in competition)...")
    pono_bin = str(_resolve_pono(args))
    results = []

    for e, ce in targets:
        name = pathlib.Path(e.path).name
        log(f"  testing: {name} (comp: {ce.result} {ce.wall_time:.0f}s {ce.category})")
        cmd = [pono_bin, "-v", "2", "-e", args.engine, "-k", str(args.bound), e.path]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=min(args.timeout, 300),
            )
            stdout_text = (proc.stdout or "").strip().lower()
            stderr_text = proc.stderr or ""
            if stdout_text in ("sat", "unsat"):
                blocking_phases = len([l for l in stderr_text.splitlines()
                                      if "Blocking phase at frame" in l])
                if blocking_phases > 0:
                    results.append({
                        "name": name,
                        "path": e.path,
                        "expected": e.expected,
                        "blocking_phases": blocking_phases,
                        "comp_category": ce.category,
                    })
                    log(f"    ✅ solved, {blocking_phases} blocking phases")
                else:
                    log(f"    ✅ solved but 0 blocking phases (too simple)")
            else:
                log(f"    ❌ result={stdout_text[:20]}")
        except subprocess.TimeoutExpired:
            log(f"    ⏱ timeout")
        except Exception as exc:
            log(f"    ❌ error: {exc}")

    if results:
        results.sort(key=lambda r: r["blocking_phases"], reverse=True)
        log(f"\nFound {len(results)} solvable benchmarks with refinement cycles:")
        for r in results[:15]:
            log(f"  {r['name']:55s} {r['expected']:5s} {r['blocking_phases']:4d} blocking phases  ({r['comp_category']})")

    return results


# ── main ─────────────────────────────────────────────────────────────────


def main() -> int:
    args = parse_args()

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

    # ── phase: find-solvable ──
    if "find-solvable" in todo:
        run_phase_download(args)  # need CSVs for competition data
        run_find_solvable(args)
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
        baseline_results = run_phase_baseline(args, entries)
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
                save_results(llm_results, args.output_dir / "results_llm.csv")
                log(f"+LLM results saved to {args.output_dir / 'results_llm.csv'}")

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
