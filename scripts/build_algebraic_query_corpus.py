#!/usr/bin/env python3
"""Build immutable generic-C2 SMT2 queries from accepted Gate 4B certificates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

import z3

import candidate_cert_check
import check_algebraic_certificate as checker


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def certificate_c2_formula(model_path: Path, document: dict):
    width = document["width"]
    variables = checker._parse_variables(document["variables"])
    _, basis = checker._parse_invariants(
        document["invariants"], width=width, variables=variables
    )
    base = candidate_cert_check.build_base_formulas(str(model_path))
    invariant = z3.And(
        *[
            checker._polynomial_to_z3(polynomial, base)
            == z3.BitVecVal(0, width)
            for polynomial in basis
        ]
    )
    invariant_next = z3.substitute(invariant, *base["substitutions"])
    return z3.And(
        invariant,
        base["constraints"],
        base["constraints_next"],
        z3.Not(invariant_next),
    )


def formula_to_smt2(formula) -> str:
    solver = z3.Solver()
    solver.add(formula)
    text = solver.to_smt2()
    if "(set-logic " not in text:
        text = "(set-logic QF_BV)\n" + text
    return text if text.endswith("\n") else text + "\n"


def build_query_corpus(
    benchmark_root: Path,
    certificate_directory: Path,
    output_directory: Path,
    *,
    timeout_ms: int,
) -> dict:
    source_manifest_path = certificate_directory / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text())
    if source_manifest.get("schema") != "pono-modular-algebraic-development-controls-v1":
        raise ValueError("unsupported certificate manifest schema")
    output_directory.mkdir(parents=True, exist_ok=False)
    rows = []
    for row in source_manifest.get("controls", []):
        benchmark_id = row["benchmark_id"]
        model_path = benchmark_root / benchmark_id
        certificate_path = certificate_directory / row["certificate"]
        if hashlib.sha256(certificate_path.read_bytes()).hexdigest() != row[
            "certificate_file_sha256"
        ]:
            raise ValueError(f"certificate file hash mismatch: {benchmark_id}")
        document = json.loads(certificate_path.read_text())
        if canonical_sha256(document) != row["certificate_sha256"]:
            raise ValueError(f"certificate canonical hash mismatch: {benchmark_id}")
        report = checker.check_certificate(
            model_path, document, timeout_ms=timeout_ms
        )
        if not report["ok"]:
            raise ValueError(f"source certificate is not accepted: {benchmark_id}")
        formula = certificate_c2_formula(model_path, document)
        query_text = formula_to_smt2(formula)
        model = candidate_cert_check.build_base_formulas(str(model_path))["model"]
        variables = checker._parse_variables(document["variables"])
        _, basis = checker._parse_invariants(
            document["invariants"],
            width=document["width"],
            variables=variables,
        )
        slug = Path(benchmark_id).stem
        query_name = f"{slug}.c2.smt2"
        query_path = output_directory / query_name
        query_path.write_text(query_text)
        basis_hash = canonical_sha256(document["invariants"])
        rows.append(
            {
                "benchmark_id": benchmark_id,
                "benchmark_content_sha256": report["benchmark_content_sha256"],
                "certificate_sha256": report["certificate_sha256"],
                "invariant_basis_sha256": basis_hash,
                "query": query_name,
                "query_sha256": hashlib.sha256(query_path.read_bytes()).hexdigest(),
                "width": document["width"],
                "variable_count": len(document["variables"]),
                "state_count": len(model["states"]),
                "input_count": sum(
                    operation == "input"
                    for operation, _ in model["nodes"].values()
                ),
                "basis_size": len(document["invariants"]),
                "maximum_basis_degree": max(
                    polynomial.degree() for polynomial in basis
                ),
                "branch_count": report["branch_count"],
                "role": "development-control",
                "counts_toward_h5a": False,
            }
        )
    manifest = {
        "schema": "pono-modular-algebraic-c2-corpus-v1",
        "source_manifest_sha256": hashlib.sha256(
            source_manifest_path.read_bytes()
        ).hexdigest(),
        "query_count": len(rows),
        "queries": rows,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark_root", type=Path)
    parser.add_argument("certificate_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    args = parser.parse_args(argv)
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    try:
        manifest = build_query_corpus(
            args.benchmark_root,
            args.certificate_directory,
            args.output_directory,
            timeout_ms=args.timeout_ms,
        )
    except (OSError, ValueError, KeyError, TypeError, z3.Z3Exception) as error:
        print(str(error))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
