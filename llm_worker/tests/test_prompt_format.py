"""Tests for compact sidecar prompt formatting."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt_format import format_cti_batch_all, format_cti_literals, format_frame_snapshot


def _sample_cti():
    return {
        "cube": {
            "form": "and",
            "literals": [
                {
                    "id": 0,
                    "form": "literal",
                    "atom": {"ref": "state15", "op": "eq", "rhs": "#b0"},
                    "polarity": False,
                },
                {
                    "id": 1,
                    "form": "literal",
                    "atom": {"ref": "state15", "op": "eq", "rhs": "#b0"},
                    "polarity": False,
                },
                {
                    "id": 2,
                    "form": "literal",
                    "atom": {"ref": "state81", "op": "eq", "rhs": "#b1"},
                    "polarity": True,
                },
            ],
        }
    }


def test_format_cti_literals_compact_and_deduped():
    text = format_cti_literals(_sample_cti())
    assert "CTI cube (2 literals" in text
    assert "!state15=0" in text
    assert "state81=1" in text
    assert text.count("state15") == 1
    assert len(text.encode()) < 500


def test_format_frame_snapshot_compact():
    snap = {
        "frame_idx": 2,
        "clauses": [
            {
                "clause_id": "F2_C0",
                "form": "or",
                "disjuncts": [
                    {
                        "form": "literal",
                        "atom": {"ref": "state93", "op": "eq", "rhs": "#b1"},
                        "polarity": True,
                    },
                    {
                        "form": "literal",
                        "atom": {"ref": "state538", "op": "eq", "rhs": "#b0"},
                        "polarity": False,
                    },
                ],
            }
        ],
    }
    text = format_frame_snapshot(snap)
    assert "frame_idx=2" in text
    assert "state93=1 | !state538=0" in text
    assert "clause_id" not in text
    assert len(text.encode()) < 500


def test_format_frame_snapshot_last_n():
    clauses = [
        {
            "clause_id": f"F2_C{i}",
            "disjuncts": [
                {
                    "atom": {"ref": f"state{i}", "rhs": "#b0"},
                    "polarity": False,
                }
            ],
        }
        for i in range(10)
    ]
    text = format_frame_snapshot({"frame_idx": 2, "clauses": clauses}, max_clauses=3)
    assert "showing last 3 of 10" in text
    assert "!state7=0" in text
    assert "!state0=0" not in text


def test_format_cti_batch_all():
    entries = [
        {"cti_id": "f1_a", "cti": _sample_cti()},
        {"cti_id": "f1_b", "cti": _sample_cti()},
    ]
    text = format_cti_batch_all(entries)
    assert "cti_total=2" in text
    assert "[f1_a]" in text
    assert "[f1_b]" in text
    assert "!state15=0" in text


def test_p040_fixture_sizes_if_available():
    path = Path("/tmp/p040_req.jsonl")
    if not path.exists():
        return
    req = json.loads(path.open().readlines()[1])
    cti_text = format_cti_literals(req.get("cti", {}))
    snap_text = format_frame_snapshot(req.get("frame_snapshot", {}))
    assert len(cti_text.encode()) < 8000
    assert len(snap_text.encode()) < 25000


if __name__ == "__main__":
    test_format_cti_literals_compact_and_deduped()
    test_format_frame_snapshot_compact()
    test_format_frame_snapshot_last_n()
    test_p040_fixture_sizes_if_available()
    print("All prompt_format tests passed")
