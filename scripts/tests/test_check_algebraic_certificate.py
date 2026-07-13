from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(TEST_DIR))

import bv_poly_kernel as kernel  # noqa: E402
import check_algebraic_certificate as checker  # noqa: E402
from test_algebraic_certificate_gate import (  # noqa: E402
    term,
    triangular_btor2,
    triangular_certificate,
)


def complete_certificate(model_path: Path) -> dict:
    certificate = triangular_certificate(model_path)
    certificate["candidate_sha256"] = checker._canonical_sha256(
        certificate["invariants"]
    )
    model = checker.cert_check.parse_btor2(model_path)
    branches = kernel.extract_transition_branches(
        model,
        width=certificate["width"],
        polynomial_variables=certificate["variables"],
        tracked_state_variables=("state6", "state7"),
        branch_cap=8,
    )
    supplied = {branch["id"]: branch for branch in certificate["branches"]}
    certificate["branches"] = [
        {
            "id": branch.branch_id,
            "guard_identity": kernel.guard_identity(branch.decisions),
            "next_state_substitution": {
                name: polynomial.canonical_terms() or [term(0)]
                for name, polynomial in sorted(branch.substitutions.items())
            },
            "multipliers": supplied[branch.branch_id]["multipliers"],
        }
        for branch in branches
    ]
    return certificate


def test_certificate_binds_candidate_guard_and_complete_substitution(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    report = checker.check_certificate(
        model_path, complete_certificate(model_path), timeout_ms=5_000
    )
    assert report["ok"] is True
    assert report["candidate_sha256"] == checker._canonical_sha256(
        complete_certificate(model_path)["invariants"]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda certificate: certificate.__setitem__(
                "candidate_sha256", "0" * 64
            ),
            "candidate SHA-256 mismatch",
        ),
        (
            lambda certificate: certificate["branches"][0].__setitem__(
                "guard_identity", "g-" + "0" * 16
            ),
            "guard identity mismatch",
        ),
        (
            lambda certificate: certificate["branches"][0][
                "next_state_substitution"
            ].pop("state6"),
            "next-state substitution",
        ),
        (
            lambda certificate: certificate["branches"][0][
                "next_state_substitution"
            ]["state6"].append(term(1)),
            "next-state substitution mismatch",
        ),
    ],
)
def test_provenance_or_substitution_tampering_is_rejected(
    tmp_path: Path, mutation, message: str
) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = complete_certificate(model_path)
    mutation(certificate)
    with pytest.raises(ValueError, match=message):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)


def test_missing_multiplier_cell_duplicate_branch_and_unknown_variable_reject(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)

    missing = complete_certificate(model_path)
    missing["branches"][0]["multipliers"][0].clear()
    with pytest.raises(ValueError, match="multiplier row"):
        checker.check_certificate(model_path, missing, timeout_ms=5_000)

    duplicate = complete_certificate(model_path)
    duplicate["branches"].append(copy.deepcopy(duplicate["branches"][0]))
    with pytest.raises(ValueError, match="duplicate branch id"):
        checker.check_certificate(model_path, duplicate, timeout_ms=5_000)

    unknown = complete_certificate(model_path)
    unknown["variables"].append("state999")
    with pytest.raises(ValueError, match="does not name a BTOR2 state"):
        checker.check_certificate(model_path, unknown, timeout_ms=5_000)


def test_malformed_json_cli_fails_closed(tmp_path: Path, capsys) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate_path = tmp_path / "malformed.json"
    certificate_path.write_text("{not-json")
    result = checker.main([str(model_path), str(certificate_path)])
    report = json.loads(capsys.readouterr().out)
    assert result == 2
    assert report["ok"] is False


def test_certificate_hashes_are_lowercase_sha256(tmp_path: Path) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = complete_certificate(model_path)
    report = checker.check_certificate(model_path, certificate, timeout_ms=5_000)
    assert report["benchmark_content_sha256"] == hashlib.sha256(
        model_path.read_bytes()
    ).hexdigest()
    assert len(report["certificate_sha256"]) == 64
