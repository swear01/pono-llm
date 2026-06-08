"""batch_cti_total helper for sidecar logging."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_worker.prompt_format import batch_cti_total


def test_digest_cti_total_preferred():
    req = {
        "cti_digest": {"cti_total": 509},
        "cti_entries": [{"cti_id": "a"}, {"cti_id": "b"}],
    }
    assert batch_cti_total(req) == 509


def test_fallback_to_entries_len():
    req = {"cti_entries": [{"cti_id": "a"}, {"cti_id": "b"}, {"cti_id": "c"}]}
    assert batch_cti_total(req) == 3


def test_empty_request():
    assert batch_cti_total({}) == 0
