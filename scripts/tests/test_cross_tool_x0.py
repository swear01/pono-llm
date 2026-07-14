from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_cross_tool_x0 as build  # noqa: E402
import cross_tool_x0_schema as schema  # noqa: E402
import validate_cross_tool_x0 as validate  # noqa: E402


CATALOG = ROOT / "scripts/cross_tool_candidate_catalog_v1.json"
CENSUS = ROOT / "scripts/cross_tool_x0_census_v1.json"
ARTIFACT = ROOT / "artifacts/cross_tool_x0_v1"
RETRIEVAL = ARTIFACT / "retrieval/retrieval_freeze.json"


def load_inputs() -> tuple[dict[str, object], dict[str, object]]:
    catalog = schema.validate_catalog(CATALOG)
    retrieval = schema.validate_retrieval_manifest(RETRIEVAL)
    return catalog, retrieval


def rewrite_integrity(directory: Path) -> None:
    (directory / "integrity.json").unlink()
    build.write_integrity(directory)


def test_preregistered_inputs_validate() -> None:
    catalog, retrieval = load_inputs()
    census = schema.validate_census(CENSUS, catalog, retrieval)
    assert set(schema.census_candidate_index(census)) == set(
        schema.EXPECTED_CANDIDATES
    )
    assert census["execution"]["new_llm_api_calls"] == 0


def test_canonical_bundle_validates_and_stops() -> None:
    summary = validate.validate(ARTIFACT)
    assert summary["decision"] == "STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS"
    assert summary["x1_authorized"] is False
    assert summary["eligible_candidate_ids"] == []
    assert summary["field_state_totals"] == {
        "ambiguous": 12,
        "available": 36,
        "blocked": 0,
        "missing": 22,
    }
    assert {
        report["candidate_id"]: report["available_count"]
        for report in summary["reports"]
    } == {
        "autoverus": 10,
        "cill": 8,
        "exverus": 4,
        "loris": 7,
        "quokka": 7,
    }


def test_strict_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        schema.load_strict(path)


def test_census_rejects_missing_required_field(tmp_path: Path) -> None:
    catalog, retrieval = load_inputs()
    census = copy.deepcopy(schema.load_strict(CENSUS))
    del census["candidates"][0]["fields"]["license"]
    census["census_sha256"] = schema.document_sha256(census, "census_sha256")
    path = tmp_path / "census.json"
    path.write_text(json.dumps(census))
    with pytest.raises(ValueError, match="field set mismatch"):
        schema.validate_census(path, catalog, retrieval)


def test_census_rejects_cross_candidate_evidence(tmp_path: Path) -> None:
    catalog, retrieval = load_inputs()
    census = copy.deepcopy(schema.load_strict(CENSUS))
    census["candidates"][0]["fields"]["license"]["evidence"][0][
        "repository"
    ] = "microsoft/verus-proof-synthesis"
    census["census_sha256"] = schema.document_sha256(census, "census_sha256")
    path = tmp_path / "census.json"
    path.write_text(json.dumps(census))
    with pytest.raises(ValueError, match="outside its candidate"):
        schema.validate_census(path, catalog, retrieval)


def test_validator_recomputes_summary_decision(tmp_path: Path) -> None:
    copied = tmp_path / "artifact"
    shutil.copytree(ARTIFACT, copied)
    summary_path = copied / "summary.json"
    summary = schema.load_strict(summary_path)
    assert isinstance(summary, dict)
    summary["decision"] = "GO_X1"
    summary["x1_authorized"] = True
    summary["summary_sha256"] = schema.document_sha256(summary, "summary_sha256")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rewrite_integrity(copied)
    with pytest.raises(ValueError, match="preregistered threshold"):
        validate.validate(copied)


def test_validator_recomputes_candidate_eligibility(tmp_path: Path) -> None:
    copied = tmp_path / "artifact"
    shutil.copytree(ARTIFACT, copied)
    report_path = copied / "reports/autoverus.json"
    report = schema.load_strict(report_path)
    assert isinstance(report, dict)
    report["full_audit_eligible"] = True
    report["report_sha256"] = schema.document_sha256(report, "report_sha256")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    rewrite_integrity(copied)
    with pytest.raises(ValueError, match="eligibility mismatch"):
        validate.validate(copied)


def test_validator_rejects_pre_preregistration_builder_commit(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "artifact"
    shutil.copytree(ARTIFACT, copied)
    provenance_path = copied / "provenance.json"
    provenance = schema.load_strict(provenance_path)
    assert isinstance(provenance, dict)
    provenance["builder_parent_commit"] = (
        "8e5e050b6898f06a01e82108950925996eedcbcb"
    )
    provenance["provenance_sha256"] = schema.document_sha256(
        provenance, "provenance_sha256"
    )
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    rewrite_integrity(copied)
    with pytest.raises(ValueError, match="does not descend"):
        validate.validate(copied)


def test_validator_rejects_bundled_raw_retrieval_payload(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "artifact"
    shutil.copytree(ARTIFACT, copied)
    raw_directory = copied / "retrieval/github"
    raw_directory.mkdir()
    (raw_directory / "unexpected.json").write_text("{}\n")
    rewrite_integrity(copied)
    with pytest.raises(ValueError, match="must not contain raw retrieval"):
        validate.validate(copied)
