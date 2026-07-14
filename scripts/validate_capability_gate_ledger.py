#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from build_capability_gate_ledger import SCHEMA, canonical_bytes, load_strict, resolve, sha256_file

STAGES = {f"G{index}" for index in range(7)}
FAILURES = {"NO_POPULATION", "UNSUPPORTED_REPRESENTATION", "PARSE_OR_BINDING_FAILURE",
            "INITIAL_FALSE", "REACHABLE_COUNTEREXAMPLE", "NON_INDUCTIVE",
            "CONSUMER_NO_CAPACITY", "PROPERTY_INSUFFICIENT", "NEGATIVE_RUNTIME_UTILITY",
            "NO_LLM_MARGINAL_VALUE", "PASS"}


def validate(path: Path, check_sources: bool = True) -> dict[str, object]:
    ledger = load_strict(path)
    if not isinstance(ledger, dict) or ledger.get("schema") != SCHEMA:
        raise ValueError("unsupported ledger schema")
    saved = ledger.get("ledger_sha256")
    unhashed = dict(ledger)
    unhashed.pop("ledger_sha256", None)
    actual = hashlib.sha256(canonical_bytes(unhashed)).hexdigest()
    if saved != actual:
        raise ValueError("ledger self-hash mismatch")
    studies = ledger.get("studies")
    if not isinstance(studies, list) or ledger.get("study_count") != len(studies):
        raise ValueError("study count mismatch")
    ids: set[str] = set()
    for study in studies:
        sid = study.get("study_id")
        if sid in ids:
            raise ValueError(f"duplicate study_id: {sid}")
        ids.add(sid)
        if study.get("stage") not in STAGES:
            raise ValueError(f"invalid stage: {study.get('stage')}")
        if study.get("failure_class") not in FAILURES:
            raise ValueError(f"invalid failure class: {study.get('failure_class')}")
        if study.get("decision") not in {"GO", "STOP", "INCONCLUSIVE"}:
            raise ValueError(f"invalid decision: {study.get('decision')}")
        if (study["failure_class"] == "PASS") != (study["decision"] == "GO"):
            raise ValueError(f"PASS/GO inconsistency: {sid}")
        if study.get("evidence_status") == "working-tree-only" and "working-tree" not in study.get("chronology", ""):
            raise ValueError(f"untracked evidence falsely classified: {sid}")
        if check_sources:
            for field in ("population_manifest", "result_artifact"):
                evidence = study[field]
                if sha256_file(resolve(evidence)) != evidence["sha256"]:
                    raise ValueError(f"source hash mismatch: {sid}/{field}")
    external = ledger.get("prospective_external_replication")
    if not isinstance(external, dict) or external.get("decision") not in {
        "GO", "STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE"
    }:
        raise ValueError("invalid prospective replication decision")
    return ledger


def validate_integrity(directory: Path) -> dict[str, object]:
    manifest = load_strict(directory / "integrity.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != "oracle-first-capability-integrity-v1":
        raise ValueError("unsupported integrity schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("integrity files must be a non-empty object")
    actual_names = {path.name for path in directory.iterdir() if path.is_file() and path.name != "integrity.json"}
    if set(files) != actual_names:
        raise ValueError("integrity file set mismatch")
    for name, expected in files.items():
        if sha256_file(directory / name) != expected:
            raise ValueError(f"integrity hash mismatch: {name}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "artifacts/capability_gate_ledger_v1/ledger.json")
    parser.add_argument("--no-source-check", action="store_true")
    args = parser.parse_args()
    ledger = validate(args.ledger, not args.no_source_check)
    validate_integrity(args.ledger.parent)
    print(f"valid {args.ledger} ({ledger['study_count']} studies, {ledger['ledger_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
