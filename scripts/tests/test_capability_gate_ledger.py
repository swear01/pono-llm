from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_capability_gate_ledger as build  # noqa: E402
import validate_capability_gate_ledger as validate  # noqa: E402


def test_canonical_ledger_builds_and_validates(tmp_path):
    ledger = build.build(
        ROOT / "scripts/capability_gate_catalog_v1.json",
        ROOT / "artifacts/capability_gate_ledger_v1/external_replication.json",
    )
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger))
    checked = validate.validate(path)
    assert checked["systems"] == ["CPAchecker", "Pono"]
    assert {"G0", "G1", "G2", "G3", "G5"} <= set(checked["stages_covered"])


def test_validator_rejects_tampered_ledger(tmp_path):
    ledger = build.build(
        ROOT / "scripts/capability_gate_catalog_v1.json",
        ROOT / "artifacts/capability_gate_ledger_v1/external_replication.json",
    )
    ledger["studies"][0]["decision"] = "GO"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="self-hash"):
        validate.validate(path, check_sources=False)


def test_strict_loader_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"a","schema":"b"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        build.load_strict(path)


def test_validator_rejects_working_tree_evidence_claimed_clean(tmp_path):
    ledger = build.build(
        ROOT / "scripts/capability_gate_catalog_v1.json",
        ROOT / "artifacts/capability_gate_ledger_v1/external_replication.json",
    )
    altered = copy.deepcopy(ledger)
    study = next(row for row in altered["studies"] if row["evidence_status"] == "working-tree-only")
    study["chronology"] = "commit-and-hash-bound"
    altered.pop("ledger_sha256")
    import hashlib
    altered["ledger_sha256"] = hashlib.sha256(build.canonical_bytes(altered)).hexdigest()
    path = tmp_path / "bad-provenance.json"
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="falsely classified"):
        validate.validate(path, check_sources=False)
