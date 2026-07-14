#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import subprocess
from pathlib import Path
from urllib.parse import quote

import cross_tool_x0_schema as schema


ROOT = Path(__file__).resolve().parents[1]


def validate_integrity(directory: Path) -> dict[str, object]:
    path = directory / "integrity.json"
    document = schema.strict_fields(
        schema.load_strict(path),
        {"schema", "file_count", "files", "integrity_sha256"},
        "X0 integrity",
    )
    if document["schema"] != schema.INTEGRITY_SCHEMA:
        raise ValueError("unsupported X0 integrity schema")
    declared = schema.sha256_text(
        document["integrity_sha256"], "integrity_sha256"
    )
    actual = schema.document_sha256(document, "integrity_sha256")
    if declared != actual:
        raise ValueError("X0 integrity self-hash mismatch")
    files = document["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("X0 integrity files must be a non-empty object")
    if document["file_count"] != len(files):
        raise ValueError("X0 integrity file count mismatch")
    actual_files = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.name != "integrity.json"
    }
    if set(files) != actual_files:
        raise ValueError(
            "X0 integrity file set mismatch: "
            f"missing={sorted(set(files) - actual_files)}, "
            f"unknown={sorted(actual_files - set(files))}"
        )
    for relative, digest_value in files.items():
        schema.bundle_path(relative, f"integrity path {relative!r}")
        digest = schema.sha256_text(digest_value, f"integrity hash {relative}")
        if schema.file_sha256(directory / relative) != digest:
            raise ValueError(f"X0 integrity hash mismatch: {relative}")
    return document


def parse_path_listing(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        header, separator, entry_path = line.partition("\t")
        if not separator:
            raise ValueError(f"invalid inventory listing line {line_number}: {path}")
        parts = header.split(" ")
        if len(parts) != 3:
            raise ValueError(f"invalid inventory header line {line_number}: {path}")
        mode, object_type, object_id = parts
        if len(object_id) != 40 or any(character not in "0123456789abcdef" for character in object_id):
            raise ValueError(f"invalid Git object at line {line_number}: {path}")
        schema.repository_path(entry_path, f"inventory path line {line_number}")
        if entry_path in seen:
            raise ValueError(f"duplicate inventory path: {entry_path}")
        seen.add(entry_path)
        entries.append(
            {
                "mode": mode,
                "type": object_type,
                "object": object_id,
                "path": entry_path,
            }
        )
    if not entries or entries != sorted(entries, key=lambda entry: entry["path"]):
        raise ValueError(f"inventory listing must be non-empty and sorted: {path}")
    return entries


def validate_inventories(
    directory: Path,
    census: dict[str, object],
    retrieval: dict[str, object],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, dict[str, str]]],
]:
    census_repositories = schema.census_repository_index(census)
    frozen_records = schema.retrieval_records(retrieval)
    inventories: dict[str, dict[str, object]] = {}
    entry_indexes: dict[str, dict[str, dict[str, str]]] = {}
    for repository in sorted(frozen_records):
        census_record = census_repositories[repository]
        inventory_relative = f"inventories/{census_record['directory']}.json"
        inventory = schema.strict_fields(
            schema.load_strict(directory / inventory_relative),
            {
                "schema",
                "candidate_id",
                "directory",
                "repository",
                "url",
                "commit",
                "tree",
                "path_count",
                "type_counts",
                "top_level_counts",
                "root_files",
                "root_license_files",
                "path_listing",
                "inventory_sha256",
            },
            f"inventory {repository}",
        )
        if inventory["schema"] != schema.INVENTORY_SCHEMA:
            raise ValueError(f"unsupported inventory schema: {repository}")
        declared = schema.sha256_text(
            inventory["inventory_sha256"], f"{repository}.inventory_sha256"
        )
        if declared != schema.document_sha256(inventory, "inventory_sha256"):
            raise ValueError(f"inventory self-hash mismatch: {repository}")
        frozen = frozen_records[repository]
        if inventory["candidate_id"] != census_record["candidate_id"]:
            raise ValueError(f"inventory candidate mismatch: {repository}")
        if inventory["directory"] != census_record["directory"]:
            raise ValueError(f"inventory directory mismatch: {repository}")
        if inventory["repository"] != repository:
            raise ValueError(f"inventory repository mismatch: {repository}")
        if inventory["url"] != frozen["url"]:
            raise ValueError(f"inventory URL mismatch: {repository}")
        if inventory["commit"] != frozen["resolved_commit"]:
            raise ValueError(f"inventory commit mismatch: {repository}")
        schema.commit_text(inventory["tree"], f"{repository}.tree")

        listing = schema.strict_fields(
            inventory["path_listing"], {"path", "sha256"}, "path listing"
        )
        expected_listing = f"inventories/{census_record['directory']}.paths.txt"
        if listing["path"] != expected_listing:
            raise ValueError(f"inventory path-listing location mismatch: {repository}")
        listing_digest = schema.sha256_text(
            listing["sha256"], f"{repository}.path_listing.sha256"
        )
        listing_path = directory / expected_listing
        if schema.file_sha256(listing_path) != listing_digest:
            raise ValueError(f"inventory path-listing hash mismatch: {repository}")
        entries = parse_path_listing(listing_path)
        if inventory["path_count"] != len(entries):
            raise ValueError(f"inventory path count mismatch: {repository}")

        type_counts: collections.Counter[str] = collections.Counter()
        top_level_counts: collections.Counter[str] = collections.Counter()
        root_files: list[str] = []
        root_license_files: list[str] = []
        for entry in entries:
            type_counts[entry["type"]] += 1
            top_level_counts[entry["path"].split("/", 1)[0]] += 1
            if "/" not in entry["path"]:
                root_files.append(entry["path"])
                if entry["path"].lower().startswith(("license", "copying", "notice")):
                    root_license_files.append(entry["path"])
        if inventory["type_counts"] != dict(sorted(type_counts.items())):
            raise ValueError(f"inventory type counts mismatch: {repository}")
        if inventory["top_level_counts"] != dict(sorted(top_level_counts.items())):
            raise ValueError(f"inventory top-level counts mismatch: {repository}")
        if inventory["root_files"] != root_files:
            raise ValueError(f"inventory root file list mismatch: {repository}")
        if inventory["root_license_files"] != root_license_files:
            raise ValueError(f"inventory root license list mismatch: {repository}")
        inventories[repository] = inventory
        entry_indexes[repository] = {entry["path"]: entry for entry in entries}
    return inventories, entry_indexes


def validate_source_files(
    path: Path,
    inventories: dict[str, dict[str, object]],
    entry_indexes: dict[str, dict[str, dict[str, str]]],
) -> tuple[dict[str, object], dict[tuple[str, str], dict[str, object]]]:
    document = schema.strict_fields(
        schema.load_strict(path),
        {"schema", "file_count", "files", "source_files_sha256"},
        "source files",
    )
    if document["schema"] != schema.SOURCE_FILES_SCHEMA:
        raise ValueError("unsupported source-files schema")
    declared = schema.sha256_text(
        document["source_files_sha256"], "source_files_sha256"
    )
    if declared != schema.document_sha256(document, "source_files_sha256"):
        raise ValueError("source-files self-hash mismatch")
    files = document["files"]
    if not isinstance(files, list) or document["file_count"] != len(files):
        raise ValueError("source-files count mismatch")
    index: dict[tuple[str, str], dict[str, object]] = {}
    previous_key: tuple[str, str] | None = None
    for item_index, value in enumerate(files):
        record = schema.strict_fields(
            value,
            {
                "repository",
                "path",
                "url",
                "mode",
                "git_type",
                "git_object",
                "sha256",
                "byte_count",
                "line_count",
            },
            f"source file {item_index}",
        )
        repository = schema.nonempty_text(record["repository"], "repository")
        source_path = schema.repository_path(record["path"], "source path")
        key = (repository, source_path)
        if key in index or (previous_key is not None and key < previous_key):
            raise ValueError("source-files records must be unique and sorted")
        previous_key = key
        if repository not in inventories:
            raise ValueError(f"unknown source-file repository: {repository}")
        entry = entry_indexes[repository].get(source_path)
        if entry is None or entry["type"] != "blob":
            raise ValueError(f"source file is not an inventoried blob: {key}")
        if (
            record["mode"] != entry["mode"]
            or record["git_type"] != entry["type"]
            or record["git_object"] != entry["object"]
        ):
            raise ValueError(f"source-file Git identity mismatch: {key}")
        inventory = inventories[repository]
        expected_url = (
            f"{inventory['url']}/blob/{inventory['commit']}/"
            f"{quote(source_path, safe='/')}"
        )
        if record["url"] != expected_url:
            raise ValueError(f"source-file URL mismatch: {key}")
        schema.sha256_text(record["sha256"], f"source file {key} sha256")
        if not isinstance(record["byte_count"], int) or record["byte_count"] < 0:
            raise ValueError(f"source-file byte_count is invalid: {key}")
        line_count = record["line_count"]
        if line_count is not None and (
            not isinstance(line_count, int)
            or isinstance(line_count, bool)
            or line_count < 0
        ):
            raise ValueError(f"source-file line_count is invalid: {key}")
        index[key] = record
    return document, index


def validate_resolved_evidence(
    resolved_value: object,
    source_value: object,
    inventories: dict[str, dict[str, object]],
    source_files: dict[tuple[str, str], dict[str, object]],
    location: str,
) -> None:
    if not isinstance(source_value, dict):
        raise ValueError(f"{location} census evidence must be an object")
    kind = source_value["kind"]
    repository = source_value["repository"]
    inventory = inventories[repository]
    if kind == "repository-commit":
        resolved = schema.strict_fields(
            resolved_value,
            {"kind", "repository", "url", "commit", "tree"},
            location,
        )
        expected = {
            "kind": kind,
            "repository": repository,
            "url": f"{inventory['url']}/tree/{inventory['commit']}",
            "commit": inventory["commit"],
            "tree": inventory["tree"],
        }
    elif kind == "repository-inventory":
        resolved = schema.strict_fields(
            resolved_value,
            {
                "kind",
                "repository",
                "inventory_path",
                "inventory_sha256",
                "path_listing_path",
                "path_listing_sha256",
            },
            location,
        )
        expected = {
            "kind": kind,
            "repository": repository,
            "inventory_path": f"inventories/{inventory['directory']}.json",
            "inventory_sha256": inventory["inventory_sha256"],
            "path_listing_path": inventory["path_listing"]["path"],
            "path_listing_sha256": inventory["path_listing"]["sha256"],
        }
    else:
        path = source_value["path"]
        source = source_files[(repository, path)]
        common = {
            "kind": kind,
            "repository": repository,
            "path": path,
            "url": source["url"],
            "commit": inventory["commit"],
            "git_object": source["git_object"],
            "sha256": source["sha256"],
            "byte_count": source["byte_count"],
        }
        if kind == "repository-object":
            resolved = schema.strict_fields(
                resolved_value,
                {
                    "kind",
                    "repository",
                    "path",
                    "url",
                    "commit",
                    "git_object",
                    "sha256",
                    "byte_count",
                },
                location,
            )
            expected = common
        elif kind == "repository-file":
            resolved = schema.strict_fields(
                resolved_value,
                {
                    "kind",
                    "repository",
                    "path",
                    "url",
                    "commit",
                    "git_object",
                    "sha256",
                    "byte_count",
                    "line_start",
                    "line_end",
                },
                location,
            )
            line_count = source["line_count"]
            if line_count is None or source_value["line_end"] > line_count:
                raise ValueError(f"resolved evidence line range is invalid: {location}")
            expected = {
                **common,
                "line_start": source_value["line_start"],
                "line_end": source_value["line_end"],
            }
        else:
            raise ValueError(f"unsupported report evidence kind: {kind}")
    if resolved != expected:
        raise ValueError(f"resolved evidence differs from census source: {location}")


def validate_reports(
    directory: Path,
    catalog: dict[str, object],
    census: dict[str, object],
    inventories: dict[str, dict[str, object]],
    source_files: dict[tuple[str, str], dict[str, object]],
) -> list[dict[str, object]]:
    catalog_candidates = schema.candidate_catalog_index(catalog)
    census_candidates = schema.census_candidate_index(census)
    reports: list[dict[str, object]] = []
    for candidate_id in sorted(schema.EXPECTED_CANDIDATES):
        path = directory / f"reports/{candidate_id}.json"
        report = schema.strict_fields(
            schema.load_strict(path),
            {
                "schema",
                "candidate_id",
                "name",
                "setting",
                "setting_class",
                "catalog_sha256",
                "retrieval_freeze_sha256",
                "census_sha256",
                "repositories",
                "fields",
                "available_count",
                "missing_fields",
                "blocked_fields",
                "ambiguous_fields",
                "full_audit_eligible",
                "report_sha256",
            },
            f"candidate report {candidate_id}",
        )
        if report["schema"] != schema.REPORT_SCHEMA:
            raise ValueError(f"unsupported candidate report schema: {candidate_id}")
        declared = schema.sha256_text(
            report["report_sha256"], f"{candidate_id}.report_sha256"
        )
        if declared != schema.document_sha256(report, "report_sha256"):
            raise ValueError(f"candidate report self-hash mismatch: {candidate_id}")
        candidate = catalog_candidates[candidate_id]
        if {
            "candidate_id": report["candidate_id"],
            "name": report["name"],
            "setting": report["setting"],
            "setting_class": report["setting_class"],
            "catalog_sha256": report["catalog_sha256"],
            "retrieval_freeze_sha256": report["retrieval_freeze_sha256"],
            "census_sha256": report["census_sha256"],
        } != {
            "candidate_id": candidate_id,
            "name": candidate["name"],
            "setting": candidate["setting"],
            "setting_class": candidate["setting_class"],
            "catalog_sha256": catalog["catalog_sha256"],
            "retrieval_freeze_sha256": census["retrieval_freeze_sha256"],
            "census_sha256": census["census_sha256"],
        }:
            raise ValueError(f"candidate report identity mismatch: {candidate_id}")

        repositories = report["repositories"]
        expected_repository_names = sorted(
            schema.EXPECTED_CANDIDATES[candidate_id]["repositories"]
        )
        if not isinstance(repositories, list) or [
            record.get("repository") if isinstance(record, dict) else None
            for record in repositories
        ] != expected_repository_names:
            raise ValueError(f"candidate report repository set mismatch: {candidate_id}")
        for repository_value in repositories:
            repository = schema.strict_fields(
                repository_value,
                {
                    "repository",
                    "url",
                    "commit",
                    "tree",
                    "inventory_path",
                    "inventory_sha256",
                },
                f"{candidate_id} report repository",
            )
            inventory = inventories[repository["repository"]]
            expected = {
                "repository": inventory["repository"],
                "url": inventory["url"],
                "commit": inventory["commit"],
                "tree": inventory["tree"],
                "inventory_path": f"inventories/{inventory['directory']}.json",
                "inventory_sha256": inventory["inventory_sha256"],
            }
            if repository != expected:
                raise ValueError(f"candidate report repository mismatch: {candidate_id}")

        fields = report["fields"]
        if not isinstance(fields, dict) or set(fields) != set(schema.REQUIRED_FIELDS):
            raise ValueError(f"candidate report field set mismatch: {candidate_id}")
        census_fields = census_candidates[candidate_id]["fields"]
        state_fields = {state: [] for state in sorted(schema.FIELD_STATES)}
        for field_name in schema.REQUIRED_FIELDS:
            field = schema.strict_fields(
                fields[field_name],
                {"state", "finding", "evidence"},
                f"{candidate_id}.{field_name}",
            )
            source_field = census_fields[field_name]
            if field["state"] != source_field["state"] or field["finding"] != source_field["finding"]:
                raise ValueError(f"candidate report finding mismatch: {candidate_id}.{field_name}")
            state_fields[field["state"]].append(field_name)
            if not isinstance(field["evidence"], list) or len(field["evidence"]) != len(source_field["evidence"]):
                raise ValueError(f"candidate report evidence count mismatch: {candidate_id}.{field_name}")
            for evidence_index, (resolved, source) in enumerate(
                zip(field["evidence"], source_field["evidence"], strict=True)
            ):
                validate_resolved_evidence(
                    resolved,
                    source,
                    inventories,
                    source_files,
                    f"{candidate_id}.{field_name}.evidence[{evidence_index}]",
                )
        available_count = len(state_fields["available"])
        if report["available_count"] != available_count:
            raise ValueError(f"candidate report available count mismatch: {candidate_id}")
        if report["missing_fields"] != state_fields["missing"]:
            raise ValueError(f"candidate report missing field list mismatch: {candidate_id}")
        if report["blocked_fields"] != state_fields["blocked"]:
            raise ValueError(f"candidate report blocked field list mismatch: {candidate_id}")
        if report["ambiguous_fields"] != state_fields["ambiguous"]:
            raise ValueError(f"candidate report ambiguous field list mismatch: {candidate_id}")
        if report["full_audit_eligible"] is not (
            available_count == len(schema.REQUIRED_FIELDS)
        ):
            raise ValueError(f"candidate report eligibility mismatch: {candidate_id}")
        reports.append(report)
    return reports


def validate_summary(
    path: Path,
    catalog: dict[str, object],
    census: dict[str, object],
    reports: list[dict[str, object]],
) -> dict[str, object]:
    summary = schema.strict_fields(
        schema.load_strict(path),
        {
            "schema",
            "gate",
            "catalog_sha256",
            "retrieval_freeze_sha256",
            "census_sha256",
            "candidate_count",
            "required_field_count",
            "field_state_totals",
            "reports",
            "eligible_candidate_ids",
            "eligible_setting_classes",
            "blocking_fields",
            "threshold",
            "decision",
            "x1_authorized",
            "new_llm_api_calls",
            "verifier_executions",
            "threshold_changes",
            "interpretation",
            "summary_sha256",
        },
        "X0 summary",
    )
    if summary["schema"] != schema.SUMMARY_SCHEMA or summary["gate"] != "X0":
        raise ValueError("unsupported X0 summary schema or gate")
    declared = schema.sha256_text(summary["summary_sha256"], "summary_sha256")
    if declared != schema.document_sha256(summary, "summary_sha256"):
        raise ValueError("X0 summary self-hash mismatch")
    if (
        summary["catalog_sha256"] != catalog["catalog_sha256"]
        or summary["retrieval_freeze_sha256"] != census["retrieval_freeze_sha256"]
        or summary["census_sha256"] != census["census_sha256"]
        or summary["candidate_count"] != len(reports)
        or summary["required_field_count"] != len(schema.REQUIRED_FIELDS)
    ):
        raise ValueError("X0 summary source identity or count mismatch")

    state_totals = {state: 0 for state in sorted(schema.FIELD_STATES)}
    eligible: list[str] = []
    eligible_settings: set[str] = set()
    report_rows: list[dict[str, object]] = []
    blocking_fields: dict[str, list[str]] = {}
    for report in reports:
        for field in report["fields"].values():
            state_totals[field["state"]] += 1
        if report["full_audit_eligible"]:
            eligible.append(report["candidate_id"])
            eligible_settings.add(report["setting_class"])
        blocking_fields[report["candidate_id"]] = [
            field_name
            for field_name in schema.REQUIRED_FIELDS
            if report["fields"][field_name]["state"] != "available"
        ]
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
    if summary["field_state_totals"] != state_totals:
        raise ValueError("X0 summary field-state totals mismatch")
    if summary["reports"] != report_rows:
        raise ValueError("X0 summary report index mismatch")
    if summary["eligible_candidate_ids"] != eligible:
        raise ValueError("X0 summary eligible candidate set mismatch")
    if summary["eligible_setting_classes"] != sorted(eligible_settings):
        raise ValueError("X0 summary eligible setting set mismatch")
    if summary["blocking_fields"] != blocking_fields:
        raise ValueError("X0 summary blocking field map mismatch")
    if summary["threshold"] != catalog["threshold"]:
        raise ValueError("X0 summary threshold differs from preregistration")
    threshold = catalog["threshold"]
    go = (
        len(eligible) >= threshold["eligible_candidates"]
        and len(eligible_settings) >= threshold["eligible_settings"]
    )
    expected_decision = threshold["success_decision"] if go else threshold["failure_decision"]
    if summary["decision"] != expected_decision or summary["x1_authorized"] is not go:
        raise ValueError("X0 summary decision does not follow preregistered threshold")
    if (
        summary["new_llm_api_calls"] != 0
        or summary["verifier_executions"] != 0
        or summary["threshold_changes"] is not False
    ):
        raise ValueError("X0 summary records an unauthorized action")
    expected_interpretation = (
        "Gate X0 measures public artifact sufficiency only; a STOP does not "
        "claim that any evaluated system is unsound or ineffective."
    )
    if summary["interpretation"] != expected_interpretation:
        raise ValueError("X0 summary interpretation changed")
    return summary


def validate_provenance(
    path: Path,
    census: dict[str, object],
    inventories: dict[str, dict[str, object]],
    source_files: dict[str, object],
) -> dict[str, object]:
    provenance = schema.strict_fields(
        schema.load_strict(path),
        {
            "schema",
            "artifact_created_at_utc",
            "preregistration_commit",
            "builder_parent_commit",
            "catalog_file_sha256",
            "catalog_sha256",
            "census_file_sha256",
            "census_sha256",
            "retrieval_file_sha256",
            "retrieval_freeze_sha256",
            "source_files_sha256",
            "builder_sources",
            "external_repositories",
            "execution",
            "inspection_scope",
            "repository_tree_blobs_bundled",
            "retrieval_api_payloads_bundled",
            "retrieval_api_payload_hashes_bundled",
            "retrieval_api_payloads_validated_at_build",
            "retrieval_api_payloads_may_include_diff_patches",
            "old_soundness_audit_amended",
            "provenance_sha256",
        },
        "X0 provenance",
    )
    if provenance["schema"] != schema.PROVENANCE_SCHEMA:
        raise ValueError("unsupported X0 provenance schema")
    declared = schema.sha256_text(
        provenance["provenance_sha256"], "provenance_sha256"
    )
    if declared != schema.document_sha256(provenance, "provenance_sha256"):
        raise ValueError("X0 provenance self-hash mismatch")
    builder_commit = schema.commit_text(
        provenance["builder_parent_commit"], "builder_parent_commit"
    )
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
    if {
        "artifact_created_at_utc": provenance["artifact_created_at_utc"],
        "preregistration_commit": provenance["preregistration_commit"],
        "catalog_file_sha256": provenance["catalog_file_sha256"],
        "catalog_sha256": provenance["catalog_sha256"],
        "census_file_sha256": provenance["census_file_sha256"],
        "census_sha256": provenance["census_sha256"],
        "retrieval_file_sha256": provenance["retrieval_file_sha256"],
        "retrieval_freeze_sha256": provenance["retrieval_freeze_sha256"],
        "source_files_sha256": provenance["source_files_sha256"],
        "execution": provenance["execution"],
        "repository_tree_blobs_bundled": provenance[
            "repository_tree_blobs_bundled"
        ],
        "retrieval_api_payloads_bundled": provenance[
            "retrieval_api_payloads_bundled"
        ],
        "retrieval_api_payload_hashes_bundled": provenance[
            "retrieval_api_payload_hashes_bundled"
        ],
        "retrieval_api_payloads_validated_at_build": provenance[
            "retrieval_api_payloads_validated_at_build"
        ],
        "retrieval_api_payloads_may_include_diff_patches": provenance[
            "retrieval_api_payloads_may_include_diff_patches"
        ],
        "old_soundness_audit_amended": provenance["old_soundness_audit_amended"],
    } != {
        "artifact_created_at_utc": census["inspection_completed_at_utc"],
        "preregistration_commit": schema.PREREGISTRATION_COMMIT,
        "catalog_file_sha256": schema.CATALOG_FILE_SHA256,
        "catalog_sha256": census["catalog_sha256"],
        "census_file_sha256": schema.file_sha256(
            ROOT / "scripts/cross_tool_x0_census_v1.json"
        ),
        "census_sha256": census["census_sha256"],
        "retrieval_file_sha256": schema.RETRIEVAL_FILE_SHA256,
        "retrieval_freeze_sha256": census["retrieval_freeze_sha256"],
        "source_files_sha256": source_files["source_files_sha256"],
        "execution": census["execution"],
        "repository_tree_blobs_bundled": False,
        "retrieval_api_payloads_bundled": False,
        "retrieval_api_payload_hashes_bundled": True,
        "retrieval_api_payloads_validated_at_build": True,
        "retrieval_api_payloads_may_include_diff_patches": True,
        "old_soundness_audit_amended": False,
    }:
        raise ValueError("X0 provenance source identity mismatch")
    builder_sources = provenance["builder_sources"]
    expected_builder_paths = [
        "scripts/cross_tool_x0_schema.py",
        "scripts/build_cross_tool_x0.py",
        "scripts/validate_cross_tool_x0.py",
        "scripts/cross_tool_x0_census_v1.json",
    ]
    if not isinstance(builder_sources, list) or [
        record.get("path") if isinstance(record, dict) else None
        for record in builder_sources
    ] != expected_builder_paths:
        raise ValueError("X0 provenance builder source list mismatch")
    for value in builder_sources:
        record = schema.strict_fields(value, {"path", "sha256"}, "builder source")
        relative = schema.bundle_path(record["path"], "builder source path")
        digest = schema.sha256_text(record["sha256"], "builder source sha256")
        if schema.file_sha256(ROOT / relative) != digest:
            raise ValueError(f"builder source hash mismatch: {relative}")
    expected_external = []
    for repository in sorted(inventories):
        inventory = inventories[repository]
        expected_external.append(
            {
                "repository": repository,
                "url": inventory["url"],
                "commit": inventory["commit"],
                "tree": inventory["tree"],
                "inventory_sha256": inventory["inventory_sha256"],
            }
        )
    if provenance["external_repositories"] != expected_external:
        raise ValueError("X0 provenance external repository list mismatch")
    expected_scope = [
        "README and artifact instructions",
        "repository manifests and immutable Git metadata",
        "benchmark and result indexes",
        "containers, lockfiles, and referenced configuration",
        "frozen result objects without executing a verifier or model",
    ]
    if provenance["inspection_scope"] != expected_scope:
        raise ValueError("X0 provenance inspection scope changed")
    return provenance


def validate(directory: Path) -> dict[str, object]:
    directory = directory.resolve()
    validate_integrity(directory)
    catalog = schema.validate_catalog(directory / "catalog.json")
    retrieval_directory = directory / "retrieval"
    retrieval_files = {
        path.relative_to(retrieval_directory).as_posix()
        for path in retrieval_directory.rglob("*")
        if path.is_file()
    }
    if retrieval_files != {"retrieval_freeze.json"}:
        raise ValueError("X0 bundle must not contain raw retrieval API payloads")
    retrieval = schema.validate_retrieval_manifest(
        retrieval_directory / "retrieval_freeze.json"
    )
    census = schema.validate_census(directory / "census.json", catalog, retrieval)
    canonical_census = schema.validate_census(
        ROOT / "scripts/cross_tool_x0_census_v1.json", catalog, retrieval
    )
    if census != canonical_census:
        raise ValueError("bundled census differs from canonical census input")
    inventories, entry_indexes = validate_inventories(
        directory, census, retrieval
    )
    source_files_document, source_file_index = validate_source_files(
        directory / "source_files.json", inventories, entry_indexes
    )
    reports = validate_reports(
        directory,
        catalog,
        census,
        inventories,
        source_file_index,
    )
    summary = validate_summary(
        directory / "summary.json", catalog, census, reports
    )
    validate_provenance(
        directory / "provenance.json",
        census,
        inventories,
        source_files_document,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the canonical cross-tool Gate X0 artifact bundle."
    )
    parser.add_argument("artifact_directory", type=Path)
    arguments = parser.parse_args()
    summary = validate(arguments.artifact_directory)
    print(
        f"valid {arguments.artifact_directory} "
        f"({summary['decision']}, {summary['summary_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
