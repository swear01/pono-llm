#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]

CATALOG_SCHEMA = "cross-tool-audit-candidate-catalog-v1"
RETRIEVAL_SCHEMA = "cross-tool-x0-retrieval-freeze-v1"
CENSUS_SCHEMA = "cross-tool-x0-census-v1"
INVENTORY_SCHEMA = "cross-tool-x0-repository-inventory-v1"
SOURCE_FILES_SCHEMA = "cross-tool-x0-source-files-v1"
REPORT_SCHEMA = "cross-tool-x0-candidate-report-v1"
SUMMARY_SCHEMA = "cross-tool-x0-summary-v1"
PROVENANCE_SCHEMA = "cross-tool-x0-provenance-v1"
INTEGRITY_SCHEMA = "cross-tool-x0-integrity-v1"

CATALOG_FILE_SHA256 = "b18a3b6e65bb642079b7ce8c9b58153936d0155a5f517562dc187bc780ede8bd"
CATALOG_SHA256 = "d8dfeaa65d6a34652f0018d9ac61a587ce884c208847094ee9750b0047a13fd3"
RETRIEVAL_FILE_SHA256 = "f819435d848b15349d2570ae88772fac9d260c76a27379daa70cf9b232655bbd"
RETRIEVAL_SHA256 = "1c4576d67a73b0ae771c6f7e37529933e5d1c9d981778bf45b70b0c21308c804"
PREREGISTRATION_COMMIT = "4d17851b746e30467b7c01e48bfce8b678a8955b"

REQUIRED_FIELDS = (
    "immutable_revision",
    "license",
    "implementation",
    "benchmark_inputs",
    "frozen_llm_outputs",
    "binding_locations",
    "expected_verdicts",
    "verifier_identity",
    "verifier_build",
    "offline_replay",
    "generation_config",
    "per_instance_timing",
    "result_provenance",
    "no_manual_repair",
)
FIELD_STATES = {"available", "missing", "blocked", "ambiguous"}

EXPECTED_CANDIDATES = {
    "cill": {
        "name": "CIll",
        "setting": "transition-system-model-checking",
        "setting_class": "model-checking",
        "repositories": {"gipsyh/rIC3", "gipsyh/cill-exp"},
    },
    "loris": {
        "name": "LORIS",
        "setting": "c-loop-invariant-synthesis",
        "setting_class": "source-program-verification",
        "repositories": {"ltcRandomwalk/LORIS"},
    },
    "quokka": {
        "name": "Quokka / InvBench",
        "setting": "c-invariant-acceleration",
        "setting_class": "source-program-verification",
        "repositories": {"Anjiang-Wei/Quokka"},
    },
    "autoverus": {
        "name": "AutoVerus",
        "setting": "verus-proof-synthesis",
        "setting_class": "deductive-proof-synthesis",
        "repositories": {"microsoft/verus-proof-synthesis"},
    },
    "exverus": {
        "name": "ExVerus",
        "setting": "verus-proof-repair",
        "setting_class": "deductive-proof-synthesis",
        "repositories": {"claudeyj/exverus"},
    },
}

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIRECTORY = re.compile(r"[A-Za-z0-9._-]+")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def document_sha256(document: dict[str, object], field: str) -> str:
    payload = dict(document)
    payload.pop(field, None)
    return canonical_sha256(payload)


def file_sha256(path: Path) -> str:
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


def strict_fields(
    value: object, expected: set[str], location: str
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{location} fields mismatch: "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )
    return value


def nonempty_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be non-empty text")
    return value


def sha256_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{location} must be a lowercase SHA-256 digest")
    return value


def commit_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError(f"{location} must be a full lowercase Git commit")
    return value


def repository_path(value: object, location: str) -> str:
    text = nonempty_text(value, location)
    if "\\" in text:
        raise ValueError(f"{location} must use POSIX separators")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"{location} must be a normalized repository-relative path")
    return text


def bundle_path(value: object, location: str) -> str:
    return repository_path(value, location)


def _validate_self_hash(
    document: dict[str, object], field: str, expected: str | None = None
) -> str:
    declared = sha256_text(document.get(field), field)
    actual = document_sha256(document, field)
    if declared != actual:
        raise ValueError(f"{field} self-hash mismatch: expected {declared}, got {actual}")
    if expected is not None and declared != expected:
        raise ValueError(f"{field} differs from preregistered digest")
    return declared


def validate_catalog(path: Path) -> dict[str, object]:
    if file_sha256(path) != CATALOG_FILE_SHA256:
        raise ValueError("candidate catalog file hash differs from preregistration")
    document = strict_fields(
        load_strict(path),
        {
            "schema",
            "candidates",
            "catalog_sha256",
            "freeze",
            "required_fields",
            "threshold",
        },
        "candidate catalog",
    )
    if document["schema"] != CATALOG_SCHEMA:
        raise ValueError("unsupported candidate catalog schema")
    _validate_self_hash(document, "catalog_sha256", CATALOG_SHA256)

    required_fields = document["required_fields"]
    if required_fields != list(REQUIRED_FIELDS):
        raise ValueError("candidate catalog required field order or content changed")

    freeze = strict_fields(
        document["freeze"],
        {
            "date",
            "literature_cutoff",
            "local_repository_clones_inspected",
            "new_llm_api_calls",
            "parent_commit",
            "prior_quokka_artifact_limitation_known",
            "replacement_candidates_authorized",
        },
        "candidate catalog freeze",
    )
    if freeze != {
        "date": "2026-07-14",
        "literature_cutoff": "2026-07-14",
        "local_repository_clones_inspected": 0,
        "new_llm_api_calls": 0,
        "parent_commit": "8e5e050b6898f06a01e82108950925996eedcbcb",
        "prior_quokka_artifact_limitation_known": True,
        "replacement_candidates_authorized": False,
    }:
        raise ValueError("candidate catalog freeze contract changed")

    threshold = strict_fields(
        document["threshold"],
        {
            "eligible_candidates",
            "eligible_settings",
            "failure_decision",
            "success_decision",
        },
        "candidate catalog threshold",
    )
    if threshold != {
        "eligible_candidates": 2,
        "eligible_settings": 2,
        "failure_decision": "STOP_X0_INSUFFICIENT_PUBLIC_ARTIFACTS",
        "success_decision": "GO_X1",
    }:
        raise ValueError("candidate catalog threshold changed")

    candidates = document["candidates"]
    if not isinstance(candidates, list) or len(candidates) != len(EXPECTED_CANDIDATES):
        raise ValueError("candidate catalog must contain the five frozen candidates")
    seen: set[str] = set()
    for index, candidate_value in enumerate(candidates):
        candidate = strict_fields(
            candidate_value,
            {
                "artifact_discovery_urls",
                "candidate_id",
                "name",
                "paper_url",
                "reported_claim",
                "setting",
                "setting_class",
            },
            f"candidate catalog candidate {index}",
        )
        candidate_id = nonempty_text(candidate["candidate_id"], "candidate_id")
        if candidate_id in seen:
            raise ValueError(f"duplicate candidate_id: {candidate_id}")
        seen.add(candidate_id)
        expected = EXPECTED_CANDIDATES.get(candidate_id)
        if expected is None:
            raise ValueError(f"unexpected candidate_id: {candidate_id}")
        for field in ("name", "setting", "setting_class"):
            if candidate[field] != expected[field]:
                raise ValueError(f"{candidate_id} {field} differs from candidate freeze")
        discovery_urls = candidate["artifact_discovery_urls"]
        if not isinstance(discovery_urls, list) or not discovery_urls:
            raise ValueError(f"{candidate_id} artifact_discovery_urls must be non-empty")
        for url in discovery_urls:
            if not nonempty_text(url, f"{candidate_id} discovery URL").startswith("https://"):
                raise ValueError(f"{candidate_id} discovery URL must use HTTPS")
        for field in ("paper_url", "reported_claim"):
            nonempty_text(candidate[field], f"{candidate_id}.{field}")
    if seen != set(EXPECTED_CANDIDATES):
        raise ValueError("candidate catalog set mismatch")
    return document


def _validate_retrieval_document(
    path: Path, github_directory: Path | None
) -> dict[str, object]:
    if file_sha256(path) != RETRIEVAL_FILE_SHA256:
        raise ValueError("retrieval freeze file hash differs from frozen retrieval")
    document = strict_fields(
        load_strict(path),
        {
            "catalog_sha256",
            "freeze_sha256",
            "llm_api_calls",
            "repositories",
            "repository_files_inspected_before_freeze",
            "retrieved_at_utc",
            "schema",
            "search_evidence",
        },
        "retrieval freeze",
    )
    if document["schema"] != RETRIEVAL_SCHEMA:
        raise ValueError("unsupported retrieval freeze schema")
    _validate_self_hash(document, "freeze_sha256", RETRIEVAL_SHA256)
    if document["catalog_sha256"] != CATALOG_FILE_SHA256:
        raise ValueError("retrieval freeze points to a different catalog file")
    if document["llm_api_calls"] != 0:
        raise ValueError("retrieval freeze contains an LLM/API call")
    if document["repository_files_inspected_before_freeze"] != 0:
        raise ValueError("repository files were inspected before retrieval freeze")
    timestamp = nonempty_text(document["retrieved_at_utc"], "retrieved_at_utc")
    if not _UTC_TIMESTAMP.fullmatch(timestamp):
        raise ValueError("retrieved_at_utc must be an explicit UTC timestamp")

    repositories = document["repositories"]
    if not isinstance(repositories, dict) or set(repositories) != set(EXPECTED_CANDIDATES):
        raise ValueError("retrieval repository candidate set mismatch")
    expected_github_files: set[str] = set()
    seen_repositories: set[str] = set()
    for candidate_id, records_value in repositories.items():
        if not isinstance(records_value, list) or not records_value:
            raise ValueError(f"{candidate_id} retrieval records must be non-empty")
        expected_repositories = EXPECTED_CANDIDATES[candidate_id]["repositories"]
        actual_repositories: set[str] = set()
        for index, record_value in enumerate(records_value):
            record = strict_fields(
                record_value,
                {
                    "default_branch",
                    "license_spdx",
                    "metadata_files",
                    "release_count",
                    "repository",
                    "resolved_commit",
                    "tag_count",
                    "url",
                },
                f"retrieval {candidate_id}[{index}]",
            )
            repository = nonempty_text(record["repository"], "repository")
            if repository in seen_repositories:
                raise ValueError(f"duplicate retrieval repository: {repository}")
            seen_repositories.add(repository)
            actual_repositories.add(repository)
            commit_text(record["resolved_commit"], f"{repository}.resolved_commit")
            if record["url"] != f"https://github.com/{repository}":
                raise ValueError(f"{repository} URL mismatch")
            nonempty_text(record["default_branch"], f"{repository}.default_branch")
            if record["license_spdx"] is not None:
                nonempty_text(record["license_spdx"], f"{repository}.license_spdx")
            for count_field in ("release_count", "tag_count"):
                if not isinstance(record[count_field], int) or record[count_field] < 0:
                    raise ValueError(f"{repository}.{count_field} must be non-negative")
            metadata = strict_fields(
                record["metadata_files"],
                {"commit", "releases", "repo", "tags"},
                f"{repository}.metadata_files",
            )
            stem = repository.replace("/", "__")
            for kind, digest_value in metadata.items():
                digest = sha256_text(digest_value, f"{repository}.{kind} hash")
                filename = f"{stem}.{kind}.json"
                expected_github_files.add(filename)
                if github_directory is not None:
                    metadata_path = github_directory / filename
                    if (
                        not metadata_path.is_file()
                        or file_sha256(metadata_path) != digest
                    ):
                        raise ValueError(f"retrieval metadata mismatch: {filename}")
        if actual_repositories != expected_repositories:
            raise ValueError(f"{candidate_id} retrieval repository set mismatch")

    search_evidence = strict_fields(
        document["search_evidence"], {"cill", "exverus"}, "search evidence"
    )
    for candidate_id, digest_value in search_evidence.items():
        digest = sha256_text(digest_value, f"{candidate_id} search evidence hash")
        filename = f"{candidate_id}.search.json"
        expected_github_files.add(filename)
        if github_directory is not None:
            evidence_path = github_directory / filename
            if not evidence_path.is_file() or file_sha256(evidence_path) != digest:
                raise ValueError(f"retrieval search evidence mismatch: {filename}")
    if github_directory is not None:
        actual_github_files = {
            item.name for item in github_directory.iterdir() if item.is_file()
        }
        if actual_github_files != expected_github_files:
            raise ValueError(
                "retrieval GitHub evidence file set mismatch: "
                f"missing={sorted(expected_github_files - actual_github_files)}, "
                f"unknown={sorted(actual_github_files - expected_github_files)}"
            )
    return document


def validate_retrieval_freeze(
    path: Path, github_directory: Path
) -> dict[str, object]:
    return _validate_retrieval_document(path, github_directory)


def validate_retrieval_manifest(path: Path) -> dict[str, object]:
    return _validate_retrieval_document(path, None)


def retrieval_records(document: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    repositories = document["repositories"]
    assert isinstance(repositories, dict)
    for records in repositories.values():
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            result[str(record["repository"])] = record
    return result


def _validate_census_evidence(
    value: object,
    location: str,
    allowed_repositories: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    kind = value.get("kind")
    if kind == "repository-commit":
        record = strict_fields(value, {"kind", "repository"}, location)
    elif kind == "repository-inventory":
        record = strict_fields(value, {"kind", "repository"}, location)
    elif kind == "repository-object":
        record = strict_fields(value, {"kind", "repository", "path"}, location)
        repository_path(record["path"], f"{location}.path")
    elif kind == "repository-file":
        record = strict_fields(
            value,
            {"kind", "repository", "path", "line_start", "line_end"},
            location,
        )
        repository_path(record["path"], f"{location}.path")
        line_start = record["line_start"]
        line_end = record["line_end"]
        if (
            not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
        ):
            raise ValueError(f"{location} line range is invalid")
    else:
        raise ValueError(f"{location} has unsupported evidence kind: {kind}")
    repository = nonempty_text(record["repository"], f"{location}.repository")
    if repository not in allowed_repositories:
        raise ValueError(f"{location} references a repository outside its candidate")
    return record


def validate_census(
    path: Path,
    catalog: dict[str, object],
    retrieval: dict[str, object],
) -> dict[str, object]:
    document = strict_fields(
        load_strict(path),
        {
            "schema",
            "inspection_completed_at_utc",
            "preregistration_commit",
            "catalog_sha256",
            "retrieval_freeze_sha256",
            "repositories",
            "candidates",
            "execution",
            "census_sha256",
        },
        "cross-tool census",
    )
    if document["schema"] != CENSUS_SCHEMA:
        raise ValueError("unsupported cross-tool census schema")
    _validate_self_hash(document, "census_sha256")
    timestamp = nonempty_text(
        document["inspection_completed_at_utc"], "inspection_completed_at_utc"
    )
    if not _UTC_TIMESTAMP.fullmatch(timestamp):
        raise ValueError("inspection_completed_at_utc must be an explicit UTC timestamp")
    if document["preregistration_commit"] != PREREGISTRATION_COMMIT:
        raise ValueError("census preregistration commit mismatch")
    if document["catalog_sha256"] != catalog["catalog_sha256"]:
        raise ValueError("census catalog hash mismatch")
    if document["retrieval_freeze_sha256"] != retrieval["freeze_sha256"]:
        raise ValueError("census retrieval freeze hash mismatch")

    execution = strict_fields(
        document["execution"],
        {
            "new_llm_api_calls",
            "verifier_executions",
            "author_contacts",
            "fresh_generated_outputs",
            "threshold_changes",
        },
        "census execution",
    )
    if execution != {
        "new_llm_api_calls": 0,
        "verifier_executions": 0,
        "author_contacts": 0,
        "fresh_generated_outputs": 0,
        "threshold_changes": False,
    }:
        raise ValueError("Gate X0 census performed an unauthorized action")

    frozen_records = retrieval_records(retrieval)
    repositories = document["repositories"]
    if not isinstance(repositories, list) or len(repositories) != len(frozen_records):
        raise ValueError("census repository count mismatch")
    seen_repositories: set[str] = set()
    seen_directories: set[str] = set()
    for index, value in enumerate(repositories):
        record = strict_fields(
            value,
            {"candidate_id", "repository", "directory"},
            f"census repository {index}",
        )
        candidate_id = nonempty_text(record["candidate_id"], "candidate_id")
        repository = nonempty_text(record["repository"], "repository")
        directory = nonempty_text(record["directory"], "directory")
        if not _DIRECTORY.fullmatch(directory):
            raise ValueError(f"invalid census repository directory: {directory}")
        if repository in seen_repositories or directory in seen_directories:
            raise ValueError("duplicate census repository or directory")
        seen_repositories.add(repository)
        seen_directories.add(directory)
        if repository not in frozen_records:
            raise ValueError(f"census repository was not frozen: {repository}")
        if candidate_id not in EXPECTED_CANDIDATES or repository not in EXPECTED_CANDIDATES[candidate_id]["repositories"]:
            raise ValueError(f"census repository candidate mismatch: {repository}")
    if seen_repositories != set(frozen_records):
        raise ValueError("census repository set mismatch")

    candidates = document["candidates"]
    if not isinstance(candidates, list) or len(candidates) != len(EXPECTED_CANDIDATES):
        raise ValueError("census candidate count mismatch")
    seen_candidates: set[str] = set()
    for candidate_index, value in enumerate(candidates):
        candidate = strict_fields(
            value,
            {"candidate_id", "fields"},
            f"census candidate {candidate_index}",
        )
        candidate_id = nonempty_text(candidate["candidate_id"], "candidate_id")
        if candidate_id in seen_candidates or candidate_id not in EXPECTED_CANDIDATES:
            raise ValueError(f"duplicate or unknown census candidate: {candidate_id}")
        seen_candidates.add(candidate_id)
        fields = candidate["fields"]
        if not isinstance(fields, dict) or set(fields) != set(REQUIRED_FIELDS):
            raise ValueError(f"{candidate_id} census field set mismatch")
        allowed_repositories = EXPECTED_CANDIDATES[candidate_id]["repositories"]
        for field_name in REQUIRED_FIELDS:
            field = strict_fields(
                fields[field_name],
                {"state", "finding", "evidence"},
                f"{candidate_id}.{field_name}",
            )
            if field["state"] not in FIELD_STATES:
                raise ValueError(f"{candidate_id}.{field_name} has invalid state")
            nonempty_text(field["finding"], f"{candidate_id}.{field_name}.finding")
            evidence = field["evidence"]
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"{candidate_id}.{field_name} evidence must be non-empty")
            for evidence_index, evidence_value in enumerate(evidence):
                _validate_census_evidence(
                    evidence_value,
                    f"{candidate_id}.{field_name}.evidence[{evidence_index}]",
                    allowed_repositories,
                )
    if seen_candidates != set(EXPECTED_CANDIDATES):
        raise ValueError("census candidate set mismatch")
    return document


def candidate_catalog_index(catalog: dict[str, object]) -> dict[str, dict[str, object]]:
    candidates = catalog["candidates"]
    assert isinstance(candidates, list)
    return {str(candidate["candidate_id"]): candidate for candidate in candidates}


def census_candidate_index(census: dict[str, object]) -> dict[str, dict[str, object]]:
    candidates = census["candidates"]
    assert isinstance(candidates, list)
    return {str(candidate["candidate_id"]): candidate for candidate in candidates}


def census_repository_index(census: dict[str, object]) -> dict[str, dict[str, object]]:
    repositories = census["repositories"]
    assert isinstance(repositories, list)
    return {str(record["repository"]): record for record in repositories}
