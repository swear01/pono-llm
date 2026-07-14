#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import cross_tool_x0_schema as schema


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "scripts/cross_tool_candidate_catalog_v1.json"
CENSUS_PATH = ROOT / "scripts/cross_tool_x0_census_v1.json"
BUILDER_PATH = ROOT / "scripts/build_cross_tool_x0.py"
VALIDATOR_PATH = ROOT / "scripts/validate_cross_tool_x0.py"
SCHEMA_PATH = ROOT / "scripts/cross_tool_x0_schema.py"
BUILDER_SOURCES = (SCHEMA_PATH, BUILDER_PATH, VALIDATOR_PATH, CENSUS_PATH)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git_text(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def git_bytes(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def parse_tree(repository: Path) -> list[dict[str, str]]:
    raw = git_bytes(repository, "ls-tree", "-r", "-z", "HEAD")
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in raw.split(b"\0"):
        if not item:
            continue
        header, separator, raw_path = item.partition(b"\t")
        if not separator:
            raise ValueError("git ls-tree record lacks a path separator")
        mode, object_type, object_id = header.decode("ascii").split(" ")
        path = raw_path.decode("utf-8")
        schema.repository_path(path, "git tree path")
        if "\n" in path or "\t" in path:
            raise ValueError(f"unsupported control character in Git path: {path!r}")
        if path in seen_paths:
            raise ValueError(f"duplicate Git tree path: {path}")
        seen_paths.add(path)
        entries.append(
            {
                "mode": mode,
                "type": object_type,
                "object": object_id,
                "path": path,
            }
        )
    if entries != sorted(entries, key=lambda entry: entry["path"]):
        raise ValueError("Git tree inventory is not lexicographically ordered")
    return entries


def normalize_origin(value: str) -> str:
    normalized = value.strip()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def build_inventory(
    repository_directory: Path,
    repository_record: dict[str, object],
    census_record: dict[str, object],
    output_directory: Path,
) -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    expected_commit = str(repository_record["resolved_commit"])
    head = git_text(repository_directory, "rev-parse", "HEAD").strip()
    if head != expected_commit:
        raise ValueError(
            f"{repository_record['repository']} checkout mismatch: {head}"
        )
    if git_text(
        repository_directory, "status", "--porcelain=v1", "--untracked-files=all"
    ):
        raise ValueError(f"external checkout is dirty: {repository_record['repository']}")
    origin = normalize_origin(
        git_text(repository_directory, "remote", "get-url", "origin")
    )
    if origin != repository_record["url"]:
        raise ValueError(
            f"{repository_record['repository']} origin mismatch: {origin}"
        )
    tree = git_text(repository_directory, "rev-parse", "HEAD^{tree}").strip()
    entries = parse_tree(repository_directory)
    entry_index = {entry["path"]: entry for entry in entries}
    directory = str(census_record["directory"])
    listing_relative = f"inventories/{directory}.paths.txt"
    listing_bytes = "".join(
        f"{entry['mode']} {entry['type']} {entry['object']}\t{entry['path']}\n"
        for entry in entries
    ).encode()
    listing_path = output_directory / listing_relative
    listing_path.parent.mkdir(parents=True, exist_ok=True)
    listing_path.write_bytes(listing_bytes)

    top_level_counts: collections.Counter[str] = collections.Counter()
    type_counts: collections.Counter[str] = collections.Counter()
    root_files: list[str] = []
    root_license_files: list[str] = []
    for entry in entries:
        path = entry["path"]
        top_level_counts[path.split("/", 1)[0]] += 1
        type_counts[entry["type"]] += 1
        if "/" not in path:
            root_files.append(path)
            lowered = path.lower()
            if lowered.startswith(("license", "copying", "notice")):
                root_license_files.append(path)

    inventory: dict[str, object] = {
        "schema": schema.INVENTORY_SCHEMA,
        "candidate_id": census_record["candidate_id"],
        "directory": directory,
        "repository": repository_record["repository"],
        "url": repository_record["url"],
        "commit": expected_commit,
        "tree": tree,
        "path_count": len(entries),
        "type_counts": dict(sorted(type_counts.items())),
        "top_level_counts": dict(sorted(top_level_counts.items())),
        "root_files": root_files,
        "root_license_files": root_license_files,
        "path_listing": {
            "path": listing_relative,
            "sha256": hashlib.sha256(listing_bytes).hexdigest(),
        },
    }
    inventory["inventory_sha256"] = schema.document_sha256(
        inventory, "inventory_sha256"
    )
    write_json(output_directory / f"inventories/{directory}.json", inventory)
    return inventory, entry_index


def collect_source_files(
    census: dict[str, object],
    repository_directories: dict[str, Path],
    inventories: dict[str, dict[str, object]],
    entry_indexes: dict[str, dict[str, dict[str, str]]],
) -> dict[str, object]:
    requested: set[tuple[str, str]] = set()
    for candidate in census["candidates"]:
        for field in candidate["fields"].values():
            for evidence in field["evidence"]:
                if evidence["kind"] in {"repository-file", "repository-object"}:
                    requested.add((evidence["repository"], evidence["path"]))

    records: list[dict[str, object]] = []
    for repository, path in sorted(requested):
        entry = entry_indexes[repository].get(path)
        if entry is None:
            raise ValueError(f"evidence path absent from frozen tree: {repository}:{path}")
        if entry["type"] != "blob":
            raise ValueError(f"evidence path is not a Git blob: {repository}:{path}")
        content = git_bytes(
            repository_directories[repository], "cat-file", "blob", entry["object"]
        )
        try:
            line_count: int | None = len(content.decode("utf-8").splitlines())
        except UnicodeDecodeError:
            line_count = None
        inventory = inventories[repository]
        records.append(
            {
                "repository": repository,
                "path": path,
                "url": (
                    f"{inventory['url']}/blob/{inventory['commit']}/"
                    f"{quote(path, safe='/')}"
                ),
                "mode": entry["mode"],
                "git_type": entry["type"],
                "git_object": entry["object"],
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_count": len(content),
                "line_count": line_count,
            }
        )
    document: dict[str, object] = {
        "schema": schema.SOURCE_FILES_SCHEMA,
        "file_count": len(records),
        "files": records,
    }
    document["source_files_sha256"] = schema.document_sha256(
        document, "source_files_sha256"
    )
    return document


def resolve_evidence(
    evidence: dict[str, object],
    inventories: dict[str, dict[str, object]],
    source_file_index: dict[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    repository = str(evidence["repository"])
    inventory = inventories[repository]
    kind = evidence["kind"]
    if kind == "repository-commit":
        return {
            "kind": kind,
            "repository": repository,
            "url": f"{inventory['url']}/tree/{inventory['commit']}",
            "commit": inventory["commit"],
            "tree": inventory["tree"],
        }
    if kind == "repository-inventory":
        directory = inventory["directory"]
        path_listing = inventory["path_listing"]
        return {
            "kind": kind,
            "repository": repository,
            "inventory_path": f"inventories/{directory}.json",
            "inventory_sha256": inventory["inventory_sha256"],
            "path_listing_path": path_listing["path"],
            "path_listing_sha256": path_listing["sha256"],
        }
    path = str(evidence["path"])
    source = source_file_index[(repository, path)]
    if kind == "repository-object":
        return {
            "kind": kind,
            "repository": repository,
            "path": path,
            "url": source["url"],
            "commit": inventory["commit"],
            "git_object": source["git_object"],
            "sha256": source["sha256"],
            "byte_count": source["byte_count"],
        }
    if kind != "repository-file":
        raise ValueError(f"unsupported evidence kind: {kind}")
    line_count = source["line_count"]
    if line_count is None or evidence["line_end"] > line_count:
        raise ValueError(f"evidence line range exceeds source: {repository}:{path}")
    return {
        "kind": kind,
        "repository": repository,
        "path": path,
        "url": source["url"],
        "commit": inventory["commit"],
        "git_object": source["git_object"],
        "sha256": source["sha256"],
        "byte_count": source["byte_count"],
        "line_start": evidence["line_start"],
        "line_end": evidence["line_end"],
    }


def build_reports(
    catalog: dict[str, object],
    census: dict[str, object],
    inventories: dict[str, dict[str, object]],
    source_files: dict[str, object],
    output_directory: Path,
) -> list[dict[str, object]]:
    catalog_candidates = schema.candidate_catalog_index(catalog)
    census_candidates = schema.census_candidate_index(census)
    source_file_index = {
        (record["repository"], record["path"]): record
        for record in source_files["files"]
    }
    reports: list[dict[str, object]] = []
    for candidate_id in sorted(schema.EXPECTED_CANDIDATES):
        candidate = catalog_candidates[candidate_id]
        census_candidate = census_candidates[candidate_id]
        fields: dict[str, object] = {}
        state_fields: dict[str, list[str]] = {
            state: [] for state in sorted(schema.FIELD_STATES)
        }
        for field_name in schema.REQUIRED_FIELDS:
            source_field = census_candidate["fields"][field_name]
            state = source_field["state"]
            state_fields[state].append(field_name)
            fields[field_name] = {
                "state": state,
                "finding": source_field["finding"],
                "evidence": [
                    resolve_evidence(item, inventories, source_file_index)
                    for item in source_field["evidence"]
                ],
            }
        candidate_repositories = sorted(
            schema.EXPECTED_CANDIDATES[candidate_id]["repositories"]
        )
        repository_records = []
        for repository in candidate_repositories:
            inventory = inventories[repository]
            repository_records.append(
                {
                    "repository": repository,
                    "url": inventory["url"],
                    "commit": inventory["commit"],
                    "tree": inventory["tree"],
                    "inventory_path": f"inventories/{inventory['directory']}.json",
                    "inventory_sha256": inventory["inventory_sha256"],
                }
            )
        available_count = len(state_fields["available"])
        report: dict[str, object] = {
            "schema": schema.REPORT_SCHEMA,
            "candidate_id": candidate_id,
            "name": candidate["name"],
            "setting": candidate["setting"],
            "setting_class": candidate["setting_class"],
            "catalog_sha256": catalog["catalog_sha256"],
            "retrieval_freeze_sha256": census["retrieval_freeze_sha256"],
            "census_sha256": census["census_sha256"],
            "repositories": repository_records,
            "fields": fields,
            "available_count": available_count,
            "missing_fields": state_fields["missing"],
            "blocked_fields": state_fields["blocked"],
            "ambiguous_fields": state_fields["ambiguous"],
            "full_audit_eligible": available_count == len(schema.REQUIRED_FIELDS),
        }
        report["report_sha256"] = schema.document_sha256(report, "report_sha256")
        report_path = output_directory / f"reports/{candidate_id}.json"
        write_json(report_path, report)
        reports.append(report)
    return reports


def build_summary(
    catalog: dict[str, object],
    census: dict[str, object],
    reports: list[dict[str, object]],
) -> dict[str, object]:
    eligible = [
        report["candidate_id"] for report in reports if report["full_audit_eligible"]
    ]
    eligible_settings = sorted(
        {
            report["setting_class"]
            for report in reports
            if report["full_audit_eligible"]
        }
    )
    threshold = catalog["threshold"]
    go = (
        len(eligible) >= threshold["eligible_candidates"]
        and len(eligible_settings) >= threshold["eligible_settings"]
    )
    decision = threshold["success_decision"] if go else threshold["failure_decision"]
    state_totals = {state: 0 for state in sorted(schema.FIELD_STATES)}
    report_rows: list[dict[str, object]] = []
    blocking_fields: dict[str, list[str]] = {}
    for report in reports:
        for field in report["fields"].values():
            state_totals[field["state"]] += 1
        nonavailable = [
            field_name
            for field_name in schema.REQUIRED_FIELDS
            if report["fields"][field_name]["state"] != "available"
        ]
        blocking_fields[report["candidate_id"]] = nonavailable
        report_rows.append(
            {
                "candidate_id": report["candidate_id"],
                "setting_class": report["setting_class"],
                "available_count": report["available_count"],
                "full_audit_eligible": report["full_audit_eligible"],
                "report_path": f"reports/{report['candidate_id']}.json",
                "report_sha256": report["report_sha256"],
            }
        )
    summary: dict[str, object] = {
        "schema": schema.SUMMARY_SCHEMA,
        "gate": "X0",
        "catalog_sha256": catalog["catalog_sha256"],
        "retrieval_freeze_sha256": census["retrieval_freeze_sha256"],
        "census_sha256": census["census_sha256"],
        "candidate_count": len(reports),
        "required_field_count": len(schema.REQUIRED_FIELDS),
        "field_state_totals": state_totals,
        "reports": report_rows,
        "eligible_candidate_ids": eligible,
        "eligible_setting_classes": eligible_settings,
        "blocking_fields": blocking_fields,
        "threshold": threshold,
        "decision": decision,
        "x1_authorized": go,
        "new_llm_api_calls": census["execution"]["new_llm_api_calls"],
        "verifier_executions": census["execution"]["verifier_executions"],
        "threshold_changes": census["execution"]["threshold_changes"],
        "interpretation": (
            "Gate X0 measures public artifact sufficiency only; a STOP does not "
            "claim that any evaluated system is unsound or ineffective."
        ),
    }
    summary["summary_sha256"] = schema.document_sha256(summary, "summary_sha256")
    return summary


def build_provenance(
    census: dict[str, object],
    inventories: dict[str, dict[str, object]],
    source_files: dict[str, object],
) -> dict[str, object]:
    builder_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            schema.PREREGISTRATION_COMMIT,
            builder_commit,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if ancestry.returncode == 1:
        raise ValueError("builder commit does not descend from preregistration")
    if ancestry.returncode != 0:
        raise RuntimeError(
            "unable to validate builder commit ancestry: "
            f"{ancestry.stderr.strip()}"
        )
    if builder_commit != schema.PREREGISTRATION_COMMIT:
        relative_sources = [
            path.relative_to(ROOT).as_posix() for path in BUILDER_SOURCES
        ]
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", *relative_sources],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if tracked.returncode != 0:
            raise ValueError("replication builder sources must be tracked by Git")
        clean = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *relative_sources],
            cwd=ROOT,
        )
        if clean.returncode == 1:
            raise ValueError("replication builder sources differ from HEAD")
        if clean.returncode != 0:
            raise RuntimeError("unable to validate replication builder source state")
    builder_sources = []
    for path in BUILDER_SOURCES:
        builder_sources.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": schema.file_sha256(path),
            }
        )
    repositories = []
    for repository in sorted(inventories):
        inventory = inventories[repository]
        repositories.append(
            {
                "repository": repository,
                "url": inventory["url"],
                "commit": inventory["commit"],
                "tree": inventory["tree"],
                "inventory_sha256": inventory["inventory_sha256"],
            }
        )
    provenance: dict[str, object] = {
        "schema": schema.PROVENANCE_SCHEMA,
        "artifact_created_at_utc": census["inspection_completed_at_utc"],
        "preregistration_commit": schema.PREREGISTRATION_COMMIT,
        "builder_parent_commit": builder_commit,
        "catalog_file_sha256": schema.file_sha256(CATALOG_PATH),
        "catalog_sha256": census["catalog_sha256"],
        "census_file_sha256": schema.file_sha256(CENSUS_PATH),
        "census_sha256": census["census_sha256"],
        "retrieval_file_sha256": schema.RETRIEVAL_FILE_SHA256,
        "retrieval_freeze_sha256": census["retrieval_freeze_sha256"],
        "source_files_sha256": source_files["source_files_sha256"],
        "builder_sources": builder_sources,
        "external_repositories": repositories,
        "execution": census["execution"],
        "inspection_scope": [
            "README and artifact instructions",
            "repository manifests and immutable Git metadata",
            "benchmark and result indexes",
            "containers, lockfiles, and referenced configuration",
            "frozen result objects without executing a verifier or model",
        ],
        "repository_tree_blobs_bundled": False,
        "retrieval_api_payloads_bundled": False,
        "retrieval_api_payload_hashes_bundled": True,
        "retrieval_api_payloads_validated_at_build": True,
        "retrieval_api_payloads_may_include_diff_patches": True,
        "old_soundness_audit_amended": False,
    }
    provenance["provenance_sha256"] = schema.document_sha256(
        provenance, "provenance_sha256"
    )
    return provenance


def write_integrity(output_directory: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    for path in sorted(output_directory.rglob("*")):
        if not path.is_file() or path.name == "integrity.json":
            continue
        relative = path.relative_to(output_directory).as_posix()
        files[relative] = schema.file_sha256(path)
    integrity: dict[str, object] = {
        "schema": schema.INTEGRITY_SCHEMA,
        "file_count": len(files),
        "files": files,
    }
    integrity["integrity_sha256"] = schema.document_sha256(
        integrity, "integrity_sha256"
    )
    write_json(output_directory / "integrity.json", integrity)
    return integrity


def build(
    repositories_root: Path,
    retrieval_directory: Path,
    output_directory: Path,
) -> dict[str, object]:
    repositories_root = repositories_root.resolve()
    retrieval_directory = retrieval_directory.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"output directory already exists: {output_directory}")
    temporary_directory = output_directory.with_name(f".{output_directory.name}.tmp")
    if temporary_directory.exists():
        raise FileExistsError(f"temporary output directory exists: {temporary_directory}")

    catalog = schema.validate_catalog(CATALOG_PATH)
    retrieval_path = retrieval_directory / "retrieval_freeze.json"
    github_directory = retrieval_directory / "github"
    retrieval = schema.validate_retrieval_freeze(retrieval_path, github_directory)
    census = schema.validate_census(CENSUS_PATH, catalog, retrieval)
    frozen_records = schema.retrieval_records(retrieval)
    census_repositories = schema.census_repository_index(census)

    temporary_directory.mkdir(parents=True)
    try:
        (temporary_directory / "catalog.json").write_bytes(CATALOG_PATH.read_bytes())
        (temporary_directory / "census.json").write_bytes(CENSUS_PATH.read_bytes())
        retrieval_output = temporary_directory / "retrieval"
        retrieval_output.mkdir()
        (retrieval_output / "retrieval_freeze.json").write_bytes(
            retrieval_path.read_bytes()
        )

        inventories: dict[str, dict[str, object]] = {}
        entry_indexes: dict[str, dict[str, dict[str, str]]] = {}
        repository_directories: dict[str, Path] = {}
        for repository in sorted(frozen_records):
            census_record = census_repositories[repository]
            repository_directory = repositories_root / str(census_record["directory"])
            if not repository_directory.is_dir():
                raise FileNotFoundError(
                    f"external repository checkout is missing: {repository_directory}"
                )
            repository_directories[repository] = repository_directory
            inventory, entry_index = build_inventory(
                repository_directory,
                frozen_records[repository],
                census_record,
                temporary_directory,
            )
            inventories[repository] = inventory
            entry_indexes[repository] = entry_index

        source_files = collect_source_files(
            census,
            repository_directories,
            inventories,
            entry_indexes,
        )
        write_json(temporary_directory / "source_files.json", source_files)
        reports = build_reports(
            catalog, census, inventories, source_files, temporary_directory
        )
        summary = build_summary(catalog, census, reports)
        write_json(temporary_directory / "summary.json", summary)
        provenance = build_provenance(census, inventories, source_files)
        write_json(temporary_directory / "provenance.json", provenance)
        write_integrity(temporary_directory)
        os.replace(temporary_directory, output_directory)
    except BaseException:
        if temporary_directory.exists():
            shutil.rmtree(temporary_directory)
        raise
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the preregistered cross-tool Gate X0 artifact census."
    )
    parser.add_argument("repositories_root", type=Path)
    parser.add_argument("retrieval_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args()
    summary = build(
        arguments.repositories_root,
        arguments.retrieval_directory,
        arguments.output_directory,
    )
    print(
        f"wrote {arguments.output_directory} "
        f"({summary['decision']}, {summary['summary_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
