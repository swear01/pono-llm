#!/usr/bin/env python3
"""
HWMCC benchmark comparison: IC3IA baseline vs LLM-guided.

Runs a set of btor2 benchmarks with and without Stage 0 LLM guidance,
measures CEGAR rounds and proof time, and prints a comparison table.

Usage:
    python scripts/hwmcc_llm_benchmark.py [--dry-run] [--timeout 120]

Requires: DEEPSEEK_API_KEY in .env or environment, pono built at build/pono.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
PONO_BIN = ROOT / "build" / "pono"
LLM_WORKER = ROOT / "llm_worker"
SIDECAR_PY = LLM_WORKER / "sidecar.py"
DOT_ENV = ROOT / ".env"

BENCHMARKS = {
    "ab_sync": ROOT / "tests" / "benchmarks" / "ab_sync.btor2",
    "stack-p2": Path("/home/swear01/hwmcc_benchmarks/2024/btor2/2020/mann/stack-p2.btor2"),
    "rast-p10": Path("/home/swear01/hwmcc_benchmarks/2024/btor2/2020/mann/rast-p10.btor2"),
    "h_Arbiter": Path("/home/swear01/hwmcc_benchmarks/2024/btor2/2019/goel/opensource/h_Arbiter/h_Arbiter.btor2"),
}


def _load_dot_env() -> None:
    if not DOT_ENV.exists():
        return
    for line in DOT_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val


_load_dot_env()


@dataclass
class RunResult:
    name: str
    mode: str          # "baseline" or "guided"
    result: str        # "unsat" / "sat" / "timeout" / "error"
    elapsed_s: float = 0.0
    cegar_rounds: int = 0
    stage0_injected: int = 0
    stage0_candidates: int = 0
    llm_suggestions: list = field(default_factory=list)
    injected_predicates: list = field(default_factory=list)
    rejected_predicates: list = field(default_factory=list)
    stderr_snippet: str = ""


def _count_cegar(stderr: str) -> int:
    return stderr.count("new predicates added by refinement")


def _extract_injected_rejected(stderr: str) -> tuple[list, list]:
    """Parse pono stderr for injected/rejected LLM predicate log lines."""
    injected, rejected = [], []
    for line in stderr.splitlines():
        if "LLM invariant candidate injected" in line:
            injected.append(line.strip())
        elif "LLM refine_predicate:" in line or "LLM response schema fail" in line:
            rejected.append(line.strip())
    return injected, rejected


def _extract_stage0(stderr: str) -> tuple[int, int]:
    """Return (injected, total_candidates) from 'Stage 0 injected X/Y' line."""
    for line in stderr.splitlines():
        if "Stage 0 injected" in line:
            try:
                # "IC3: Stage 0 injected 1/3 candidates"
                parts = line.split("injected")[1].split()[0].split("/")
                return int(parts[0]), int(parts[1])
            except (IndexError, ValueError):
                pass
    return 0, 0


def run_baseline(name: str, btor2: Path, timeout_s: int, k: int = 100) -> RunResult:
    """Run IC3IA without LLM."""
    t0 = time.monotonic()
    stdout_data, stderr_data, result = "", "", "error"
    try:
        proc = subprocess.run(
            [str(PONO_BIN), "-e", "ic3ia", "-v", "2", "-k", str(k), str(btor2)],
            capture_output=True, text=True, timeout=timeout_s,
        )
        stdout_data, stderr_data = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        # Partial output is in the exception
        stdout_data = (e.stdout or b"")
        stderr_data = (e.stderr or b"")
        if isinstance(stdout_data, bytes):
            stdout_data = stdout_data.decode(errors="replace")
        if isinstance(stderr_data, bytes):
            stderr_data = stderr_data.decode(errors="replace")
        result = "timeout"

    elapsed = time.monotonic() - t0
    combined = stdout_data + stderr_data
    if result != "timeout":
        if "unsat" in combined:
            result = "unsat"
        elif "sat" in combined:
            result = "sat"
    return RunResult(
        name=name,
        mode="baseline",
        result=result,
        elapsed_s=elapsed,
        cegar_rounds=_count_cegar(stderr_data),
        stderr_snippet=stderr_data[-600:],
    )


def run_guided(name: str, btor2: Path, timeout_s: int,
               tmp_dir: Path, k: int = 100) -> RunResult:
    """Run IC3IA with Stage 0 LLM guidance via sidecar."""
    req = tmp_dir / f"{name}_req.jsonl"
    resp = tmp_dir / f"{name}_resp.jsonl"
    log = tmp_dir / f"{name}_sidecar.log"

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return RunResult(name=name, mode="guided", result="skip-no-key")

    sidecar = subprocess.Popen(
        [
            sys.executable, str(SIDECAR_PY),
            "--req-path", str(req),
            "--resp-path", str(resp),
            "--log-path", str(log),
            "--provider", "deepseek",
            "--model", "deepseek-v4-pro",
            "--max-requests", "2",
            "--poll-interval", "0.5",
        ],
        cwd=str(LLM_WORKER),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    pono = subprocess.Popen(
        [
            str(PONO_BIN), "-e", "ic3ia", "-v", "2",
            "--llm-gen-mode", "semantic",
            "--llm-req-path", str(req),
            "--llm-resp-path", str(resp),
            "-k", str(k),
            str(btor2),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Drain stderr in background thread to avoid pipe buffering
    stderr_buf = io.StringIO()
    lock = threading.Lock()

    def _drain():
        for line in pono.stderr:
            with lock:
                stderr_buf.write(line)

    drain_t = threading.Thread(target=_drain, daemon=True)
    drain_t.start()

    t0 = time.monotonic()
    result_str = "timeout"
    try:
        pono.wait(timeout=timeout_s)
        stdout_data = pono.stdout.read() if pono.stdout else ""
        drain_t.join(timeout=3)
        with lock:
            stderr_data = stderr_buf.getvalue()

        combined = stdout_data + stderr_data
        if "unsat" in combined:
            result_str = "unsat"
        elif "sat" in combined:
            result_str = "sat"
        else:
            result_str = "error"
    except subprocess.TimeoutExpired:
        pono.kill()
        pono.wait(timeout=5)
        drain_t.join(timeout=3)
        with lock:
            stderr_data = stderr_buf.getvalue()
        result_str = "timeout"
    finally:
        sidecar.kill()
        sidecar.wait(timeout=5)

    elapsed = time.monotonic() - t0
    injected, total = _extract_stage0(stderr_data)
    inj_lines, rej_lines = _extract_injected_rejected(stderr_data)

    # Parse what LLM suggested from resp.jsonl
    suggestions = []
    if resp.exists():
        for raw in resp.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if obj.get("type") == "ic3_invariant_response":
                    for c in obj.get("candidates", []):
                        suggestions.append(c.get("predicate_ast", {}))
            except json.JSONDecodeError:
                pass

    return RunResult(
        name=name,
        mode="guided",
        result=result_str,
        elapsed_s=elapsed,
        cegar_rounds=_count_cegar(stderr_data),
        stage0_injected=injected,
        stage0_candidates=total,
        llm_suggestions=suggestions,
        injected_predicates=inj_lines,
        rejected_predicates=rej_lines,
        stderr_snippet=stderr_data[-600:],
    )


def print_report(baseline: RunResult, guided: RunResult) -> None:
    b, g = baseline, guided
    print(f"\n{'='*60}")
    print(f"Benchmark: {b.name}")
    print(f"{'='*60}")
    print(f"  {'':20s} {'BASELINE':>12s}   {'LLM-GUIDED':>12s}")
    print(f"  {'Result':20s} {b.result:>12s}   {g.result:>12s}")
    print(f"  {'Time (s)':20s} {b.elapsed_s:>12.1f}   {g.elapsed_s:>12.1f}")
    print(f"  {'CEGAR rounds':20s} {b.cegar_rounds:>12d}   {g.cegar_rounds:>12d}")
    if g.stage0_candidates > 0 or g.stage0_injected > 0:
        print(f"  {'Stage 0 injected':20s} {'—':>12s}   {g.stage0_injected}/{g.stage0_candidates} candidates")
    if g.llm_suggestions:
        print(f"  LLM suggestions ({len(g.llm_suggestions)}):")
        for i, s in enumerate(g.llm_suggestions[:8]):
            print(f"    [{i+1}] {json.dumps(s, separators=(',',':'))}")
    elif g.result not in ("skip-no-key", "timeout"):
        print(f"  LLM suggestions: (none / empty response)")
    if g.injected_predicates:
        print(f"  Injected into IC3IA:")
        for line in g.injected_predicates[:5]:
            print(f"    {line}")
    if g.rejected_predicates:
        print(f"  Rejection reasons ({len(g.rejected_predicates)}):")
        from collections import Counter
        reasons = Counter()
        for line in g.rejected_predicates:
            for kw in ("not only_curr", "not boolean", "not a predicate shape",
                       "duplicate", "intersects initial", "schema fail"):
                if kw in line:
                    reasons[kw] += 1
        for reason, count in reasons.most_common():
            print(f"    {count}x {reason}")
    if b.cegar_rounds > 0 and g.cegar_rounds < b.cegar_rounds:
        saved = b.cegar_rounds - g.cegar_rounds
        print(f"  ✓ LLM saved {saved} CEGAR round(s)!")
    elif b.cegar_rounds > 0 and g.cegar_rounds == b.cegar_rounds:
        print(f"  – No CEGAR savings (suggestions not accepted or not helpful)")
    elif b.cegar_rounds == 0:
        print(f"  – Benchmark trivially proved without CEGAR")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=180,
                        help="Seconds per run (default: 180)")
    parser.add_argument("--k", type=int, default=100,
                        help="IC3 bound k")
    parser.add_argument("--benchmarks", nargs="+",
                        choices=list(BENCHMARKS.keys()) + ["all"],
                        default=["all"])
    parser.add_argument("--no-guided", action="store_true",
                        help="Skip LLM-guided runs (baseline only)")
    args = parser.parse_args()

    names = list(BENCHMARKS.keys()) if "all" in args.benchmarks else args.benchmarks

    # Filter to existing files
    available = {n: p for n, p in BENCHMARKS.items() if n in names and p.exists()}
    missing = [n for n in names if n not in available]
    if missing:
        print(f"[warn] Missing benchmark files: {missing}", file=sys.stderr)

    if not available:
        print("No benchmarks available.", file=sys.stderr)
        sys.exit(1)

    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="pono_hwmcc_"))
    print(f"Temp dir: {tmp_dir}")
    print(f"Benchmarks: {list(available.keys())}")
    print(f"Timeout per run: {args.timeout}s")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[warn] DEEPSEEK_API_KEY not set — guided runs will be skipped")

    results = []
    for name, btor2 in available.items():
        print(f"\n--- Running baseline: {name} ---")
        try:
            b = run_baseline(name, btor2, args.timeout, args.k)
        except subprocess.TimeoutExpired:
            b = RunResult(name=name, mode="baseline", result="timeout",
                          elapsed_s=args.timeout)
        except Exception as e:
            b = RunResult(name=name, mode="baseline", result=f"error: {e}")
        print(f"    {b.result} in {b.elapsed_s:.1f}s, {b.cegar_rounds} CEGAR rounds")

        if args.no_guided:
            g = RunResult(name=name, mode="guided", result="skipped")
        else:
            print(f"--- Running LLM-guided: {name} ---")
            try:
                g = run_guided(name, btor2, args.timeout, tmp_dir, args.k)
            except Exception as e:
                g = RunResult(name=name, mode="guided", result=f"error: {e}")
            print(f"    {g.result} in {g.elapsed_s:.1f}s, {g.cegar_rounds} CEGAR rounds, "
                  f"injected {g.stage0_injected}/{g.stage0_candidates}")

        results.append((b, g))

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for b, g in results:
        print_report(b, g)

    # Save JSON results
    out_json = tmp_dir / "results.json"
    out_data = []
    for b, g in results:
        out_data.append({
            "name": b.name,
            "baseline": {"result": b.result, "time_s": round(b.elapsed_s, 2),
                         "cegar": b.cegar_rounds},
            "guided": {"result": g.result, "time_s": round(g.elapsed_s, 2),
                       "cegar": g.cegar_rounds, "injected": g.stage0_injected,
                       "candidates": g.stage0_candidates,
                       "suggestions": g.llm_suggestions},
        })
    out_json.write_text(json.dumps(out_data, indent=2))
    print(f"\nFull results saved to: {out_json}")


if __name__ == "__main__":
    main()
