#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "oracle-first-capability-ledger-v1"


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_strict(path: Path) -> object:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=hook)


def resolve(record: dict[str, str]) -> Path:
    return Path(record.get("root", str(ROOT))) / record["path"]


def build(catalog_path: Path, external_path: Path) -> dict[str, object]:
    catalog = load_strict(catalog_path)
    if not isinstance(catalog, dict) or catalog.get("schema") != "oracle-first-capability-catalog-v1":
        raise ValueError("unsupported catalog schema")
    studies = catalog.get("studies")
    if not isinstance(studies, list):
        raise ValueError("studies must be a list")
    checked = []
    for study in studies:
        if not isinstance(study, dict):
            raise ValueError("study must be an object")
        for field in ("population_manifest", "result_artifact"):
            evidence = study[field]
            path = resolve(evidence)
            actual = sha256_file(path)
            if actual != evidence["sha256"]:
                raise ValueError(f"{study['study_id']} {field} SHA-256 mismatch: {actual}")
        checked.append(study)
    external = load_strict(external_path)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    ledger: dict[str, object] = {
        "schema": SCHEMA,
        "catalog_file_sha256": sha256_file(catalog_path),
        "builder_commit": commit,
        "study_count": len(checked),
        "systems": sorted({study["system"] for study in checked}),
        "stages_covered": sorted({study["stage"] for study in checked}),
        "studies": checked,
        "prospective_external_replication": external,
    }
    ledger["ledger_sha256"] = hashlib.sha256(canonical_bytes(ledger)).hexdigest()
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=ROOT / "scripts/capability_gate_catalog_v1.json")
    parser.add_argument("--external", type=Path, default=ROOT / "artifacts/capability_gate_ledger_v1/external_replication.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/capability_gate_ledger_v1/ledger.json")
    args = parser.parse_args()
    ledger = build(args.catalog, args.external)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json.dumps(ledger, indent=2, sort_keys=True).encode() + b"\n")
    print(f"wrote {args.output} ({ledger['ledger_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
