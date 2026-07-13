#!/usr/bin/env python3
"""Run the frozen malformed/unsafe rejection suite for Gate 4B H5c."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Callable, Sequence

import z3

import bv_poly_kernel as kernel
import cert_check
import check_algebraic_certificate as checker


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _term(coefficient: int, powers: dict[str, int] | None = None) -> dict:
    return {
        "coefficient": str(coefficient),
        "powers": powers or {},
    }


def _synthetic_model(path: Path, mode: str) -> dict:
    if mode == "unsafe":
        next_line = "7 next 2 5 5"
        bad_line = "8 eq 1 5 3"
    elif mode == "false-initial":
        next_line = "7 next 2 5 5"
        bad_line = "8 eq 1 5 4"
    elif mode == "unsupported-extract":
        next_line = "7 slice 2 5 7 0\n8 next 2 5 7"
        bad_line = "9 eq 1 5 4"
    elif mode == "unsupported-division":
        next_line = "7 udiv 2 5 4\n8 next 2 5 7"
        bad_line = "9 eq 1 5 4"
    elif mode == "missing-next":
        next_line = ""
        bad_line = "8 eq 1 5 4"
    else:
        raise ValueError(f"unknown synthetic mode {mode}")
    lines = [
        "1 sort bitvec 1",
        "2 sort bitvec 8",
        "3 zero 2",
        "4 one 2",
        "5 state 2 x",
        "6 init 2 5 3",
    ]
    if next_line:
        lines.extend(next_line.splitlines())
    lines.append(bad_line)
    bad_node = int(bad_line.split()[0])
    lines.append(f"{bad_node + 1} bad {bad_node}")
    path.write_text("\n".join(lines) + "\n")
    model = cert_check.parse_btor2(path)
    branch_id = "b-0000000000000000"
    branches = ()
    if mode not in {"unsupported-extract", "unsupported-division", "missing-next"}:
        branches = kernel.extract_transition_branches(
            model,
            width=8,
            polynomial_variables=("state5",),
            tracked_state_variables=("state5",),
            branch_cap=8,
        )
        branch_id = branches[0].branch_id
    invariant_constant = 1 if mode == "false-initial" else 0
    invariant_documents = [
        {
            "id": "P0",
            "terms": [
                _term(1, {"state5": 1}),
                _term(-invariant_constant),
            ],
        }
    ]
    return {
        "schema": checker.SCHEMA,
        "benchmark_id": f"negative/{mode}.btor2",
        "benchmark_content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_sha256": canonical_sha256(invariant_documents),
        "width": 8,
        "variables": ["state5"],
        "invariants": invariant_documents,
        "branches": [
            {
                "id": branch_id,
                "guard_identity": (
                    kernel.guard_identity(branches[0].decisions)
                    if branches
                    else "g-0000000000000000"
                ),
                "next_state_substitution": (
                    {
                        name: polynomial.canonical_terms() or [_term(0)]
                        for name, polynomial in sorted(
                            branches[0].substitutions.items()
                        )
                    }
                    if branches
                    else {"state5": [_term(1, {"state5": 1})]}
                ),
                "multipliers": [[[ _term(1) ]]],
            }
        ],
    }


def _run_case(
    name: str,
    model_path: Path,
    document: dict,
    *,
    timeout_ms: int,
    expected_rejection: str,
) -> dict:
    try:
        report = checker.check_certificate(
            model_path, document, timeout_ms=timeout_ms
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        NotImplementedError,
        z3.Z3Exception,
    ) as error:
        result = {
            "name": name,
            "accepted": False,
            "rejection_kind": "schema-or-model-error",
            "detail": str(error),
        }
        result["expected_rejection"] = expected_rejection
        result["expectation_met"] = expected_rejection == result["rejection_kind"]
        return result
    checks = {check["name"]: check["result"] for check in report["checks"]}
    if report["ok"]:
        rejection_kind = "none"
    elif checks["C1 Init=>H"] == "sat":
        rejection_kind = "C1-sat"
    elif checks["C2 modular identities"] == "rejected":
        rejection_kind = "C2-rejected"
    elif checks["C3 H=>notBAD"] == "sat":
        rejection_kind = "C3-sat"
    else:
        rejection_kind = "formal-check-rejected"
    result = {
        "name": name,
        "accepted": report["ok"],
        "rejection_kind": rejection_kind,
        "checks": report["checks"],
        "identity_errors": report["identity_errors"],
        "expected_rejection": expected_rejection,
    }
    result["expectation_met"] = expected_rejection == rejection_kind
    return result


def run_negative_suite(
    benchmark_root: Path,
    certificate_directory: Path,
    output_directory: Path,
    *,
    timeout_ms: int,
) -> dict:
    output_directory.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((certificate_directory / "manifest.json").read_text())
    control = manifest["controls"][0]
    control_path = benchmark_root / control["benchmark_id"]
    original = json.loads(
        (certificate_directory / control["certificate"]).read_text()
    )
    mutations: list[tuple[str, str, Callable[[dict], None]]] = []

    def mutation(name: str, expected_rejection: str):
        def register(function: Callable[[dict], None]):
            mutations.append((name, expected_rejection, function))
            return function
        return register

    @mutation("wrong-multiplier", "C2-rejected")
    def wrong_multiplier(document: dict) -> None:
        document["branches"][0]["multipliers"][0][0] = [_term(7)]

    @mutation("missing-branch", "schema-or-model-error")
    def missing_branch(document: dict) -> None:
        document["branches"].pop()

    @mutation("extra-branch", "schema-or-model-error")
    def extra_branch(document: dict) -> None:
        branch = copy.deepcopy(document["branches"][0])
        branch["id"] = "b-ffffffffffffffff"
        document["branches"].append(branch)

    @mutation("wrong-width", "schema-or-model-error")
    def wrong_width(document: dict) -> None:
        document["width"] += 1

    @mutation("benchmark-hash-mismatch", "schema-or-model-error")
    def hash_mismatch(document: dict) -> None:
        document["benchmark_content_sha256"] = "0" * 64

    @mutation("candidate-hash-mismatch", "schema-or-model-error")
    def candidate_hash_mismatch(document: dict) -> None:
        document["candidate_sha256"] = "0" * 64

    @mutation("unknown-schema-field", "schema-or-model-error")
    def unknown_field(document: dict) -> None:
        document["repair"] = True

    @mutation("zero-invariant", "schema-or-model-error")
    def zero_invariant(document: dict) -> None:
        document["invariants"][0]["terms"] = [_term(0)]

    @mutation("wrong-matrix-dimension", "schema-or-model-error")
    def wrong_matrix(document: dict) -> None:
        document["branches"][0]["multipliers"].pop()

    @mutation("invalid-branch-id", "schema-or-model-error")
    def invalid_branch(document: dict) -> None:
        document["branches"][0]["id"] = "llm-branch"

    @mutation("duplicate-branch-id", "schema-or-model-error")
    def duplicate_branch(document: dict) -> None:
        document["branches"].append(copy.deepcopy(document["branches"][0]))

    @mutation("wrong-guard-identity", "schema-or-model-error")
    def wrong_guard(document: dict) -> None:
        current = document["branches"][0]["guard_identity"]
        document["branches"][0]["guard_identity"] = (
            "g-1111111111111111"
            if current == "g-0000000000000000"
            else "g-0000000000000000"
        )

    @mutation("missing-next-state-substitution", "schema-or-model-error")
    def missing_substitution(document: dict) -> None:
        document["branches"][0]["next_state_substitution"].pop(
            next(iter(document["branches"][0]["next_state_substitution"]))
        )

    @mutation("wrong-next-state-substitution", "schema-or-model-error")
    def wrong_substitution(document: dict) -> None:
        name = next(iter(document["branches"][0]["next_state_substitution"]))
        document["branches"][0]["next_state_substitution"][name].append(_term(1))

    @mutation("unknown-variable", "schema-or-model-error")
    def unknown_variable(document: dict) -> None:
        document["variables"].append("state999999")

    rows = []
    for name, expected_rejection, mutate in mutations:
        document = copy.deepcopy(original)
        mutate(document)
        rows.append(
            _run_case(
                name,
                control_path,
                document,
                timeout_ms=timeout_ms,
                expected_rejection=expected_rejection,
            )
        )

    for mode, expected_rejection in (
        ("unsafe", "C3-sat"),
        ("false-initial", "C1-sat"),
        ("unsupported-extract", "schema-or-model-error"),
        ("unsupported-division", "schema-or-model-error"),
        ("missing-next", "schema-or-model-error"),
    ):
        model_path = output_directory / f"{mode}.btor2"
        document = _synthetic_model(model_path, mode)
        certificate_path = output_directory / f"{mode}.certificate.json"
        certificate_path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        )
        rows.append(
            _run_case(
                mode,
                model_path,
                document,
                timeout_ms=timeout_ms,
                expected_rejection=expected_rejection,
            )
        )

    accepted = [row["name"] for row in rows if row["accepted"]]
    report = {
        "schema": "pono-modular-algebraic-negative-suite-v1",
        "case_count": len(rows),
        "rejected_count": len(rows) - len(accepted),
        "accepted_count": len(accepted),
        "accepted_cases": accepted,
        "all_rejected": not accepted,
        "expectation_failure_count": sum(
            not row["expectation_met"] for row in rows
        ),
        "all_expectations_met": all(row["expectation_met"] for row in rows),
        "cases": rows,
    }
    report["report_sha256"] = canonical_sha256(report)
    (output_directory / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


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
        report = run_negative_suite(
            args.benchmark_root,
            args.certificate_directory,
            args.output_directory,
            timeout_ms=args.timeout_ms,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_rejected"] and report["all_expectations_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
