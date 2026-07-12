#!/usr/bin/env python3
"""Stable benchmark identities for replayable experiments."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_BENCHMARK_ROOT = Path(
    os.environ.get("HWMCC_ROOT", "/home/swear01/hwmcc_benchmarks")
)
CAPTURE_INTEGRITY_FILE = "integrity.json"
MATRIX_CONTRACT_FIELDS = (
    "matrix_benchmark_count",
    "matrix_config_count",
    "matrix_trial_count",
    "matrix_expected_row_count",
    "matrix_benchmark_set_sha256",
    "matrix_contract_sha256",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CAPTURE_SCHEMAS = {
    "pono-llm-candidate-capture-v2",
    "pono-llm-candidate-capture-v2-migrated",
    "pono-llm-candidate-capture-v3",
    "pono-llm-candidate-capture-v4",
}
_CAPTURE_META_SCHEMAS = {
    "pono-llm-candidate-meta-v2",
    "pono-llm-candidate-meta-v2-migrated",
    "pono-llm-candidate-meta-v3",
    "pono-llm-candidate-meta-v4",
}


@dataclass(frozen=True)
class BenchmarkSpec:
    benchmark_id: str
    path: Path
    content_sha256: str | None = None


def normalise_sha256(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value.lower()):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return value.lower()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def replay_matrix_contract(
    benchmark_hashes: dict[str, str],
    configs: list[str] | tuple[str, ...] | set[str],
    trials: int,
) -> dict[str, str]:
    if not isinstance(trials, int) or trials <= 0:
        raise ValueError("matrix contract trials must be positive")
    config_list = sorted(configs)
    if not config_list or any(not isinstance(config, str) or not config for config in config_list):
        raise ValueError("matrix contract configs must be non-empty strings")
    if len(config_list) != len(set(config_list)):
        raise ValueError("matrix contract configs must be unique")

    benchmarks = []
    for raw_id, raw_digest in benchmark_hashes.items():
        benchmark_id = _normalise_id(raw_id)
        digest = normalise_sha256(
            raw_digest, f"matrix content_sha256 for {benchmark_id}"
        )
        if digest is None:
            raise ValueError(f"matrix content hash is missing for {benchmark_id}")
        benchmarks.append({
            "benchmark_id": benchmark_id,
            "content_sha256": digest,
        })
    benchmarks.sort(key=lambda row: row["benchmark_id"])
    if len(benchmarks) != len({row["benchmark_id"] for row in benchmarks}):
        raise ValueError("matrix contract contains duplicate benchmark IDs")

    benchmark_set_sha256 = _canonical_sha256({
        "schema": "pono-llm-replay-benchmark-set-v1",
        "benchmarks": benchmarks,
    })
    contract_sha256 = _canonical_sha256({
        "schema": "pono-llm-replay-contract-v1",
        "benchmark_set_sha256": benchmark_set_sha256,
        "configs": config_list,
        "trials": trials,
    })
    return {
        "matrix_benchmark_count": str(len(benchmarks)),
        "matrix_config_count": str(len(config_list)),
        "matrix_trial_count": str(trials),
        "matrix_expected_row_count": str(
            len(benchmarks) * len(config_list) * trials
        ),
        "matrix_benchmark_set_sha256": benchmark_set_sha256,
        "matrix_contract_sha256": contract_sha256,
    }


def validate_replay_matrix(
    rows: list[dict],
    benchmark_hashes: dict[str, str],
    configs: list[str] | tuple[str, ...] | set[str],
    trials: int,
    *,
    benchmark_manifest_sha256: str | None = None,
) -> dict[str, str]:
    if not rows:
        raise ValueError("replay matrix contains no rows")
    expected = replay_matrix_contract(benchmark_hashes, configs, trials)
    expected_ids = set(benchmark_hashes)
    expected_configs = set(configs)
    expected_identities = {
        (benchmark_id, config, trial)
        for benchmark_id in expected_ids
        for config in expected_configs
        for trial in range(trials)
    }
    identities = set()
    source_hash = normalise_sha256(
        benchmark_manifest_sha256, "benchmark manifest sha256"
    )
    for row_number, row in enumerate(rows, start=2):
        benchmark_id = row.get("benchmark_id", "")
        if benchmark_id not in expected_ids:
            raise ValueError(
                f"matrix row {row_number} has unexpected benchmark ID: "
                f"{benchmark_id!r}"
            )
        config = row.get("config", "")
        if config not in expected_configs:
            raise ValueError(
                f"matrix row {row_number} has unexpected config: {config!r}"
            )
        try:
            trial = int(row.get("trial", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"matrix row {row_number} has invalid trial"
            ) from exc
        identity = (benchmark_id, config, trial)
        if identity in identities:
            raise ValueError(f"duplicate replay identity: {identity}")
        identities.add(identity)

        digest = normalise_sha256(
            row.get("benchmark_content_sha256"),
            f"matrix content_sha256 for {benchmark_id}",
        )
        expected_digest = normalise_sha256(
            benchmark_hashes[benchmark_id],
            f"expected content_sha256 for {benchmark_id}",
        )
        if digest != expected_digest:
            raise ValueError(
                f"matrix/model content hash mismatch for {benchmark_id}"
            )
        for field, value in expected.items():
            if row.get(field) != value:
                raise ValueError(
                    f"matrix row {row_number} has invalid {field}: "
                    f"expected {value!r}, got {row.get(field)!r}"
                )
        if source_hash is not None and row.get("benchmark_manifest_sha256") != source_hash:
            raise ValueError(
                f"matrix row {row_number} references a different benchmark manifest"
            )

    if identities != expected_identities:
        missing = sorted(expected_identities - identities)
        extra = sorted(identities - expected_identities)
        raise ValueError(
            "replay matrix does not satisfy its benchmark/config/trial contract: "
            f"missing={missing[:5]}, extra={extra[:5]}"
        )
    return expected


def verify_benchmark_content(spec: BenchmarkSpec, expected: str | None = None) -> str:
    declared = normalise_sha256(spec.content_sha256, "content_sha256")
    supplied = normalise_sha256(expected, "expected content_sha256")
    if declared and supplied and declared != supplied:
        raise ValueError(
            f"conflicting content hashes for {spec.benchmark_id}: "
            f"{declared} != {supplied}"
        )
    wanted = declared or supplied
    actual = file_sha256(spec.path)
    if wanted and actual != wanted:
        raise ValueError(
            f"benchmark content hash mismatch for {spec.benchmark_id}: "
            f"expected {wanted}, got {actual} ({spec.path})"
        )
    return actual


def stable_slug(benchmark_id: str) -> str:
    name = Path(benchmark_id).name
    for suffix in (".btor2", ".btor"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    digest = hashlib.sha256(benchmark_id.encode()).hexdigest()[:12]
    return f"{safe}-{digest}"


def _normalise_id(benchmark_id: str) -> str:
    value = benchmark_id.strip().replace("\\", "/")
    if not value:
        raise ValueError("benchmark_id must not be empty")
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"benchmark_id must be a relative path without '..': {value}")
    return p.as_posix()


def benchmark_id_for_path(path: str | Path, benchmark_root: str | Path) -> str:
    root = Path(benchmark_root).expanduser().resolve()
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"benchmark path is outside benchmark root {root}: {resolved}; "
            "use a CSV/JSON manifest with an explicit benchmark_id"
        ) from exc


def make_spec(
    path: str | Path,
    benchmark_root: str | Path,
    benchmark_id: str | None = None,
    content_sha256: str | None = None,
) -> BenchmarkSpec:
    root = Path(benchmark_root).expanduser().resolve()
    raw_path = Path(path).expanduser()
    resolved = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()
    stable_id = (
        _normalise_id(benchmark_id)
        if benchmark_id is not None
        else benchmark_id_for_path(resolved, root)
    )
    return BenchmarkSpec(
        stable_id,
        resolved,
        normalise_sha256(content_sha256, f"content_sha256 for {stable_id}"),
    )


def _specs_from_rows(rows: list[dict], benchmark_root: Path) -> list[BenchmarkSpec]:
    specs: list[BenchmarkSpec] = []
    for index, row in enumerate(rows, start=1):
        raw_path = row.get("path") or row.get("benchmark_id")
        if not raw_path:
            raise ValueError(f"manifest row {index} has neither path nor benchmark_id")
        specs.append(
            make_spec(
                raw_path,
                benchmark_root,
                row.get("benchmark_id"),
                row.get("content_sha256"),
            )
        )
    return specs


def load_manifest(path: str | Path, benchmark_root: str | Path) -> list[BenchmarkSpec]:
    manifest_path = Path(path)
    root = Path(benchmark_root).expanduser().resolve()
    text = manifest_path.read_text()
    stripped = text.lstrip()
    if not stripped:
        return []

    if stripped[0] in "[{":
        obj = json.loads(text)
        if isinstance(obj, dict):
            rows = obj.get("benchmarks")
            if not isinstance(rows, list):
                raise ValueError("JSON manifest must contain a benchmarks list")
        elif isinstance(obj, list):
            rows = obj
        else:
            raise ValueError("JSON manifest must be an object or list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("JSON manifest benchmark entries must be objects")
        return _deduplicate(_specs_from_rows(rows, root))

    lines = text.splitlines()
    first = next((line for line in lines if line.strip() and not line.lstrip().startswith("#")), "")
    if first.split(",")[0].strip() in {"path", "benchmark_id"}:
        csv_lines = [
            line
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        ]
        rows = list(csv.DictReader(csv_lines))
        return _deduplicate(_specs_from_rows(rows, root))

    specs = []
    for lineno, line in enumerate(lines, start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "," in value:
            raise ValueError(
                f"manifest line {lineno} contains a comma but has no CSV header"
            )
        specs.append(make_spec(value, root))
    return _deduplicate(specs)


def _deduplicate(specs: list[BenchmarkSpec]) -> list[BenchmarkSpec]:
    by_id: dict[str, BenchmarkSpec] = {}
    positions: dict[str, int] = {}
    out: list[BenchmarkSpec] = []
    for spec in specs:
        previous = by_id.get(spec.benchmark_id)
        if previous is not None:
            if previous.path != spec.path:
                raise ValueError(
                    f"benchmark_id {spec.benchmark_id!r} maps to both "
                    f"{previous.path} and {spec.path}"
                )
            if (
                previous.content_sha256
                and spec.content_sha256
                and previous.content_sha256 != spec.content_sha256
            ):
                raise ValueError(
                    f"benchmark_id {spec.benchmark_id!r} has conflicting "
                    "content_sha256 values"
                )
            if previous.content_sha256 is None and spec.content_sha256:
                by_id[spec.benchmark_id] = spec
                out[positions[spec.benchmark_id]] = spec
            continue
        by_id[spec.benchmark_id] = spec
        positions[spec.benchmark_id] = len(out)
        out.append(spec)
    return out


def _capture_file(capture_dir: Path, relative: object, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{field} must name a capture file")
    relpath = Path(relative)
    if relpath.is_absolute() or ".." in relpath.parts:
        raise ValueError(f"{field} must be a relative path inside the capture")
    path = (capture_dir / relpath).resolve()
    if capture_dir.resolve() not in path.parents:
        raise ValueError(f"{field} escapes the capture directory")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _capture_entries(manifest: dict) -> dict[str, dict]:
    entries = manifest.get("benchmarks")
    if not isinstance(entries, list):
        raise ValueError("capture manifest must contain a benchmarks list")
    by_id: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"capture manifest benchmark {index} must be an object")
        raw_id = entry.get("benchmark_id")
        if not isinstance(raw_id, str):
            raise ValueError(f"capture manifest benchmark {index} has no benchmark_id")
        benchmark_id = _normalise_id(raw_id)
        if benchmark_id in by_id:
            raise ValueError(f"duplicate capture benchmark_id: {benchmark_id}")
        by_id[benchmark_id] = entry
    return by_id


def write_capture_integrity(
    capture_dir: str | Path,
    benchmark_hashes: dict[str, str],
    *,
    recorded_after_capture: bool,
) -> Path:
    directory = Path(capture_dir).resolve()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entries = _capture_entries(manifest)
    if set(entries) != set(benchmark_hashes):
        raise ValueError("capture manifest and benchmark hash sets differ")

    records = []
    for benchmark_id, entry in sorted(entries.items()):
        record = {
            "benchmark_id": benchmark_id,
            "content_sha256": normalise_sha256(
                benchmark_hashes[benchmark_id],
                f"content_sha256 for {benchmark_id}",
            ),
        }
        for field in (
            "metadata_file",
            "predicates_file",
            "prompt_file",
            "responses_file",
        ):
            relative = entry.get(field)
            record[field] = relative
            if relative is None and field == "responses_file":
                record["responses_sha256"] = None
                continue
            path = _capture_file(directory, relative, field)
            record[field.replace("_file", "_sha256")] = file_sha256(path)
        records.append(record)

    global_files = []
    for field in ("provenance_file", "system_prompt_file"):
        relative = manifest.get(field)
        if not relative:
            continue
        path = _capture_file(directory, relative, field)
        global_files.append({"path": relative, "sha256": file_sha256(path)})

    payload = {
        "schema": "pono-llm-capture-integrity-v1",
        "status": "completed",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "recorded_after_capture": recorded_after_capture,
        "capture_manifest_file": manifest_path.name,
        "capture_manifest_sha256": file_sha256(manifest_path),
        "benchmarks": records,
        "global_files": global_files,
    }
    destination = directory / CAPTURE_INTEGRITY_FILE
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(destination)
    return destination


def _validate_response_records(path: Path, meta: dict) -> None:
    records = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid response JSON at {path}:{lineno}") from exc
        if not isinstance(record, dict) or not isinstance(record.get("response"), str):
            raise ValueError(f"invalid response record at {path}:{lineno}")
        digest = hashlib.sha256(record["response"].encode()).hexdigest()
        if record.get("response_sha256") != digest:
            raise ValueError(f"response hash mismatch at {path}:{lineno}")
        records.append(record)

    calls = meta.get("llm_calls", [])
    if not isinstance(calls, list) or len(records) != len(calls):
        raise ValueError(f"response/call count mismatch in {path}")
    calls_by_round = {call.get("round"): call for call in calls}
    if len(calls_by_round) != len(calls):
        raise ValueError(f"duplicate LLM call round in {path}")
    for record in records:
        call = calls_by_round.get(record.get("round"))
        if call is None:
            raise ValueError(f"response round missing from metadata in {path}")
        expected = call.get("response_sha256")
        if expected is not None and expected != record["response_sha256"]:
            raise ValueError(f"response/metadata hash mismatch in {path}")


def validate_capture_archive(capture_dir: str | Path) -> dict:
    directory = Path(capture_dir).resolve()
    manifest_path = directory / "manifest.json"
    integrity_path = directory / CAPTURE_INTEGRITY_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    if not integrity_path.is_file():
        raise FileNotFoundError(integrity_path)

    manifest = json.loads(manifest_path.read_text())
    schema = manifest.get("schema")
    if schema not in _CAPTURE_SCHEMAS:
        raise ValueError(f"unsupported capture manifest schema: {schema!r}")
    entries = _capture_entries(manifest)

    integrity = json.loads(integrity_path.read_text())
    if integrity.get("schema") != "pono-llm-capture-integrity-v1":
        raise ValueError("unsupported capture integrity schema")
    if integrity.get("status") != "completed":
        raise ValueError("capture integrity status is not completed")
    if not isinstance(integrity.get("recorded_after_capture"), bool):
        raise ValueError("capture integrity recorded_after_capture must be boolean")
    if integrity.get("capture_manifest_file") != manifest_path.name:
        raise ValueError("capture integrity references a different manifest")
    if integrity.get("capture_manifest_sha256") != file_sha256(manifest_path):
        raise ValueError("capture manifest hash does not match integrity sidecar")

    integrity_records = integrity.get("benchmarks")
    if not isinstance(integrity_records, list):
        raise ValueError("capture integrity must contain a benchmarks list")
    integrity_by_id: dict[str, dict] = {}
    for record in integrity_records:
        if not isinstance(record, dict):
            raise ValueError("capture integrity benchmark must be an object")
        raw_id = record.get("benchmark_id")
        if not isinstance(raw_id, str):
            raise ValueError("capture integrity benchmark has no benchmark_id")
        benchmark_id = _normalise_id(raw_id)
        if benchmark_id in integrity_by_id:
            raise ValueError(f"duplicate integrity benchmark_id: {benchmark_id}")
        integrity_by_id[benchmark_id] = record
    if set(entries) != set(integrity_by_id):
        raise ValueError("capture manifest and integrity benchmark sets differ")

    global_records = integrity.get("global_files", [])
    if not isinstance(global_records, list):
        raise ValueError("capture integrity global_files must be a list")
    global_by_path = {}
    for record in global_records:
        if not isinstance(record, dict):
            raise ValueError("capture global-file record must be an object")
        path = _capture_file(directory, record.get("path"), "global file")
        if record["path"] in global_by_path:
            raise ValueError(f"duplicate capture global file: {record['path']}")
        if normalise_sha256(record.get("sha256"), "global file sha256") != file_sha256(path):
            raise ValueError(f"capture global file hash mismatch: {path}")
        global_by_path[record["path"]] = record
    for field in ("provenance_file", "system_prompt_file"):
        relative = manifest.get(field)
        if relative and relative not in global_by_path:
            raise ValueError(f"capture integrity omits {field}: {relative}")
    provenance_relative = manifest.get("provenance_file")
    system_prompt_relative = manifest.get("system_prompt_file")
    if provenance_relative:
        provenance_path = _capture_file(
            directory, provenance_relative, "provenance_file"
        )
        provenance = json.loads(provenance_path.read_text())
        if provenance.get("schema") != "pono-llm-capture-provenance-v1":
            raise ValueError("unsupported capture provenance schema")
        if not isinstance(provenance.get("recorded_after_capture"), bool):
            raise ValueError(
                "capture provenance recorded_after_capture must be boolean"
            )
        if provenance.get("system_prompt_file") != system_prompt_relative:
            raise ValueError("capture provenance references a different system prompt")
        system_prompt_path = _capture_file(
            directory, system_prompt_relative, "system_prompt_file"
        )
        if provenance.get("system_prompt_sha256") != file_sha256(
            system_prompt_path
        ):
            raise ValueError("capture provenance system-prompt hash mismatch")
    if schema == "pono-llm-candidate-capture-v4":
        if manifest.get("integrity_file") != CAPTURE_INTEGRITY_FILE:
            raise ValueError("capture v4 manifest must declare integrity.json")
        if integrity.get("recorded_after_capture"):
            raise ValueError("capture v4 integrity must be finalized during capture")
        for field in ("provenance_file", "system_prompt_file"):
            relative = manifest.get(field)
            if not isinstance(relative, str) or not relative:
                raise ValueError(f"capture v4 manifest must declare {field}")
            if relative not in global_by_path:
                raise ValueError(f"capture v4 integrity omits {field}: {relative}")
        if provenance.get("recorded_after_capture"):
            raise ValueError("capture v4 provenance must be native")

    validated = {}
    for benchmark_id, entry in entries.items():
        record = integrity_by_id[benchmark_id]
        content_sha256 = normalise_sha256(
            record.get("content_sha256"),
            f"capture content_sha256 for {benchmark_id}",
        )
        if content_sha256 is None:
            raise ValueError(f"capture benchmark hash is missing for {benchmark_id}")
        entry_content_sha256 = normalise_sha256(
            entry.get("content_sha256"),
            f"manifest content_sha256 for {benchmark_id}",
        )
        if schema == "pono-llm-candidate-capture-v4" and (
            entry_content_sha256 != content_sha256
        ):
            raise ValueError(f"capture manifest content hash mismatch for {benchmark_id}")
        if entry_content_sha256 and entry_content_sha256 != content_sha256:
            raise ValueError(f"capture manifest/integrity hash mismatch for {benchmark_id}")

        slug = stable_slug(benchmark_id)
        if entry.get("slug") != slug:
            raise ValueError(f"capture slug mismatch for {benchmark_id}")
        paths = {}
        for field in ("metadata_file", "predicates_file", "prompt_file"):
            if record.get(field) != entry.get(field):
                raise ValueError(f"capture {field} mismatch for {benchmark_id}")
            path = _capture_file(directory, entry.get(field), field)
            digest_field = field.replace("_file", "_sha256")
            expected_digest = normalise_sha256(
                record.get(digest_field), f"{digest_field} for {benchmark_id}"
            )
            if expected_digest != file_sha256(path):
                raise ValueError(f"capture {field} hash mismatch for {benchmark_id}")
            paths[field] = path

        responses_relative = entry.get("responses_file")
        if record.get("responses_file") != responses_relative:
            raise ValueError(f"capture responses_file mismatch for {benchmark_id}")
        responses_path = None
        if responses_relative is not None:
            responses_path = _capture_file(
                directory, responses_relative, "responses_file"
            )
            expected_digest = normalise_sha256(
                record.get("responses_sha256"),
                f"responses_sha256 for {benchmark_id}",
            )
            if expected_digest != file_sha256(responses_path):
                raise ValueError(f"capture response hash mismatch for {benchmark_id}")
        elif schema != "pono-llm-candidate-capture-v2-migrated":
            raise ValueError(f"capture responses are missing for {benchmark_id}")

        meta = json.loads(paths["metadata_file"].read_text())
        if meta.get("schema") not in _CAPTURE_META_SCHEMAS:
            raise ValueError(f"unsupported capture metadata schema for {benchmark_id}")
        if meta.get("benchmark_id") != benchmark_id or meta.get("slug") != slug:
            raise ValueError(f"capture metadata identity mismatch for {benchmark_id}")
        if meta.get("predicates_file") != entry.get("predicates_file"):
            raise ValueError(f"capture predicate metadata mismatch for {benchmark_id}")
        if meta.get("prompt_file") != entry.get("prompt_file"):
            raise ValueError(f"capture prompt metadata mismatch for {benchmark_id}")
        if meta.get("responses_file") != responses_relative:
            raise ValueError(f"capture response metadata mismatch for {benchmark_id}")
        if schema in {
            "pono-llm-candidate-capture-v3",
            "pono-llm-candidate-capture-v4",
        } and meta.get("status") != "completed":
            raise ValueError(f"capture metadata is incomplete for {benchmark_id}")
        meta_content_sha256 = normalise_sha256(
            meta.get("benchmark_content_sha256"),
            f"metadata content_sha256 for {benchmark_id}",
        )
        if schema == "pono-llm-candidate-capture-v4" and (
            meta_content_sha256 != content_sha256
        ):
            raise ValueError(f"capture metadata content hash mismatch for {benchmark_id}")
        if meta_content_sha256 and meta_content_sha256 != content_sha256:
            raise ValueError(f"capture metadata/integrity hash mismatch for {benchmark_id}")

        predicate_digest = file_sha256(paths["predicates_file"])
        prompt_digest = file_sha256(paths["prompt_file"])
        if meta.get("predicates_sha256") != predicate_digest:
            raise ValueError(f"predicate metadata hash mismatch for {benchmark_id}")
        if meta.get("prompt_sha256") != prompt_digest:
            raise ValueError(f"prompt metadata hash mismatch for {benchmark_id}")
        candidate_count = sum(
            bool(line.strip())
            for line in paths["predicates_file"].read_text().splitlines()
        )
        if int(meta.get("dedup_candidate_count", -1)) != candidate_count:
            raise ValueError(f"candidate count mismatch for {benchmark_id}")
        calls = meta.get("llm_calls", [])
        if not isinstance(calls, list):
            raise ValueError(f"LLM calls metadata must be a list for {benchmark_id}")
        if int(meta.get("rounds", -1)) != len(calls):
            raise ValueError(f"LLM round count mismatch for {benchmark_id}")
        if responses_path is not None:
            _validate_response_records(responses_path, meta)

        validated[benchmark_id] = {
            "entry": entry,
            "meta": meta,
            "predicate_path": paths["predicates_file"],
            "content_sha256": content_sha256,
        }

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": file_sha256(manifest_path),
        "integrity": integrity,
        "integrity_path": integrity_path,
        "integrity_sha256": file_sha256(integrity_path),
        "records": validated,
    }


def validate_capture_bundle(
    capture_dir: str | Path,
    benchmarks: list[BenchmarkSpec],
) -> dict:
    bundle = validate_capture_archive(capture_dir)
    requested = {benchmark.benchmark_id: benchmark for benchmark in benchmarks}
    missing = sorted(set(requested) - set(bundle["records"]))
    if missing:
        raise ValueError("capture is missing benchmark IDs: " + ", ".join(missing))
    for benchmark_id, benchmark in requested.items():
        content_sha256 = bundle["records"][benchmark_id]["content_sha256"]
        actual_content_sha256 = verify_benchmark_content(
            benchmark, content_sha256
        )
        if actual_content_sha256 != content_sha256:
            raise ValueError(f"capture benchmark hash mismatch for {benchmark_id}")
    return bundle
