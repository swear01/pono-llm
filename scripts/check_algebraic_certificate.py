#!/usr/bin/env python3
"""Check Gate 4B modular algebraic certificates on an original BTOR2 model."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Sequence

import z3

import bv_poly_kernel as kernel
import candidate_cert_check
import cert_check


SCHEMA = "pono-modular-algebraic-certificate-v1"
_TOP_FIELDS = {
    "schema",
    "benchmark_id",
    "benchmark_content_sha256",
    "candidate_sha256",
    "width",
    "variables",
    "invariants",
    "branches",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _strict_fields(value: dict, expected: set[str], location: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        raise ValueError(
            f"{location} has unknown fields {sorted(unknown)} "
            f"or missing fields {sorted(missing)}"
        )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_benchmark_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("benchmark_id must be a non-empty string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("benchmark_id must be portable and relative")
    return path.as_posix()


def _parse_variables(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("variables must be a non-empty list")
    variables = []
    for index, variable in enumerate(raw):
        if not isinstance(variable, str) or not re.fullmatch(
            r"(?:state|input)[0-9]+", variable
        ):
            raise ValueError(f"variables[{index}] must be a stateN or inputN ref")
        variables.append(variable)
    if len(variables) != len(set(variables)):
        raise ValueError("variables must be unique")
    return tuple(variables)


def _parse_invariants(
    raw: object, *, width: int, variables: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[kernel.Polynomial, ...]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("invariants must be a non-empty list")
    allowed = set(variables)
    ids = []
    invariants = []
    for index, invariant in enumerate(raw):
        if not isinstance(invariant, dict):
            raise ValueError(f"invariant {index} must be an object")
        _strict_fields(invariant, {"id", "terms"}, f"invariant {index}")
        invariant_id = invariant["id"]
        if not isinstance(invariant_id, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]*", invariant_id
        ):
            raise ValueError(f"invariant {index} has invalid id")
        polynomial = kernel.Polynomial.from_terms(
            width, invariant["terms"], allowed_variables=allowed
        )
        if polynomial.is_zero():
            raise ValueError(f"invariant {invariant_id} is a zero polynomial")
        input_refs = sorted(
            variable for variable in polynomial.variables() if variable.startswith("input")
        )
        if input_refs:
            raise ValueError(
                f"invariant {invariant_id} references step-local inputs {input_refs}"
            )
        ids.append(invariant_id)
        invariants.append(polynomial)
    if len(ids) != len(set(ids)):
        raise ValueError("invariant ids must be unique")
    return tuple(ids), tuple(invariants)


def _validate_variables_against_model(
    model: dict, variables: tuple[str, ...], width: int
) -> None:
    for variable in variables:
        node = int(re.search(r"[0-9]+$", variable).group())
        op, _ = model["nodes"].get(node, (None, []))
        expected_op = "state" if variable.startswith("state") else "input"
        if op != expected_op:
            raise ValueError(f"{variable} does not name a BTOR2 {expected_op}")
        actual_width = cert_check.width_of(model, node)
        if actual_width != width:
            raise ValueError(
                f"{variable} has width {actual_width}, certificate declares {width}"
            )


def _parse_multiplier_matrix(
    raw: object,
    *,
    width: int,
    variables: tuple[str, ...],
    basis_size: int,
    branch_id: str,
) -> tuple[tuple[kernel.Polynomial, ...], ...]:
    if not isinstance(raw, list) or len(raw) != basis_size:
        raise ValueError(
            f"branch {branch_id} multiplier matrix must have {basis_size} rows"
        )
    result = []
    allowed = set(variables)
    for row_index, row in enumerate(raw):
        if not isinstance(row, list) or len(row) != basis_size:
            raise ValueError(
                f"branch {branch_id} multiplier row {row_index} must have "
                f"{basis_size} cells"
            )
        result.append(
            tuple(
                kernel.Polynomial.from_terms(
                    width, cell, allowed_variables=allowed
                )
                for cell in row
            )
        )
    return tuple(result)


def _parse_branches(
    raw: object,
    *,
    width: int,
    variables: tuple[str, ...],
    tracked_state_variables: tuple[str, ...],
    basis_size: int,
) -> dict[str, dict]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("branches must be a non-empty list")
    branches = {}
    for index, branch in enumerate(raw):
        if not isinstance(branch, dict):
            raise ValueError(f"branch {index} must be an object")
        _strict_fields(
            branch,
            {"id", "guard_identity", "next_state_substitution", "multipliers"},
            f"branch {index}",
        )
        branch_id = branch["id"]
        if not isinstance(branch_id, str) or not re.fullmatch(r"b-[0-9a-f]{16}", branch_id):
            raise ValueError(f"branch {index} has invalid checker-derived id")
        if branch_id in branches:
            raise ValueError(f"duplicate branch id {branch_id}")
        guard = branch["guard_identity"]
        if not isinstance(guard, str) or not re.fullmatch(r"g-[0-9a-f]{16}", guard):
            raise ValueError(f"branch {branch_id} has invalid guard identity")
        raw_substitutions = branch["next_state_substitution"]
        if not isinstance(raw_substitutions, dict):
            raise ValueError(
                f"branch {branch_id} next-state substitution must be an object"
            )
        expected_states = set(tracked_state_variables)
        actual_states = set(raw_substitutions)
        if actual_states != expected_states:
            raise ValueError(
                f"branch {branch_id} next-state substitution is incomplete: "
                f"missing={sorted(expected_states - actual_states)}, "
                f"extra={sorted(actual_states - expected_states)}"
            )
        substitutions = {
            name: kernel.Polynomial.from_terms(
                width, raw_substitutions[name], allowed_variables=set(variables)
            )
            for name in tracked_state_variables
        }
        branches[branch_id] = {
            "guard_identity": guard,
            "next_state_substitution": substitutions,
            "multipliers": _parse_multiplier_matrix(
                branch["multipliers"],
                width=width,
                variables=variables,
                basis_size=basis_size,
                branch_id=branch_id,
            ),
        }
    return branches


def _polynomial_to_z3(polynomial: kernel.Polynomial, base: dict):
    width = polynomial.width
    variables = {
        **{f"state{node}": value for node, value in base["statevars"].items()},
        **{f"input{node}": value for node, value in base["inputvars"].items()},
    }
    result = z3.BitVecVal(0, width)
    for monomial, coefficient in polynomial.terms:
        term = z3.BitVecVal(coefficient, width)
        for name, exponent in monomial:
            factor = variables[name]
            for _ in range(exponent):
                term = term * factor
        result = result + term
    return result


def check_certificate(
    btor2_path: str | Path,
    document: object,
    *,
    timeout_ms: int,
    branch_cap: int = 8,
) -> dict:
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    if not isinstance(document, dict):
        raise ValueError("certificate must be a JSON object")
    _strict_fields(document, _TOP_FIELDS, "certificate")
    if document["schema"] != SCHEMA:
        raise ValueError(f"certificate schema must be {SCHEMA}")
    benchmark_id = _validate_benchmark_id(document["benchmark_id"])
    declared_hash = document["benchmark_content_sha256"]
    if not isinstance(declared_hash, str) or not _SHA256.fullmatch(declared_hash):
        raise ValueError("benchmark_content_sha256 must be lowercase SHA-256")
    model_path = Path(btor2_path)
    actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if actual_hash != declared_hash:
        raise ValueError(
            f"benchmark content SHA-256 mismatch: {declared_hash} != {actual_hash}"
        )
    width = document["width"]
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        raise ValueError("width must be a positive integer")
    variables = _parse_variables(document["variables"])
    model = cert_check.parse_btor2(model_path)
    _validate_variables_against_model(model, variables, width)
    invariant_ids, basis = _parse_invariants(
        document["invariants"], width=width, variables=variables
    )
    candidate_hash = document["candidate_sha256"]
    if not isinstance(candidate_hash, str) or not _SHA256.fullmatch(candidate_hash):
        raise ValueError("candidate_sha256 must be lowercase SHA-256")
    expected_candidate_hash = _canonical_sha256(document["invariants"])
    if candidate_hash != expected_candidate_hash:
        raise ValueError(
            "candidate SHA-256 mismatch: "
            f"{candidate_hash} != {expected_candidate_hash}"
        )
    tracked_state_variables = tuple(
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
    if not tracked_state_variables:
        raise ValueError("invariant basis requires at least one state variable")
    extracted = kernel.extract_transition_branches(
        model,
        width=width,
        polynomial_variables=variables,
        tracked_state_variables=tracked_state_variables,
        branch_cap=branch_cap,
    )
    supplied = _parse_branches(
        document["branches"],
        width=width,
        variables=variables,
        tracked_state_variables=tracked_state_variables,
        basis_size=len(basis),
    )
    extracted_ids = {branch.branch_id for branch in extracted}
    supplied_ids = set(supplied)
    if extracted_ids != supplied_ids:
        raise ValueError(
            "branch set mismatch: "
            f"missing={sorted(extracted_ids - supplied_ids)}, "
            f"extra={sorted(supplied_ids - extracted_ids)}"
        )

    base = candidate_cert_check.build_base_formulas(str(model_path))
    invariant_terms = [
        _polynomial_to_z3(polynomial, base) == z3.BitVecVal(0, width)
        for polynomial in basis
    ]
    invariant = z3.And(*invariant_terms)
    _, c1 = candidate_cert_check.solve_formula(
        z3.And(base["init"], base["constraints"], z3.Not(invariant)),
        timeout_ms,
    )

    identity_errors = []
    branch_reports = []
    for branch in extracted:
        supplied_branch = supplied[branch.branch_id]
        expected_guard = kernel.guard_identity(branch.decisions)
        if supplied_branch["guard_identity"] != expected_guard:
            raise ValueError(
                f"branch {branch.branch_id} guard identity mismatch: "
                f"{supplied_branch['guard_identity']} != {expected_guard}"
            )
        if supplied_branch["next_state_substitution"] != branch.substitutions:
            raise ValueError(
                f"branch {branch.branch_id} next-state substitution mismatch"
            )
        errors = kernel.check_multiplier_identity(
            basis, branch.substitutions, supplied_branch["multipliers"]
        )
        identity_errors.extend(
            f"{branch.branch_id}: {error}" for error in errors
        )
        branch_reports.append(
            {
                "id": branch.branch_id,
                "decisions": [[node, value] for node, value in branch.decisions],
                "result": "accepted" if not errors else "rejected",
                "errors": list(errors),
            }
        )
    c2 = "accepted" if not identity_errors else "rejected"

    _, c3 = candidate_cert_check.solve_formula(
        z3.And(invariant, base["constraints"], base["bad"]), timeout_ms
    )
    checks = [
        {"name": "C1 Init=>H", "result": str(c1)},
        {"name": "C2 modular identities", "result": c2},
        {"name": "C3 H=>notBAD", "result": str(c3)},
    ]
    return {
        "schema": "pono-modular-algebraic-certificate-report-v1",
        "benchmark_id": benchmark_id,
        "benchmark_content_sha256": actual_hash,
        "candidate_sha256": candidate_hash,
        "certificate_sha256": _canonical_sha256(document),
        "width": width,
        "variables": list(variables),
        "invariant_ids": list(invariant_ids),
        "branch_count": len(extracted),
        "branches": branch_reports,
        "identity_errors": identity_errors,
        "checks": checks,
        "ok": c1 == z3.unsat and c2 == "accepted" and c3 == z3.unsat,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("btor2")
    parser.add_argument("certificate")
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--branch-cap", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        document = json.loads(Path(args.certificate).read_text())
        report = check_certificate(
            args.btor2,
            document,
            timeout_ms=args.timeout_ms,
            branch_cap=args.branch_cap,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
        NotImplementedError,
        z3.Z3Exception,
    ) as error:
        report = {
            "schema": "pono-modular-algebraic-certificate-report-v1",
            "btor2": args.btor2,
            "certificate": args.certificate,
            "ok": False,
            "error": str(error),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
