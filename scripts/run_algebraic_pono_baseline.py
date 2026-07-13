#!/usr/bin/env python3
"""Run Pono IC3IA on Gate 4B controls with the certified basis as predicates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

import run_algebraic_baselines as baseline_runner
import check_algebraic_certificate as checker
import bv_poly_kernel as kernel
import cert_check


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _const(value: int, width: int) -> dict:
    return {"form": "const", "width": width, "const": str(value)}


def _multiply(factors: list[dict]) -> dict:
    if len(factors) == 1:
        return factors[0]
    return {"form": "mul", "args": factors}


def polynomial_ast(terms: list[dict], width: int) -> dict:
    parsed = kernel.Polynomial.from_terms(
        width,
        terms,
        allowed_variables={
            name for term in terms for name in term.get("powers", {})
        },
    )
    summands = []
    for monomial, coefficient in parsed.terms:
        factors = []
        if coefficient != 1 or not monomial:
            factors.append(_const(coefficient, width))
        for name, exponent in monomial:
            factors.extend({"form": "ref", "ref": name} for _ in range(exponent))
        summands.append(_multiply(factors))
    if not summands:
        expression = _const(0, width)
    elif len(summands) == 1:
        expression = summands[0]
    else:
        expression = {"form": "add", "args": summands}
    return {"form": "eq", "args": [expression, _const(0, width)]}


def predicate_jsonl(document: dict) -> str:
    lines = [
        json.dumps(
            {
                "predicate_ast": polynomial_ast(
                    invariant["terms"], document["width"]
                )
            },
            sort_keys=True,
        )
        for invariant in document["invariants"]
    ]
    return "\n".join(lines) + "\n"


def run_pono_baseline(
    benchmark_root: Path,
    certificate_directory: Path,
    pono_binary: Path,
    output_directory: Path,
    *,
    trials: int,
    timeout_sec: float,
) -> dict:
    if not pono_binary.is_file() or not os.access(pono_binary, os.X_OK):
        raise ValueError(f"Pono binary is unavailable: {pono_binary}")
    output_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = certificate_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "pono-modular-algebraic-development-controls-v1":
        raise ValueError("unsupported development-control manifest")
    rows = []
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=0"
    pono_version = baseline_runner._executable_version(
        pono_binary,
        accepted_returncodes=frozenset({0, 2}),
        environment=environment,
    )
    for control in manifest["controls"]:
        model_path = benchmark_root / control["benchmark_id"]
        if file_sha256(model_path) != control["benchmark_content_sha256"]:
            raise ValueError(f"benchmark hash mismatch: {control['benchmark_id']}")
        certificate_path = certificate_directory / control["certificate"]
        if file_sha256(certificate_path) != control["certificate_file_sha256"]:
            raise ValueError(
                f"certificate file hash mismatch: {control['benchmark_id']}"
            )
        document = json.loads(certificate_path.read_text())
        if canonical_sha256(document) != control["certificate_sha256"]:
            raise ValueError(
                f"certificate hash mismatch: {control['benchmark_id']}"
            )
        certificate_report = checker.check_certificate(
            model_path, document, timeout_ms=20_000
        )
        if not certificate_report["ok"]:
            raise ValueError(
                f"certificate is not accepted: {control['benchmark_id']}"
            )
        text = predicate_jsonl(document)
        predicate_path = output_directory / f"{Path(control['benchmark_id']).stem}.jsonl"
        predicate_path.write_text(text)
        predicate_hash = file_sha256(predicate_path)
        model = cert_check.parse_btor2(model_path)
        if not model["bads"]:
            raise ValueError(f"benchmark has no BAD property: {control['benchmark_id']}")
        arms = (
            ("pono-ic3ia-plain", ()),
            (
                "pono-ic3ia-certified-basis",
                ("--initial-predicates", str(predicate_path)),
            ),
        )
        for arm, extra_options in arms:
            for property_index in range(len(model["bads"])):
                for trial in range(trials):
                    command = [
                        str(pono_binary),
                        "-e",
                        "ic3ia",
                        "--smt-solver",
                        "bzla",
                        "-p",
                        str(property_index),
                        *extra_options,
                        str(model_path),
                    ]
                    outcome = baseline_runner._run_command(
                        command,
                        timeout_sec=timeout_sec,
                        environment=environment,
                    )
                    rows.append(
                        {
                            "benchmark_id": control["benchmark_id"],
                            "benchmark_content_sha256": control[
                                "benchmark_content_sha256"
                            ],
                            "certificate_sha256": control["certificate_sha256"],
                            "predicate_file": predicate_path.name,
                            "predicate_sha256": predicate_hash,
                            "arm": arm,
                            "property_index": property_index,
                            "trial": trial,
                            "obligation": "original-model-safety",
                            "command": command,
                            **outcome,
                        }
                    )
    report = {
        "schema": "pono-modular-algebraic-pono-matrix-v1",
        "certificate_manifest_sha256": file_sha256(manifest_path),
        "pono_executable": str(pono_binary),
        "pono_executable_sha256": file_sha256(pono_binary),
        "pono_version": pono_version,
        "solver": "bzla",
        "environment": {"ASAN_OPTIONS": "detect_leaks=0"},
        "trials": trials,
        "timeout_sec": timeout_sec,
        "rows": rows,
    }
    report["report_sha256"] = canonical_sha256(report)
    (output_directory / "matrix.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_root", type=Path)
    parser.add_argument("certificate_directory", type=Path)
    parser.add_argument("pono_binary", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=70.0)
    args = parser.parse_args(argv)
    if args.trials <= 0 or args.timeout_sec <= 0:
        parser.error("--trials and --timeout-sec must be positive")
    try:
        report = run_pono_baseline(
            args.benchmark_root,
            args.certificate_directory,
            args.pono_binary,
            args.output_directory,
            trials=args.trials,
            timeout_sec=args.timeout_sec,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    counts = {}
    for row in report["rows"]:
        arm = counts.setdefault(row["arm"], {})
        arm[row["result"]] = arm.get(row["result"], 0) + 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
