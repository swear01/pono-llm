from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bv_poly_kernel as kernel  # noqa: E402
import cert_check  # noqa: E402


def test_independent_ite_products_enumerate_all_four_branches(tmp_path: Path) -> None:
    model_path = tmp_path / "four-branches.btor2"
    model_path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 input 1 a",
                "4 input 1 b",
                "5 zero 2",
                "6 one 2",
                "7 ite 2 3 5 6",
                "8 ite 2 4 5 6",
                "9 add 2 7 8",
                "10 state 2 x",
                "11 init 2 10 5",
                "12 next 2 10 9",
                "13 eq 1 10 5",
                "14 bad 13",
            ]
        )
        + "\n"
    )
    expanded = kernel.expand_polynomial_branches(
        cert_check.parse_btor2(model_path),
        9,
        width=8,
        polynomial_variables=(),
    )
    assert len(expanded) == 4
    assert {entry.decisions for entry in expanded} == {
        ((3, False), (4, False)),
        ((3, False), (4, True)),
        ((3, True), (4, False)),
        ((3, True), (4, True)),
    }


def test_polynomial_canonical_serialization_is_order_independent() -> None:
    terms = [
        {"coefficient": "1", "powers": {"y": 1, "x": 2}},
        {"coefficient": "257", "powers": {"x": 2, "y": 1}},
        {"coefficient": "-1", "powers": {}},
    ]
    polynomial = kernel.Polynomial.from_terms(
        8, terms, allowed_variables={"x", "y"}
    )
    assert polynomial.canonical_terms() == [
        {"coefficient": "255", "powers": {}},
        {"coefficient": "2", "powers": {"x": 2, "y": 1}},
    ]


def test_btor2_negation_normalizes_to_modular_coefficient(tmp_path: Path) -> None:
    model_path = tmp_path / "neg.btor2"
    model_path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 zero 2",
                "4 state 2 x",
                "5 init 2 4 3",
                "6 neg 2 4",
                "7 next 2 4 6",
                "8 eq 1 4 3",
                "9 bad 8",
            ]
        )
        + "\n"
    )
    branches = kernel.extract_transition_branches(
        cert_check.parse_btor2(model_path),
        width=8,
        polynomial_variables=("state4",),
        tracked_state_variables=("state4",),
        branch_cap=8,
    )
    assert branches[0].substitutions["state4"].canonical_terms() == [
        {"coefficient": "255", "powers": {"state4": 1}}
    ]


@pytest.mark.parametrize("operator", ["udiv", "urem", "slice"])
def test_unsupported_transition_operator_fails_closed(
    tmp_path: Path, operator: str
) -> None:
    operand = "7 6" if operator != "slice" else "7 7"
    operation = (
        f"8 {operator} 2 5 {operand}"
        if operator != "slice"
        else "8 slice 2 5 7 0"
    )
    model_path = tmp_path / f"{operator}.btor2"
    model_path.write_text(
        "\n".join(
            [
                "1 sort bitvec 1",
                "2 sort bitvec 8",
                "3 zero 2",
                "4 one 2",
                "5 state 2 x",
                "6 init 2 5 3",
                "7 constd 2 2",
                operation,
                "9 next 2 5 8",
                "10 eq 1 5 3",
                "11 bad 10",
            ]
        )
        + "\n"
    )
    with pytest.raises(kernel.UnsupportedPolynomialModel, match="unsupported"):
        kernel.extract_transition_branches(
            cert_check.parse_btor2(model_path),
            width=8,
            polynomial_variables=("state5",),
            tracked_state_variables=("state5",),
            branch_cap=8,
        )
