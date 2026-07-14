from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_quokka_oracle_r1 as r1  # noqa: E402


def test_insertion_points_match_quokka_loop_contract(tmp_path):
    source = tmp_path / "loop.c"
    source.write_text("int main() {\n  while (x) {\n    x--;\n  }\n}\n")
    assert r1.insertion_points(source) == [2]


def test_valid_condition_rejects_assignment_but_accepts_equality():
    assert r1.valid_condition("x == 1 && y <= 2")
    assert not r1.valid_condition("x = 1")
    assert not r1.valid_condition("x++ < 2")
