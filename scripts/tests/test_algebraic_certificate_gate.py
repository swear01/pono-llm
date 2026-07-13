from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bv_poly_kernel as kernel  # noqa: E402
import check_algebraic_certificate as checker  # noqa: E402
import build_algebraic_population as population  # noqa: E402
import build_algebraic_query_corpus as query_corpus  # noqa: E402
import run_algebraic_baselines as baselines  # noqa: E402
import run_algebraic_negative_suite as negative_suite  # noqa: E402
import run_algebraic_pono_baseline as pono_baseline  # noqa: E402


def term(coefficient: int, **powers: int) -> dict:
    return {
        "coefficient": str(coefficient),
        "powers": {name: exponent for name, exponent in powers.items()},
    }


def triangular_btor2(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 input 1 rst",
                "4 zero 2",
                "5 one 2",
                "6 state 2 i",
                "7 state 2 sum",
                "8 init 2 6 4",
                "9 init 2 7 4",
                "10 add 2 6 5",
                "11 add 2 7 6",
                "12 ite 2 3 4 10",
                "13 ite 2 3 4 11",
                "14 next 2 6 12",
                "15 next 2 7 13",
                "16 add 2 7 7",
                "17 sub 2 6 5",
                "18 mul 2 6 17",
                "19 neq 1 16 18",
                "20 bad 19",
                "21 input 2 aux",
            ]
        )
        + "\n"
    )


def triangular_certificate(model_path: Path) -> dict:
    model = checker.cert_check.parse_btor2(model_path)
    branches = kernel.extract_transition_branches(
        model,
        width=8,
        polynomial_variables=("state6", "state7"),
        tracked_state_variables=("state6", "state7"),
        branch_cap=8,
    )
    rows = []
    for branch in branches:
        reset = branch.substitutions["state6"].is_zero()
        rows.append(
            {
                "id": branch.branch_id,
                "guard_identity": kernel.guard_identity(branch.decisions),
                "next_state_substitution": {
                    name: polynomial.canonical_terms() or [term(0)]
                    for name, polynomial in sorted(branch.substitutions.items())
                },
                "multipliers": [[[term(0 if reset else 1)]]],
            }
        )
    invariants = [
        {
            "id": "P0",
            "terms": [
                term(2, state7=1),
                term(-1, state6=2),
                term(1, state6=1),
            ],
        }
    ]
    return {
        "schema": checker.SCHEMA,
        "benchmark_id": "micro/triangular.btor2",
        "benchmark_content_sha256": hashlib.sha256(
            model_path.read_bytes()
        ).hexdigest(),
        "candidate_sha256": checker._canonical_sha256(invariants),
        "width": 8,
        "variables": ["state6", "state7"],
        "invariants": invariants,
        "branches": rows,
    }


def test_sparse_polynomial_normalizes_coefficients_modulo_width() -> None:
    poly = kernel.Polynomial.from_terms(
        4,
        [term(1, x=1), term(15, x=1), term(-1), term(17)],
        allowed_variables={"x"},
    )
    assert poly.is_zero()


def test_polynomial_substitution_proves_triangular_update_identity() -> None:
    width = 8
    i = kernel.Polynomial.variable(width, "i")
    total = kernel.Polynomial.variable(width, "sum")
    one = kernel.Polynomial.constant(width, 1)
    invariant = total.scale(2) - i * (i - one)
    update = invariant.substitute({"i": i + one, "sum": total + i})
    assert update == invariant
    reset = invariant.substitute(
        {"i": kernel.Polynomial.zero(width), "sum": kernel.Polynomial.zero(width)}
    )
    assert reset.is_zero()


def test_multiplier_matrix_supports_mutually_inductive_basis() -> None:
    width = 8
    x = kernel.Polynomial.variable(width, "x")
    y = kernel.Polynomial.variable(width, "y")
    basis = (x, y)
    substitutions = {"x": x + y, "y": y}
    multipliers = (
        (
            kernel.Polynomial.constant(width, 1),
            kernel.Polynomial.constant(width, 1),
        ),
        (
            kernel.Polynomial.zero(width),
            kernel.Polynomial.constant(width, 1),
        ),
    )
    assert kernel.check_multiplier_identity(basis, substitutions, multipliers) == ()


def test_transition_extractor_enumerates_shared_ite_branches(tmp_path: Path) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    model = checker.cert_check.parse_btor2(model_path)
    branches = kernel.extract_transition_branches(
        model,
        width=8,
        polynomial_variables=("state6", "state7"),
        tracked_state_variables=("state6", "state7"),
        branch_cap=8,
    )
    assert len(branches) == 2
    assert len({branch.branch_id for branch in branches}) == 2
    assert {branch.decisions for branch in branches} == {
        ((3, False),),
        ((3, True),),
    }


def test_end_to_end_certificate_accepts_exact_modular_identity(tmp_path: Path) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    report = checker.check_certificate(
        model_path,
        triangular_certificate(model_path),
        timeout_ms=5_000,
    )
    assert report["ok"] is True
    assert [check["result"] for check in report["checks"]] == [
        "unsat",
        "accepted",
        "unsat",
    ]


def test_wrong_multiplier_and_missing_branch_are_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = triangular_certificate(model_path)
    certificate["branches"][0]["multipliers"] = [[[term(7)]]]
    report = checker.check_certificate(model_path, certificate, timeout_ms=5_000)
    assert report["ok"] is False
    assert report["checks"][1]["result"] == "rejected"

    certificate = triangular_certificate(model_path)
    certificate["branches"].pop()
    with pytest.raises(ValueError, match="branch set mismatch"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)


def test_schema_rejects_unknown_fields_zero_invariant_and_bad_hash(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = triangular_certificate(model_path)
    certificate["unexpected"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)

    certificate = triangular_certificate(model_path)
    certificate["invariants"][0]["terms"] = [term(0)]
    with pytest.raises(ValueError, match="zero polynomial"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)

    certificate = triangular_certificate(model_path)
    certificate["benchmark_content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content SHA-256 mismatch"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)


def test_nonconstant_extension_and_mixed_width_state_are_unsupported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsupported.btor2"
    path.write_text(
        "\n".join(
            [
                "1 sort bitvec 8",
                "2 sort bitvec 16",
                "3 state 1 x",
                "4 uext 2 3 8",
                "5 state 2 y",
                "6 next 2 5 4",
                "7 zero 1",
                "8 init 1 3 7",
                "9 zero 2",
                "10 init 2 5 9",
                "11 bad 3",
            ]
        )
        + "\n"
    )
    model = checker.cert_check.parse_btor2(path)
    with pytest.raises(kernel.UnsupportedPolynomialModel, match="uext"):
        kernel.extract_transition_branches(
            model,
            width=16,
            polynomial_variables=("state5",),
            tracked_state_variables=("state5",),
            branch_cap=8,
        )


def test_cli_reports_rejection_without_repair(tmp_path: Path, capsys) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = triangular_certificate(model_path)
    certificate["branches"][0]["multipliers"] = [[[term(3)]]]
    cert_path = tmp_path / "certificate.json"
    cert_path.write_text(json.dumps(certificate))
    result = checker.main(
        [str(model_path), str(cert_path), "--timeout-ms", "5000"]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == 1
    assert output["ok"] is False
    assert "repaired" not in json.dumps(output).lower()


def test_checker_rejects_wrong_width_input_invariant_and_missing_next(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)

    certificate = triangular_certificate(model_path)
    certificate["width"] = 7
    with pytest.raises(ValueError, match="certificate declares 7"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)

    certificate = triangular_certificate(model_path)
    certificate["variables"].append("input21")
    certificate["invariants"][0]["terms"].append(term(1, input21=1))
    with pytest.raises(ValueError, match="step-local inputs"):
        checker.check_certificate(model_path, certificate, timeout_ms=5_000)

    missing_next = tmp_path / "missing-next.btor2"
    missing_next.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 zero 2",
                "4 state 2 x",
                "5 init 2 4 3",
                "6 eq 1 4 3",
                "7 bad 6",
            ]
        )
        + "\n"
    )
    model = checker.cert_check.parse_btor2(missing_next)
    with pytest.raises(kernel.UnsupportedPolynomialModel, match="no functional next"):
        kernel.extract_transition_branches(
            model,
            width=8,
            polynomial_variables=("state4",),
            tracked_state_variables=("state4",),
            branch_cap=8,
        )


def test_kernel_does_not_use_integer_cancellation_and_wraps_exactly() -> None:
    width = 4
    x = kernel.Polynomial.variable(width, "x")
    one = kernel.Polynomial.constant(width, 1)
    eight = kernel.Polynomial.constant(width, 8)
    identity = ((one,),)

    errors = kernel.check_multiplier_identity((x,), {"x": x + eight}, identity)
    assert errors == ("P0 branch identity mismatch",)

    doubled = x.scale(2)
    assert kernel.check_multiplier_identity(
        (doubled,), {"x": x + eight}, identity
    ) == ()
    assert x + kernel.Polynomial.constant(width, 16) == x


def _single_state_model(path: Path, *, unsafe: bool, initial: int = 0) -> None:
    bad_value = initial if unsafe else 1 - initial
    path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                f"3 constd 2 {initial}",
                f"4 constd 2 {bad_value}",
                "5 state 2 x",
                "6 init 2 5 3",
                "7 next 2 5 5",
                "8 eq 1 5 4",
                "9 bad 8",
            ]
        )
        + "\n"
    )


def _single_state_certificate(path: Path, constant: int) -> dict:
    model = checker.cert_check.parse_btor2(path)
    branches = kernel.extract_transition_branches(
        model,
        width=8,
        polynomial_variables=("state5",),
        tracked_state_variables=("state5",),
        branch_cap=8,
    )
    return {
        "schema": checker.SCHEMA,
        "benchmark_id": "micro/single.btor2",
        "benchmark_content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "candidate_sha256": checker._canonical_sha256(
            [
                {
                    "id": "P0",
                    "terms": [term(1, state5=1), term(-constant)],
                }
            ]
        ),
        "width": 8,
        "variables": ["state5"],
        "invariants": [
            {
                "id": "P0",
                "terms": [term(1, state5=1), term(-constant)],
            }
        ],
        "branches": [
            {
                "id": branches[0].branch_id,
                "guard_identity": kernel.guard_identity(branches[0].decisions),
                "next_state_substitution": {
                    name: polynomial.canonical_terms() or [term(0)]
                    for name, polynomial in sorted(
                        branches[0].substitutions.items()
                    )
                },
                "multipliers": [[[term(1)]]],
            }
        ],
    }


def test_false_initial_candidate_and_unsafe_model_never_certify(tmp_path: Path) -> None:
    safe_path = tmp_path / "safe.btor2"
    _single_state_model(safe_path, unsafe=False, initial=0)
    false_initial = checker.check_certificate(
        safe_path, _single_state_certificate(safe_path, 1), timeout_ms=5_000
    )
    assert false_initial["ok"] is False
    assert false_initial["checks"][0]["result"] == "sat"
    assert false_initial["checks"][1]["result"] == "accepted"

    unsafe_path = tmp_path / "unsafe.btor2"
    _single_state_model(unsafe_path, unsafe=True, initial=0)
    unsafe = checker.check_certificate(
        unsafe_path, _single_state_certificate(unsafe_path, 0), timeout_ms=5_000
    )
    assert unsafe["ok"] is False
    assert unsafe["checks"][2]["result"] == "sat"


def test_population_component_detector_finds_nonlinear_scc_and_enforces_cap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nonlinear.btor2"
    path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 input 1 branch",
                "4 zero 2",
                "5 state 2 x",
                "6 init 2 5 4",
                "7 mul 2 5 5",
                "8 ite 2 3 7 5",
                "9 next 2 5 8",
                "10 eq 1 5 4",
                "11 bad 10",
            ]
        )
        + "\n"
    )
    model = checker.cert_check.parse_btor2(path)
    components, diagnostics = population._task_components(model, branch_cap=2)
    assert len(components) == 1
    assert components[0]["maximum_update_degree"] == 2
    assert components[0]["branch_count"] == 2
    assert diagnostics["eligible-component"] == 1

    components, diagnostics = population._task_components(model, branch_cap=1)
    assert components == []
    assert diagnostics["nonlinear-scc-over-branch-cap"] == 1


def test_query_corpus_binds_accepted_certificate_and_python_solver(
    tmp_path: Path,
) -> None:
    benchmark_root = tmp_path / "benchmarks"
    model_path = benchmark_root / "micro" / "triangular.btor2"
    model_path.parent.mkdir(parents=True)
    triangular_btor2(model_path)
    certificate = triangular_certificate(model_path)
    certificate_directory = tmp_path / "certificates"
    certificate_directory.mkdir()
    certificate_path = certificate_directory / "triangular.certificate.json"
    certificate_path.write_text(json.dumps(certificate))
    source_manifest = {
        "schema": "pono-modular-algebraic-development-controls-v1",
        "controls": [
            {
                "benchmark_id": "micro/triangular.btor2",
                "certificate": "triangular.certificate.json",
                "certificate_sha256": checker._canonical_sha256(certificate),
                "certificate_file_sha256": hashlib.sha256(
                    certificate_path.read_bytes()
                ).hexdigest(),
            }
        ],
    }
    (certificate_directory / "manifest.json").write_text(
        json.dumps(source_manifest)
    )
    output_directory = tmp_path / "queries"
    manifest = query_corpus.build_query_corpus(
        benchmark_root,
        certificate_directory,
        output_directory,
        timeout_ms=5_000,
    )
    assert manifest["query_count"] == 1
    query = manifest["queries"][0]
    query_path = output_directory / query["query"]
    assert hashlib.sha256(query_path.read_bytes()).hexdigest() == query["query_sha256"]
    worker = baselines.python_worker(query_path, 5_000)
    assert worker["result"] == "unsat"


def test_solver_result_parser_and_frozen_polysat_configuration() -> None:
    assert baselines._solver_result("unsat\n(:time 0.01)\n") == "unsat"
    assert baselines._solver_result("diagnostic only") == "error"
    assert baselines.POLYSAT_COMMIT == (
        "16fb86b636047fd79ad5827f768b6f26d8812948"
    )
    assert baselines.POLYSAT_OPTIONS == (
        "sat.smt=true",
        "tactic.default_tactic=smt",
        "smt.bv.solver=1",
    )


def test_generic_c2_query_and_python_worker_agree_with_kernel(tmp_path: Path) -> None:
    model_path = tmp_path / "triangular.btor2"
    triangular_btor2(model_path)
    certificate = triangular_certificate(model_path)
    formula = query_corpus.certificate_c2_formula(model_path, certificate)
    query = query_corpus.formula_to_smt2(formula)
    query_path = tmp_path / "triangular.c2.smt2"
    query_path.write_text(query)
    result = baselines.python_worker(query_path, 2_000)
    assert result["result"] == "unsat"
    assert "(check-sat)" in query
    certificate_report = checker.check_certificate(
        model_path, certificate, timeout_ms=2_000
    )
    assert certificate_report["checks"][1]["result"] == "accepted"

    assert baselines.main(
        ["--python-worker", str(query_path), "--timeout-ms", "2000"]
    ) == 0


def test_solver_result_parser_does_not_infer_a_verdict() -> None:
    assert baselines._solver_result("diagnostic\nunsat\n") == "unsat"
    assert baselines._solver_result("diagnostic only\n") == "error"


def test_declared_nonbasis_state_does_not_require_a_next_function(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "declared-helper.btor2"
    model_path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 zero 2",
                "4 state 2 x",
                "5 state 2 helper",
                "6 init 2 4 3",
                "7 init 2 5 3",
                "8 next 2 4 4",
                "9 neq 1 4 3",
                "10 bad 9",
            ]
        )
        + "\n"
    )
    model = checker.cert_check.parse_btor2(model_path)
    branches = kernel.extract_transition_branches(
        model,
        width=8,
        polynomial_variables=("state4", "state5"),
        tracked_state_variables=("state4",),
        branch_cap=8,
    )
    invariants = [{"id": "P0", "terms": [term(1, state4=1)]}]
    certificate = {
        "schema": checker.SCHEMA,
        "benchmark_id": "micro/declared-helper.btor2",
        "benchmark_content_sha256": hashlib.sha256(
            model_path.read_bytes()
        ).hexdigest(),
        "candidate_sha256": checker._canonical_sha256(invariants),
        "width": 8,
        "variables": ["state4", "state5"],
        "invariants": invariants,
        "branches": [
            {
                "id": branches[0].branch_id,
                "guard_identity": kernel.guard_identity(branches[0].decisions),
                "next_state_substitution": {
                    "state4": branches[0].substitutions[
                        "state4"
                    ].canonical_terms()
                },
                "multipliers": [[[term(1)]]],
            }
        ],
    }
    assert checker.check_certificate(
        model_path, certificate, timeout_ms=2_000
    )["ok"]


def test_polynomial_basis_has_a_deterministic_pono_predicate_encoding() -> None:
    ast = pono_baseline.polynomial_ast(
        [term(2, state7=1), term(-1, state7=2), term(1)],
        8,
    )
    assert ast["form"] == "eq"
    assert ast["args"][1] == {"form": "const", "width": 8, "const": "0"}
    assert "state7" in json.dumps(ast, sort_keys=True)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("unsafe", "C3-sat"),
        ("false-initial", "C1-sat"),
        ("unsupported-division", "schema-or-model-error"),
        ("missing-next", "schema-or-model-error"),
    ],
)
def test_negative_controls_reach_the_expected_rejection_stage(
    tmp_path: Path, mode: str, expected: str
) -> None:
    model_path = tmp_path / f"{mode}.btor2"
    document = negative_suite._synthetic_model(model_path, mode)
    result = negative_suite._run_case(
        mode,
        model_path,
        document,
        timeout_ms=2_000,
        expected_rejection=expected,
    )
    assert result["accepted"] is False
    assert result["expectation_met"] is True
