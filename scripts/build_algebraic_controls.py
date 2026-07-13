#!/usr/bin/env python3
"""Build the two frozen Gate 4B0 development-control certificates."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Sequence

import bv_poly_kernel as kernel
import cert_check
import check_algebraic_certificate as checker


@dataclasses.dataclass(frozen=True)
class DevelopmentControl:
    benchmark_id: str
    content_sha256: str
    width: int
    variables: tuple[str, ...]
    index_variable: str
    accumulator_variable: str
    constant_variable: str
    constant_value: int


DEVELOPMENT_CONTROLS = (
    DevelopmentControl(
        benchmark_id=(
            "2025/wordlevel/bv/2024/hkust/arithmetic_circuits/"
            "fib_23/fib_23.btor2"
        ),
        content_sha256=(
            "a078bbffe6dc000ce0a24a4d11c45efade0c613ca55ca40db83dbb7b013338d6"
        ),
        width=19,
        variables=("state7", "state10", "state13"),
        index_variable="state7",
        accumulator_variable="state13",
        constant_variable="state10",
        constant_value=150,
    ),
    DevelopmentControl(
        benchmark_id=(
            "2024/btor2/2024/hku/arithmetic_circuits/fib_30/fib_30.btor2"
        ),
        content_sha256=(
            "1bb400e569c8c3147d38245dd81458261c4cc0aac565286e731dabf78fdf31d0"
        ),
        width=19,
        variables=("state7", "state10", "state14"),
        index_variable="state10",
        accumulator_variable="state7",
        constant_variable="state14",
        constant_value=150,
    ),
)


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def certificate_terms(polynomial: kernel.Polynomial) -> list[dict]:
    terms = polynomial.canonical_terms()
    return terms or [{"coefficient": "0", "powers": {}}]


def _constant_matrix(
    width: int, basis_size: int, *, identity: bool
) -> tuple[tuple[kernel.Polynomial, ...], ...]:
    zero = kernel.Polynomial.zero(width)
    one = kernel.Polynomial.constant(width, 1)
    return tuple(
        tuple(one if identity and row == column else zero for column in range(basis_size))
        for row in range(basis_size)
    )


def _matrix_document(
    matrix: tuple[tuple[kernel.Polynomial, ...], ...]
) -> list[list[list[dict]]]:
    return [
        [certificate_terms(polynomial) for polynomial in row]
        for row in matrix
    ]


def build_control_certificate(
    model_path: Path,
    control: DevelopmentControl,
) -> dict:
    actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if actual_hash != control.content_sha256:
        raise ValueError(
            f"development-control hash mismatch for {control.benchmark_id}: "
            f"{actual_hash} != {control.content_sha256}"
        )
    model = cert_check.parse_btor2(model_path)
    width = control.width
    index = kernel.Polynomial.variable(width, control.index_variable)
    accumulator = kernel.Polynomial.variable(width, control.accumulator_variable)
    constant = kernel.Polynomial.variable(width, control.constant_variable)
    one = kernel.Polynomial.constant(width, 1)
    basis = (
        accumulator.scale(2) - index * (index - one),
        constant - kernel.Polynomial.constant(width, control.constant_value),
    )
    branches = kernel.extract_transition_branches(
        model,
        width=width,
        polynomial_variables=control.variables,
        tracked_state_variables=control.variables,
        branch_cap=8,
    )
    zero = _constant_matrix(width, len(basis), identity=False)
    identity = _constant_matrix(width, len(basis), identity=True)
    branch_documents = []
    for branch in branches:
        matching = [
            matrix
            for matrix in (zero, identity)
            if not kernel.check_multiplier_identity(
                basis, branch.substitutions, matrix
            )
        ]
        if len(matching) != 1:
            raise ValueError(
                f"branch {branch.branch_id} does not have exactly one frozen "
                "zero/identity development multiplier"
            )
        branch_documents.append(
            {
                "id": branch.branch_id,
                "guard_identity": kernel.guard_identity(branch.decisions),
                "next_state_substitution": {
                    name: certificate_terms(polynomial)
                    for name, polynomial in sorted(branch.substitutions.items())
                },
                "multipliers": _matrix_document(matching[0]),
            }
        )
    invariant_documents = [
        {"id": f"P{index}", "terms": certificate_terms(polynomial)}
        for index, polynomial in enumerate(basis)
    ]
    return {
        "schema": checker.SCHEMA,
        "benchmark_id": control.benchmark_id,
        "benchmark_content_sha256": actual_hash,
        "candidate_sha256": canonical_sha256(invariant_documents),
        "width": width,
        "variables": list(control.variables),
        "invariants": invariant_documents,
        "branches": branch_documents,
    }


def build_controls(
    benchmark_root: Path,
    output_directory: Path,
    *,
    timeout_ms: int,
) -> dict:
    output_directory.mkdir(parents=True, exist_ok=False)
    rows = []
    for control in DEVELOPMENT_CONTROLS:
        model_path = benchmark_root / control.benchmark_id
        certificate = build_control_certificate(model_path, control)
        report = checker.check_certificate(
            model_path, certificate, timeout_ms=timeout_ms
        )
        if not report["ok"]:
            raise RuntimeError(
                f"generated development control was rejected: {control.benchmark_id}"
            )
        slug = Path(control.benchmark_id).stem
        certificate_path = output_directory / f"{slug}.certificate.json"
        report_path = output_directory / f"{slug}.report.json"
        certificate_path.write_text(
            json.dumps(certificate, indent=2, sort_keys=True) + "\n"
        )
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        rows.append(
            {
                "benchmark_id": control.benchmark_id,
                "benchmark_content_sha256": control.content_sha256,
                "certificate": certificate_path.name,
                "certificate_sha256": canonical_sha256(certificate),
                "certificate_file_sha256": hashlib.sha256(
                    certificate_path.read_bytes()
                ).hexdigest(),
                "report": report_path.name,
                "report_file_sha256": hashlib.sha256(
                    report_path.read_bytes()
                ).hexdigest(),
                "accepted": True,
            }
        )
    manifest = {
        "schema": "pono-modular-algebraic-development-controls-v1",
        "controls": rows,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_root", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    args = parser.parse_args(argv)
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    try:
        manifest = build_controls(
            args.benchmark_root,
            args.output_directory,
            timeout_ms=args.timeout_ms,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
