"""Tests for scripts/inspect_harness_packet.py."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inspect_harness_packet.py"


def test_inspect_json_output(tmp_path):
    req = {
        "type": "ic3_frame_batch_request",
        "batch_id": "batch_f1_a1",
        "frame_idx": 1,
        "attempt": 1,
        "cti_digest": {
            "cti_total": 10,
            "literal_stats": [{"lit": "state5=1", "count": 10}],
        },
        "init_raw": {"values": {"state5": "0"}},
        "cti_entries": [{"cti_id": "c0", "literals": ["state5=1"]}],
        "frame_snapshot": {"frame_idx": 1, "clauses_total": 3},
    }
    path = tmp_path / "requests.jsonl"
    path.write_text(json.dumps(req) + "\n")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "--json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(ROOT),
    )
    report = json.loads(proc.stdout)
    assert report["aggregate"]["requests"] == 1
    assert report["requests"][0]["metrics"]["has_init_raw"]
