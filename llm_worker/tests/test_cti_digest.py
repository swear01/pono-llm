"""CTI digest prompt formatting and schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_worker.ic3_frame_schema import validate_batch_request
from llm_worker.prompt_format import format_cti_batch_all, format_cti_batch_digest


def _entries(n: int):
    out = []
    for i in range(n):
        out.append({
            "cti_id": f"f2_{i}",
            "cti": {
                "cube": {
                    "literals": [
                        {
                            "atom": {"ref": f"state{i % 5}", "rhs": "1"},
                            "polarity": True,
                        }
                    ]
                }
            },
        })
    return out


def test_validate_batch_with_digest():
    req = {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f2_a1",
        "frame_idx": 2,
        "cti_digest": {
            "cti_total": 509,
            "literal_stats": [{"lit": "state1=1", "count": 400}],
            "sample_cubes": [],
        },
        "cti_entries": _entries(2),
    }
    ok, err = validate_batch_request(req)
    assert ok, err


def test_digest_prompt_smaller_than_full():
    entries = _entries(100)
    digest = {
        "cti_total": 100,
        "literal_stats": [{"lit": "state1=1", "count": 80}],
        "sample_cubes": [],
    }
    full = format_cti_batch_all(entries)
    slim = format_cti_batch_digest(digest, entries[:4])
    assert len(slim) < len(full)
    assert "cti_total=100" in slim
    assert "High-frequency literals" in slim


if __name__ == "__main__":
    test_validate_batch_with_digest()
    test_digest_prompt_smaller_than_full()
    print("cti digest tests passed")
