#!/usr/bin/env python3
"""Measure Gate 4B kernel C2 and full-certificate costs on frozen controls."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Sequence

import z3

import bv_poly_kernel as kernel
import cert_check
import check_algebraic_certificate as checker


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_kernel_c2(
    model_path: Path, document: dict, *, branch_cap: int
) -> dict:
    started = time.perf_counter()
    width = document["width"]
    variables = checker._parse_variables(document["variables"])
    model = cert_check.parse_btor2(model_path)
    checker._validate_variables_against_model(model, variables, width)
    invariant_ids, basis = checker._parse_invariants(
        document["invariants"], width=width, variables=variables
    )
    tracked_states = tuple(
        sorted(
            {
                variable
                for polynomial in basis
                for variable in polynomial.variables()
                if variable.startswith("state")
            },
            key=lambda value: int(value.removeprefix("state")),
        )
    )
    branches = kernel.extract_transition_branches(
        model,
        width=width,
        polynomial_variables=variables,
        tracked_state_variables=tracked_states,
        branch_cap=branch_cap,
    )
    supplied = checker._parse_branches(
        document["branches"],
        width=width,
        variables=variables,
        tracked_state_variables=tracked_states,
        basis_size=len(basis),
    )
    branch_ids = {branch.branch_id for branch in branches}
    if branch_ids != set(supplied):
        raise ValueError("branch set mismatch during kernel measurement")
    errors = []
    for branch in branches:
        supplied_branch = supplied[branch.branch_id]
        if supplied_branch["guard_identity"] != kernel.guard_identity(
            branch.decisions
        ):
            raise ValueError("guard identity mismatch during kernel measurement")
        if supplied_branch["next_state_substitution"] != branch.substitutions:
            raise ValueError(
                "next-state substitution mismatch during kernel measurement"
            )
        errors.extend(
            kernel.check_multiplier_identity(
                basis, branch.substitutions, supplied_branch["multipliers"]
            )
        )
    elapsed = time.perf_counter() - started
    return {
        "result": "accepted" if not errors else "rejected",
        "wall_time_sec": elapsed,
        "branch_count": len(branches),
        "basis_size": len(basis),
        "invariant_ids": list(invariant_ids),
        "errors": errors,
    }


def run_gate_controls(
    benchmark_root: Path,
    certificate_directory: Path,
    output_path: Path,
    *,
    trials: int,
    timeout_ms: int,
    branch_cap: int,
) -> dict:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite kernel matrix: {output_path}")
    manifest_path = certificate_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "pono-modular-algebraic-development-controls-v1":
        raise ValueError("unsupported development-control manifest")
    rows = []
    for control in manifest.get("controls", []):
        model_path = benchmark_root / control["benchmark_id"]
        certificate_path = certificate_directory / control["certificate"]
        document = json.loads(certificate_path.read_text())
        if file_sha256(model_path) != control["benchmark_content_sha256"]:
            raise ValueError(f"benchmark hash mismatch: {control['benchmark_id']}")
        initial_report = checker.check_certificate(
            model_path, document, timeout_ms=timeout_ms, branch_cap=branch_cap
        )
        if not initial_report["ok"]:
            raise ValueError(f"control certificate rejected: {control['benchmark_id']}")
        for trial in range(trials):
            kernel_result = run_kernel_c2(
                model_path, document, branch_cap=branch_cap
            )
            full_started = time.perf_counter()
            full_report = checker.check_certificate(
                model_path,
                document,
                timeout_ms=timeout_ms,
                branch_cap=branch_cap,
            )
            full_elapsed = time.perf_counter() - full_started
            rows.append(
                {
                    "benchmark_id": control["benchmark_id"],
                    "benchmark_content_sha256": control["benchmark_content_sha256"],
                    "certificate_sha256": initial_report["certificate_sha256"],
                    "role": "development-control",
                    "counts_toward_h5a": False,
                    "trial": trial,
                    "kernel_c2_result": kernel_result["result"],
                    "kernel_c2_wall_time_sec": kernel_result["wall_time_sec"],
                    "full_certificate_ok": full_report["ok"],
                    "full_certificate_wall_time_sec": full_elapsed,
                    "checks": full_report["checks"],
                    "branch_count": kernel_result["branch_count"],
                    "basis_size": kernel_result["basis_size"],
                }
            )
    medians = {}
    for benchmark_id in sorted({row["benchmark_id"] for row in rows}):
        selected = [row for row in rows if row["benchmark_id"] == benchmark_id]
        medians[benchmark_id] = {
            "kernel_c2_wall_time_sec": statistics.median(
                row["kernel_c2_wall_time_sec"] for row in selected
            ),
            "full_certificate_wall_time_sec": statistics.median(
                row["full_certificate_wall_time_sec"] for row in selected
            ),
        }
    report = {
        "schema": "pono-modular-algebraic-kernel-matrix-v1",
        "certificate_manifest_sha256": file_sha256(manifest_path),
        "trials": trials,
        "timeout_ms": timeout_ms,
        "branch_cap": branch_cap,
        "python_z3_version": z3.get_version_string(),
        "rows": rows,
        "medians": medians,
    }
    report["report_sha256"] = canonical_sha256(report)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_root", type=Path)
    parser.add_argument("certificate_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--branch-cap", type=int, default=8)
    args = parser.parse_args(argv)
    if args.trials <= 0 or args.timeout_ms <= 0 or args.branch_cap <= 0:
        parser.error("trials, timeout, and branch cap must be positive")
    try:
        report = run_gate_controls(
            args.benchmark_root,
            args.certificate_directory,
            args.output,
            trials=args.trials,
            timeout_ms=args.timeout_ms,
            branch_cap=args.branch_cap,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        z3.Z3Exception,
    ) as error:
        print(str(error))
        return 1
    print(json.dumps(report["medians"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
