from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_quokka_oracle_r1 as r1  # noqa: E402
import run_quokka_oracle_replication as runner  # noqa: E402
import validate_quokka_oracle_r1 as validator  # noqa: E402


def test_insertion_points_match_quokka_loop_contract(tmp_path):
    source = tmp_path / "loop.c"
    source.write_text("int main() {\n  while (x) {\n    x--;\n  }\n}\n")
    assert r1.insertion_points(source) == [2]


def test_valid_condition_rejects_assignment_but_accepts_equality():
    assert r1.valid_condition("x == 1 && y <= 2")
    assert not r1.valid_condition("x = 1")
    assert not r1.valid_condition("x++ < 2")


def test_transform_preserves_original_and_separates_assert_assume():
    source = b"int main() {\n while (x) {\n  x--;\n }\n __VERIFIER_assert(x == 0);\n}\n"
    assert runner.transform(source, 2, "x >= 0", "original") == source
    assertion = runner.transform(source, 2, "x >= 0", "assert")
    assumption = runner.transform(source, 2, "x >= 0", "assume")
    assert b"__VERIFIER_assert(x >= 0)" in assertion
    assert b"__VERIFIER_assert(x == 0)" not in assertion
    assert b"__VERIFIER_assume(x >= 0)" in assumption
    assert b"__VERIFIER_assert(x == 0)" in assumption


def test_classification_uses_raw_arms_without_fallback():
    def arms(original, assertion, assumption, times=(10.0, 2.0, 3.0)):
        return {name: {"verdict": result, "wall_time_sec": wall}
                for name, result, wall in zip(("original", "assert", "assume"),
                                              (original, assertion, assumption), times)}
    assert runner.classify(arms("TRUE", "FALSE", "TRUE")) == "G2_INVALID_INVARIANT"
    assert runner.classify(arms("TRUE", "TRUE", "UNKNOWN")) == "G3_CONSUMER_NO_CAPACITY"
    assert runner.classify(arms("TRUE", "TRUE", "TRUE")) == "PASS"
    assert runner.classify(arms("TRUE", "TRUE", "TRUE", (1.0, 2.0, 3.0))) == "G5_NEGATIVE_RUNTIME_UTILITY"
    assert runner.classify(arms("FALSE", "TRUE", "TRUE")) == "INFRASTRUCTURE_FAILURE"
    assert runner.classify(arms("TRUE", "ERROR", "ERROR")) == "INFRASTRUCTURE_FAILURE"


def test_metrics_parser_accepts_time_indentation():
    parsed = runner.parse_metrics("\tUser time (seconds): 1.25\n\tMaximum resident set size (kbytes): 42\n")
    assert parsed["user_cpu_sec"] == 1.25
    assert parsed["peak_memory_kib"] == 42


def test_canonical_r1_artifact_validates():
    summary = validator.validate(ROOT / "artifacts/external_quokka_oracle_r1")
    assert summary["decision"] == "STOP"
