from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from quokka_expression_purity import is_pure_expression
from validate_quokka_soundness_audit import validate


def test_accepts_frozen_pure_controls():
    assert is_pure_expression("1", {"x"})
    assert is_pure_expression("0", {"x"})
    assert is_pure_expression("x >= 0", {"x"})
    assert is_pure_expression("!(x + 1 == 0) || x < 4", {"x"})


def test_rejects_frozen_attacks_and_assignment():
    assert not is_pure_expression("x = 0", {"x"})
    assert not is_pure_expression("(__VERIFIER_assume(0), 1)", {"x"})
    assert not is_pure_expression("prune_and_true()", {"x"})
    assert not is_pure_expression("PRUNE_TRUE()", {"x"})


def test_rejects_malformed_and_extended_c_forms():
    for expression in ("", "x +", "(x", "x)", "x[0]", "x.y", "*p", "x ? 1 : 0", "1U", "y"):
        assert not is_pure_expression(expression, {"x"})


def test_canonical_audit_artifact_validates():
    summary = validate(ROOT / "artifacts/quokka_soundness_v1", ROOT / "scripts/quokka_soundness_inputs_v1.json")
    assert summary["violation_confirmed"] is True
    assert summary["mitigation_control_pass"] is True
