import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "llm_worker"))

import offline_repair_driver as drv


def test_extract_json_object_strips_markdown():
    row = drv.extract_json_object('```json\n{"keep_ids":[0],"drop_ids":[1]}\n```')
    assert row == {"keep_ids": [0], "drop_ids": [1]}


def test_normalize_proposal_filters_invalid_ids():
    cti = {"cti_id": "c1", "literals": [{"id": 0}, {"id": 1}, {"id": 2}]}
    raw = {"keep_ids": [0, 9], "drop_ids": [1, 9], "confidence": "high", "short_reason": "x"}
    row = drv.normalize_proposal(raw, cti)
    assert row["cti_id"] == "c1"
    assert row["keep_ids"] == [0]
    assert row["drop_ids"] == [1]


def test_normalize_proposal_infers_drop_ids():
    cti = {"cti_id": "c1", "literals": [{"id": 0}, {"id": 1}, {"id": 2}]}
    row = drv.normalize_proposal({"keep_ids": [2]}, cti)
    assert row["drop_ids"] == [0, 1]


def test_normalize_repair_allows_only_witness_diff_ids():
    req = {
        "cti_id": "c1",
        "failed_keep_ids": [0],
        "sat_witness_diff": [{"literal_id": 1}, {"literal_id": 3}],
    }
    row = drv.normalize_repair({"add_back_ids": [1, 2, 3]}, req)
    assert row["base_keep_ids"] == [0]
    assert row["add_back_ids"] == [1, 3]


def test_jsonl_roundtrip(tmp_path):
    path = tmp_path / "x.jsonl"
    drv.append_jsonl(path, {"b": 2, "a": 1})
    assert drv.read_jsonl(path) == [{"a": 1, "b": 2}]
