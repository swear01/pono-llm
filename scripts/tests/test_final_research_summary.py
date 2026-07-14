from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_final_research_summary as validate  # noqa: E402


SUMMARY_PATH = ROOT / "artifacts/final_research_summary_v1.json"


def rehash(document: dict[str, object]) -> dict[str, object]:
    document["summary_sha256"] = validate.summary_sha256(document)
    return document


def test_canonical_summary_validates():
    checked = validate.validate(SUMMARY_PATH)
    assert checked["program"]["status"] == "closed"
    assert checked["closure_record"]["new_llm_or_api_calls"] == 0
    assert checked["future_work_boundary"]["gate6_authorized"] is False


def test_validator_rejects_tampered_self_hash(tmp_path):
    document = validate.load_strict(SUMMARY_PATH)
    document["final_scoped_conclusion"] = "tampered"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="self-hash"):
        validate.validate(path)


def test_validator_rejects_nonzero_llm_calls():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    document["closure_record"]["new_llm_or_api_calls"] = 1
    rehash(document)
    with pytest.raises(ValueError, match="zero new LLM/API calls"):
        validate.validate_document(document, ROOT)


def test_validator_rejects_authorized_follow_on():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    document["gates"][0]["authorized_follow_on"] = ["Gate 6"]
    rehash(document)
    with pytest.raises(ValueError, match="authorized_follow_on must be empty"):
        validate.validate_document(document, ROOT)


def test_validator_rejects_unsafe_path():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    document["claim_ledger"]["path"] = "../outside.md"
    rehash(document)
    with pytest.raises(ValueError, match="repository-relative"):
        validate.validate_document(document, ROOT)


def test_validator_rejects_referenced_file_hash_mismatch():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    document["claim_ledger"]["sha256"] = "0" * 64
    rehash(document)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate.validate_document(document, ROOT)


def test_validator_rejects_wrong_evidence_path_set():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    gate = next(row for row in document["gates"] if row["gate_id"] == "S2")
    gate["evidence"] = [
        {
            "kind": "wrong-source",
            "path": "artifacts/gate2_summary_v1.json",
            "sha256": validate.sha256_file(ROOT / "artifacts/gate2_summary_v1.json"),
        }
    ]
    rehash(document)
    with pytest.raises(ValueError, match="evidence path set mismatch"):
        validate.validate_document(document, ROOT)


def test_source_semantics_rejects_changed_phase1_decision(tmp_path):
    target = tmp_path / "artifacts/phase1_2_summary_v1.json"
    target.parent.mkdir(parents=True)
    source = json.loads((ROOT / "artifacts/phase1_2_summary_v1.json").read_text())
    source["matched_set_equal"] = False
    target.write_text(json.dumps(source))
    with pytest.raises(ValueError, match=r"Phase 1\+2 source semantics mismatch"):
        validate.validate_source_semantics(tmp_path)


def test_validator_rejects_missing_gate():
    document = copy.deepcopy(validate.load_strict(SUMMARY_PATH))
    document["gates"].pop()
    rehash(document)
    with pytest.raises(ValueError, match="gate order/set mismatch"):
        validate.validate_document(document, ROOT)


def test_strict_loader_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"a","schema":"b"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        validate.load_strict(path)
