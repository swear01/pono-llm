#!/usr/bin/env python3
"""Strict schemas and canonical identities for certified invariant transport."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


MAP_SCHEMA = "pono-certified-transport-map-v1"
INVARIANT_SCHEMA = "pono-transport-invariant-v1"
POPULATION_SCHEMA = "pono-certified-transport-population-v1"
TRANSFORM_FAMILIES = {"rename", "affine-recode", "split-merge", "stutter"}
EXACT_TRANSFORM_FAMILIES = {"rename", "affine-recode", "split-merge"}
FROZEN_SEEDS = {11, 23, 47}
MIN_SAFE_BASES = 12
MIN_SOURCE_FAMILIES = 8
MIN_PER_PRIMARY_TRANSFORM = 8
MIN_INPUT_DRIVEN_T3_FAMILIES = 3
MIN_UNSAFE_CONTROLS = 4

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}")
_REF = re.compile(r"(?:state|input)\d+")
_STATE_REF = re.compile(r"state\d+")
_INPUT_REF = re.compile(r"input\d+")

_NARY_FORMS = {
    "add",
    "and",
    "concat",
    "mul",
    "or",
    "xor",
}
_BINARY_FORMS = {
    "bvand",
    "bvcomp",
    "bvor",
    "bvxor",
    "eq",
    "implies",
    "ne",
    "sdiv",
    "sge",
    "sgt",
    "sle",
    "sll",
    "slt",
    "sra",
    "srem",
    "srl",
    "udiv",
    "uge",
    "ugt",
    "ule",
    "ult",
    "urem",
}
_UNARY_FORMS = {"bvnot", "not"}


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: str | Path) -> object:
    try:
        return json.loads(
            Path(path).read_text(), object_pairs_hook=_reject_duplicate_pairs
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _strict_fields(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{location} fields mismatch: missing={missing}, unknown={unknown}"
        )
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.lower()):
        raise ValueError(f"{field} must be a 64-character SHA-256 digest")
    return value.lower()


def _relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must not be absolute or contain '..'")
    return path.as_posix()


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < 0 or (value == 0 and not allow_zero):
        relation = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be {relation}")
    return value


def normalize_ast(value: object, location: str = "AST") -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    form = value.get("form")
    if not isinstance(form, str) or not form:
        raise ValueError(f"{location}.form must be a non-empty string")

    if form == "ref":
        node = _strict_fields(value, {"form", "ref"}, location)
        ref = node["ref"]
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise ValueError(f"{location}.ref must be stateN or inputN")
        return {"form": "ref", "ref": ref}

    if form == "const":
        node = _strict_fields(value, {"form", "const", "width"}, location)
        width = _positive_int(node["width"], f"{location}.width", allow_zero=True)
        raw = node["const"]
        if not isinstance(raw, (str, int)) or isinstance(raw, bool):
            raise ValueError(f"{location}.const must be an integer literal")
        literal = str(raw)
        if width == 0:
            if literal not in {"true", "false", "0", "1"}:
                raise ValueError(f"{location} has an invalid Boolean constant")
            literal = "true" if literal in {"true", "1"} else "false"
        else:
            try:
                if literal.startswith("#b"):
                    int(literal[2:], 2)
                    if len(literal[2:]) != width:
                        raise ValueError(
                            f"{location} binary literal width does not match {width}"
                        )
                elif literal.startswith("#x"):
                    int(literal[2:], 16)
                    if 4 * len(literal[2:]) != width:
                        raise ValueError(
                            f"{location} hexadecimal literal width does not match {width}"
                        )
                else:
                    int(literal, 10)
            except ValueError as exc:
                raise ValueError(f"{location} has an invalid BV constant") from exc
        return {"form": "const", "const": literal, "width": width}

    if form == "extract":
        node = _strict_fields(value, {"form", "args", "hi", "lo"}, location)
        args = _normalize_args(node["args"], location)
        if len(args) != 1:
            raise ValueError(f"{location} extract requires one argument")
        hi = _positive_int(node["hi"], f"{location}.hi", allow_zero=True)
        lo = _positive_int(node["lo"], f"{location}.lo", allow_zero=True)
        if hi < lo:
            raise ValueError(f"{location} extract requires hi >= lo")
        return {"form": form, "args": args, "hi": hi, "lo": lo}

    if form in {"uext", "sext"}:
        node = _strict_fields(value, {"form", "args", "width"}, location)
        args = _normalize_args(node["args"], location)
        if len(args) != 1:
            raise ValueError(f"{location} {form} requires one argument")
        width = _positive_int(node["width"], f"{location}.width")
        return {"form": form, "args": args, "width": width}

    if form == "ite":
        node = _strict_fields(value, {"form", "args"}, location)
        args = _normalize_args(node["args"], location)
        if len(args) != 3:
            raise ValueError(f"{location} ite requires three arguments")
        return {"form": form, "args": args}

    if form == "sub":
        node = _strict_fields(value, {"form", "args"}, location)
        args = _normalize_args(node["args"], location)
        if not args:
            raise ValueError(f"{location} sub requires at least one argument")
        return {"form": form, "args": args}

    if form in _NARY_FORMS:
        node = _strict_fields(value, {"form", "args"}, location)
        args = _normalize_args(node["args"], location)
        minimum = 2 if form == "concat" else 1
        if len(args) < minimum:
            raise ValueError(
                f"{location} {form} requires at least {minimum} argument(s)"
            )
        return {"form": form, "args": args}

    if form in _BINARY_FORMS:
        node = _strict_fields(value, {"form", "args"}, location)
        args = _normalize_args(node["args"], location)
        if len(args) != 2:
            raise ValueError(f"{location} {form} requires two arguments")
        return {"form": form, "args": args}

    if form in _UNARY_FORMS:
        node = _strict_fields(value, {"form", "args"}, location)
        args = _normalize_args(node["args"], location)
        if len(args) != 1:
            raise ValueError(f"{location} {form} requires one argument")
        return {"form": form, "args": args}

    raise ValueError(f"{location} uses unsupported form: {form}")


def _normalize_args(value: object, location: str) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError(f"{location}.args must be a list")
    return [normalize_ast(arg, f"{location}.args[{index}]") for index, arg in enumerate(value)]


def normalize_invariant_document(value: object) -> dict:
    document = _strict_fields(
        value, {"schema", "source", "predicates", "origin"}, "invariant document"
    )
    if document["schema"] != INVARIANT_SCHEMA:
        raise ValueError(f"unsupported invariant schema: {document['schema']!r}")
    source = _strict_fields(
        document["source"], {"benchmark_id", "sha256"}, "invariant source"
    )
    predicates = document["predicates"]
    if not isinstance(predicates, list) or not predicates:
        raise ValueError("invariant predicates must be a non-empty list")
    origin = _strict_fields(
        document["origin"], {"kind", "artifacts"}, "invariant origin"
    )
    if origin["kind"] not in {
        "frozen-candidate-houdini",
        "phase-grammar-houdini",
        "pono-returned-invariant",
    }:
        raise ValueError(f"unsupported invariant origin kind: {origin['kind']!r}")
    artifacts = origin["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("invariant origin artifacts must be a non-empty list")
    normalized_artifacts = []
    seen_paths = set()
    for index, artifact in enumerate(artifacts):
        row = _strict_fields(
            artifact, {"path", "sha256"}, f"invariant origin artifact {index}"
        )
        path = _relative_path(row["path"], f"origin artifact {index}.path")
        if path in seen_paths:
            raise ValueError(f"duplicate invariant origin artifact: {path}")
        seen_paths.add(path)
        normalized_artifacts.append({
            "path": path,
            "sha256": _sha256(row["sha256"], f"origin artifact {index}.sha256"),
        })
    normalized_artifacts.sort(key=lambda row: row["path"])
    return {
        "schema": INVARIANT_SCHEMA,
        "source": {
            "benchmark_id": _relative_path(
                source["benchmark_id"], "invariant source benchmark_id"
            ),
            "sha256": _sha256(source["sha256"], "invariant source sha256"),
        },
        "predicates": [
            normalize_ast(ast, f"invariant predicate {index}")
            for index, ast in enumerate(predicates)
        ],
        "origin": {
            "kind": origin["kind"],
            "artifacts": normalized_artifacts,
        },
    }


def _normalize_identity(value: object, location: str) -> dict:
    row = _strict_fields(value, {"benchmark_id", "sha256"}, location)
    return {
        "benchmark_id": _relative_path(row["benchmark_id"], f"{location}.benchmark_id"),
        "sha256": _sha256(row["sha256"], f"{location}.sha256"),
    }


def _normalize_ast_map(
    value: object, location: str, key_pattern: re.Pattern[str]
) -> dict[str, dict]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    normalized = {}
    def sort_key(item: object) -> int:
        if isinstance(item, str) and _REF.fullmatch(item):
            return int(item.removeprefix("state").removeprefix("input"))
        return -1

    for key in sorted(value, key=sort_key):
        if not isinstance(key, str) or not key_pattern.fullmatch(key):
            raise ValueError(f"{location} has invalid key: {key!r}")
        normalized[key] = normalize_ast(value[key], f"{location}.{key}")
    return normalized


def normalize_map_document(value: object) -> dict:
    document = _strict_fields(
        value,
        {
            "schema",
            "source",
            "target",
            "transformation",
            "projection",
            "input_map",
            "inverse_embedding",
            "observation_predicate",
            "property_map",
            "generated_map_invariants",
            "source_certificate_sha256",
            "generator_commit",
            "validator_version_sha256",
        },
        "transport map",
    )
    if document["schema"] != MAP_SCHEMA:
        raise ValueError(f"unsupported transport map schema: {document['schema']!r}")
    transformation = _strict_fields(
        document["transformation"],
        {"family", "version", "seed", "parameters", "parameters_sha256"},
        "transport transformation",
    )
    family = transformation["family"]
    if family not in TRANSFORM_FAMILIES:
        raise ValueError(f"unsupported transformation family: {family!r}")
    if transformation["version"] != 1:
        raise ValueError("transport transformation version must be 1")
    seed = _positive_int(transformation["seed"], "transport transformation seed")
    if seed not in FROZEN_SEEDS:
        raise ValueError(f"transport transformation seed is not frozen: {seed}")
    parameters = transformation["parameters"]
    if not isinstance(parameters, dict):
        raise ValueError("transport transformation parameters must be an object")
    parameters_hash = _sha256(
        transformation["parameters_sha256"], "transport parameters_sha256"
    )
    if canonical_sha256(parameters) != parameters_hash:
        raise ValueError("transport transformation parameters hash mismatch")

    projection = _normalize_ast_map(
        document["projection"], "transport projection", _STATE_REF
    )
    if not projection:
        raise ValueError("transport projection must not be empty")
    input_map = _normalize_ast_map(
        document["input_map"], "transport input_map", _INPUT_REF
    )
    inverse = _normalize_ast_map(
        document["inverse_embedding"], "transport inverse_embedding", _STATE_REF
    )
    observation = document["observation_predicate"]
    if observation is not None:
        observation = normalize_ast(observation, "transport observation_predicate")
    if family in EXACT_TRANSFORM_FAMILIES:
        if not inverse:
            raise ValueError(f"{family} requires a non-empty inverse_embedding")
        if observation is not None:
            raise ValueError(f"{family} requires a null observation_predicate")
    else:
        if inverse:
            raise ValueError("stutter requires an empty inverse_embedding")
        if observation is None:
            raise ValueError("stutter requires an observation_predicate")

    property_map = document["property_map"]
    if not isinstance(property_map, list) or not property_map:
        raise ValueError("transport property_map must be a non-empty list")
    normalized_properties = []
    seen_source = set()
    seen_target = set()
    for index, item in enumerate(property_map):
        row = _strict_fields(
            item,
            {"source_bad_index", "target_bad_index"},
            f"transport property_map {index}",
        )
        source_index = _positive_int(
            row["source_bad_index"],
            f"transport property_map {index}.source_bad_index",
            allow_zero=True,
        )
        target_index = _positive_int(
            row["target_bad_index"],
            f"transport property_map {index}.target_bad_index",
            allow_zero=True,
        )
        if source_index in seen_source or target_index in seen_target:
            raise ValueError("transport property_map indices must be one-to-one")
        seen_source.add(source_index)
        seen_target.add(target_index)
        normalized_properties.append({
            "source_bad_index": source_index,
            "target_bad_index": target_index,
        })
    normalized_properties.sort(key=lambda row: row["source_bad_index"])

    if document["generated_map_invariants"] != []:
        raise ValueError("generated_map_invariants must be present and empty in v1")
    revision = document["generator_commit"]
    if not isinstance(revision, str) or not _GIT_REVISION.fullmatch(revision.lower()):
        raise ValueError("generator_commit must be a 40-character Git revision")
    return {
        "schema": MAP_SCHEMA,
        "source": _normalize_identity(document["source"], "transport source"),
        "target": _normalize_identity(document["target"], "transport target"),
        "transformation": {
            "family": family,
            "version": 1,
            "seed": seed,
            "parameters": parameters,
            "parameters_sha256": parameters_hash,
        },
        "projection": projection,
        "input_map": input_map,
        "inverse_embedding": inverse,
        "observation_predicate": observation,
        "property_map": normalized_properties,
        "generated_map_invariants": [],
        "source_certificate_sha256": _sha256(
            document["source_certificate_sha256"], "source_certificate_sha256"
        ),
        "generator_commit": revision.lower(),
        "validator_version_sha256": _sha256(
            document["validator_version_sha256"], "validator_version_sha256"
        ),
    }


def validate_population_document(value: object) -> dict:
    document = _strict_fields(
        value,
        {
            "schema",
            "decision",
            "failed_conditions",
            "conditions",
            "counts",
            "provenance",
            "safe_bases",
            "unsafe_controls",
            "exclusions",
            "population_sha256",
        },
        "transport population",
    )
    if document["schema"] != POPULATION_SCHEMA:
        raise ValueError(f"unsupported population schema: {document['schema']!r}")
    declared_hash = _sha256(
        document["population_sha256"], "transport population_sha256"
    )
    payload = {
        key: item for key, item in document.items() if key != "population_sha256"
    }
    if canonical_sha256(payload) != declared_hash:
        raise ValueError("transport population self-hash mismatch")

    conditions = document["conditions"]
    if not isinstance(conditions, dict) or not conditions:
        raise ValueError("transport population conditions must be a non-empty object")
    failed = []
    for name, raw in conditions.items():
        if not isinstance(name, str) or not name:
            raise ValueError("transport population condition names must be non-empty")
        if not isinstance(raw, dict):
            raise ValueError(f"transport population condition {name} must be an object")
        allowed = {"actual", "required", "pass", "implementation_note"}
        if set(raw) - allowed or not {"actual", "required", "pass"}.issubset(raw):
            raise ValueError(f"transport population condition {name} fields mismatch")
        _positive_int(raw["actual"], f"condition {name}.actual", allow_zero=True)
        _positive_int(raw["required"], f"condition {name}.required", allow_zero=True)
        if not isinstance(raw["pass"], bool):
            raise ValueError(f"condition {name}.pass must be Boolean")
        if "implementation_note" in raw and (
            not isinstance(raw["implementation_note"], str)
            or not raw["implementation_note"]
        ):
            raise ValueError(f"condition {name}.implementation_note is invalid")
        if not raw["pass"]:
            failed.append(name)
    if document["failed_conditions"] != sorted(failed):
        raise ValueError("transport population failed_conditions mismatch")
    expected_decision = "population-insufficient" if failed else "population-sufficient"
    if document["decision"] != expected_decision:
        raise ValueError("transport population decision mismatch")

    safe_bases = document["safe_bases"]
    if not isinstance(safe_bases, list):
        raise ValueError("transport population safe_bases must be a list")
    benchmark_ids = set()
    family_ids = set()
    certificate_paths = set()
    origins = set()
    class_counts: dict[str, int] = {}
    applicability_counts = {family: 0 for family in ("T1", "T2", "T3")}
    input_driven_t3_families = set()
    for index, raw in enumerate(safe_bases):
        row = _strict_fields(
            raw,
            {
                "benchmark_id",
                "benchmark_sha256",
                "source_family_key",
                "source_family_id",
                "source_certificate_path",
                "source_certificate_file_sha256",
                "source_certificate_sha256",
                "source_certificate_origin",
                "prior_evidence",
                "predicate_count",
                "ast_node_count",
                "invariant_classes",
                "certificate",
                "applicability",
            },
            f"transport safe base {index}",
        )
        benchmark_id = _relative_path(
            row["benchmark_id"], f"transport safe base {index}.benchmark_id"
        )
        if benchmark_id in benchmark_ids:
            raise ValueError(f"duplicate transport safe benchmark: {benchmark_id}")
        benchmark_ids.add(benchmark_id)
        family_id = _sha256(
            row["source_family_id"], f"transport safe base {index}.source_family_id"
        )
        if family_id in family_ids:
            raise ValueError(f"duplicate transport source family: {family_id}")
        family_ids.add(family_id)
        if not isinstance(row["source_family_key"], str) or not row["source_family_key"]:
            raise ValueError(f"transport safe base {index} has invalid source_family_key")
        _sha256(row["benchmark_sha256"], f"transport safe base {index}.benchmark_sha256")
        path = _relative_path(
            row["source_certificate_path"],
            f"transport safe base {index}.source_certificate_path",
        )
        if path in certificate_paths:
            raise ValueError(f"duplicate source certificate path: {path}")
        certificate_paths.add(path)
        _sha256(
            row["source_certificate_file_sha256"],
            f"transport safe base {index}.source_certificate_file_sha256",
        )
        _sha256(
            row["source_certificate_sha256"],
            f"transport safe base {index}.source_certificate_sha256",
        )
        if row["source_certificate_origin"] not in {
            "frozen-candidate-houdini",
            "phase-grammar-houdini",
            "pono-returned-invariant",
        }:
            raise ValueError(f"transport safe base {index} has invalid origin")
        origins.add(row["source_certificate_origin"])
        if not isinstance(row["prior_evidence"], str) or not row["prior_evidence"]:
            raise ValueError(f"transport safe base {index} has invalid prior_evidence")
        predicate_count = _positive_int(
            row["predicate_count"], f"transport safe base {index}.predicate_count"
        )
        ast_node_count = _positive_int(
            row["ast_node_count"], f"transport safe base {index}.ast_node_count"
        )
        classes = row["invariant_classes"]
        if not isinstance(classes, list) or len(classes) != len(set(classes)):
            raise ValueError(f"transport safe base {index} has invalid invariant_classes")
        for label in classes:
            if label not in {
                "affine-relational",
                "quadratic-polynomial",
                "phase-guarded",
                "conjunctive",
            }:
                raise ValueError(f"transport safe base {index} has unknown class: {label}")
            class_counts[label] = class_counts.get(label, 0) + 1

        certificate = _strict_fields(
            row["certificate"],
            {"ok", "checks", "bad_count", "predicate_count", "ast_node_count"},
            f"transport safe base {index}.certificate",
        )
        if certificate["ok"] is not True:
            raise ValueError(f"transport safe base {index} is not certified")
        if certificate["predicate_count"] != predicate_count:
            raise ValueError(f"transport safe base {index} predicate count mismatch")
        if certificate["ast_node_count"] != ast_node_count:
            raise ValueError(f"transport safe base {index} AST node count mismatch")
        bad_count = _positive_int(
            certificate["bad_count"], f"transport safe base {index}.bad_count"
        )
        checks = certificate["checks"]
        if not isinstance(checks, list) or len(checks) != bad_count + 2:
            raise ValueError(f"transport safe base {index} check count mismatch")
        expected_check_names = ["C1 Init=>H", "C2 inductive"] + [
            f"C3[{bad_index}] H=>notBAD" for bad_index in range(bad_count)
        ]
        for check_index, raw_check in enumerate(checks):
            check = _strict_fields(
                raw_check,
                {"name", "result", "time_sec", "unknown_reason"},
                f"transport safe base {index}.check {check_index}",
            )
            if not isinstance(check["name"], str) or not check["name"]:
                raise ValueError(f"transport safe base {index} has unnamed check")
            if check["name"] != expected_check_names[check_index]:
                raise ValueError(f"transport safe base {index} check order mismatch")
            if check["result"] != "unsat" or check["unknown_reason"] != "":
                raise ValueError(f"transport safe base {index} has non-proof check")
            if (
                isinstance(check["time_sec"], bool)
                or not isinstance(check["time_sec"], (int, float))
                or not math.isfinite(check["time_sec"])
                or check["time_sec"] < 0
            ):
                raise ValueError(f"transport safe base {index} has invalid check time")

        applicability = _strict_fields(
            row["applicability"],
            {"T1", "T2", "T3"},
            f"transport safe base {index}.applicability",
        )
        family_fields = {
            "T1": {"applicable", "reason", "candidate_groups"},
            "T2": {"applicable", "reason", "candidate_state_refs"},
            "T3": {
                "applicable",
                "reason",
                "state_update_count",
                "input_driven",
                "input_driven_state_refs",
            },
        }
        for family, fields in family_fields.items():
            detail = _strict_fields(
                applicability[family], fields,
                f"transport safe base {index}.applicability.{family}",
            )
            if not isinstance(detail["applicable"], bool):
                raise ValueError(f"transport safe base {index} {family} flag is invalid")
            if not isinstance(detail["reason"], str):
                raise ValueError(f"transport safe base {index} {family} reason is invalid")
            if detail["applicable"] != (detail["reason"] == ""):
                raise ValueError(
                    f"transport safe base {index} {family} reason/flag mismatch"
                )
            applicability_counts[family] += int(detail["applicable"])
        t1_groups = applicability["T1"]["candidate_groups"]
        if not isinstance(t1_groups, list) or bool(t1_groups) != applicability["T1"]["applicable"]:
            raise ValueError(f"transport safe base {index} T1 groups mismatch")
        for group_index, group in enumerate(t1_groups):
            group = _strict_fields(
                group,
                {"width", "state_refs"},
                f"transport safe base {index}.T1 group {group_index}",
            )
            _positive_int(group["width"], f"transport safe base {index}.T1 width")
            refs = group["state_refs"]
            if (
                not isinstance(refs, list)
                or not 2 <= len(refs) <= 3
                or len(refs) != len(set(refs))
                or any(not isinstance(ref, str) or not _STATE_REF.fullmatch(ref) for ref in refs)
            ):
                raise ValueError(f"transport safe base {index} T1 refs are invalid")
        t2_refs = applicability["T2"]["candidate_state_refs"]
        if (
            not isinstance(t2_refs, list)
            or bool(t2_refs) != applicability["T2"]["applicable"]
            or len(t2_refs) != len(set(t2_refs))
            or any(
                not isinstance(ref, str) or not _STATE_REF.fullmatch(ref)
                for ref in t2_refs
            )
        ):
            raise ValueError(f"transport safe base {index} T2 refs are invalid")
        update_count = _positive_int(
            applicability["T3"]["state_update_count"],
            f"transport safe base {index}.T3 state_update_count",
            allow_zero=True,
        )
        if applicability["T3"]["applicable"] != (update_count >= 2):
            raise ValueError(f"transport safe base {index} T3 update count mismatch")
        if not isinstance(applicability["T3"]["input_driven"], bool):
            raise ValueError(f"transport safe base {index} T3 input flag is invalid")
        input_refs = applicability["T3"]["input_driven_state_refs"]
        if (
            not isinstance(input_refs, list)
            or bool(input_refs) != applicability["T3"]["input_driven"]
            or len(input_refs) != len(set(input_refs))
            or any(
                not isinstance(ref, str) or not _STATE_REF.fullmatch(ref)
                for ref in input_refs
            )
        ):
            raise ValueError(f"transport safe base {index} T3 input refs are invalid")
        if applicability["T3"]["applicable"] and applicability["T3"]["input_driven"]:
            input_driven_t3_families.add(family_id)

    unsafe_controls = document["unsafe_controls"]
    if not isinstance(unsafe_controls, list):
        raise ValueError("transport population unsafe_controls must be a list")
    unsafe_families = set()
    for index, raw in enumerate(unsafe_controls):
        row = _strict_fields(
            raw,
            {"benchmark_id", "benchmark_sha256", "source_family_id"},
            f"transport unsafe control {index}",
        )
        _relative_path(row["benchmark_id"], f"transport unsafe control {index}.benchmark_id")
        _sha256(row["benchmark_sha256"], f"transport unsafe control {index}.benchmark_sha256")
        family_id = _sha256(
            row["source_family_id"], f"transport unsafe control {index}.source_family_id"
        )
        if family_id in unsafe_families:
            raise ValueError(f"duplicate transport unsafe family: {family_id}")
        unsafe_families.add(family_id)

    counts = _strict_fields(
        document["counts"],
        {
            "discovered_record_count",
            "eligible_before_dedup_count",
            "safe_base_count",
            "source_family_count",
            "source_origin_counts",
            "invariant_class_counts",
            "applicability_counts",
            "T3_input_driven_source_family_count",
            "unsafe_control_count",
            "exclusion_reason_counts",
        },
        "transport population counts",
    )
    expected_counts = {
        "safe_base_count": len(safe_bases),
        "source_family_count": len(family_ids),
        "source_origin_counts": {
            key: sum(row["source_certificate_origin"] == key for row in safe_bases)
            for key in sorted(origins)
        },
        "invariant_class_counts": dict(sorted(class_counts.items())),
        "applicability_counts": applicability_counts,
        "T3_input_driven_source_family_count": len(input_driven_t3_families),
        "unsafe_control_count": len(unsafe_controls),
    }
    for key, expected in expected_counts.items():
        if counts[key] != expected:
            raise ValueError(f"transport population count mismatch: {key}")
    for key in ("discovered_record_count", "eligible_before_dedup_count"):
        _positive_int(counts[key], f"transport population counts.{key}", allow_zero=True)
    if not (
        counts["discovered_record_count"]
        >= counts["eligible_before_dedup_count"]
        >= counts["safe_base_count"]
    ):
        raise ValueError("transport population discovery counts are inconsistent")

    expected_condition_values = {
        "safe_base_count": (len(safe_bases), MIN_SAFE_BASES),
        "source_family_count": (len(family_ids), MIN_SOURCE_FAMILIES),
        "affine_relational_class": (class_counts.get("affine-relational", 0), 1),
        "quadratic_polynomial_class": (
            class_counts.get("quadratic-polynomial", 0), 1
        ),
        "phase_guarded_or_genuinely_conjunctive_class": (
            class_counts.get("phase-guarded", 0), 1
        ),
        "T1_applicable_base_count": (
            applicability_counts["T1"], MIN_PER_PRIMARY_TRANSFORM
        ),
        "T2_applicable_base_count": (
            applicability_counts["T2"], MIN_PER_PRIMARY_TRANSFORM
        ),
        "T3_applicable_base_count": (
            applicability_counts["T3"], MIN_PER_PRIMARY_TRANSFORM
        ),
        "T3_input_driven_source_family_count": (
            len(input_driven_t3_families), MIN_INPUT_DRIVEN_T3_FAMILIES
        ),
        "unsafe_control_count": (len(unsafe_controls), MIN_UNSAFE_CONTROLS),
    }
    if set(conditions) != set(expected_condition_values):
        raise ValueError("transport population condition set mismatch")
    for name, (actual, required) in expected_condition_values.items():
        if (
            conditions[name]["actual"] != actual
            or conditions[name]["required"] != required
            or conditions[name]["pass"] != (actual >= required)
        ):
            raise ValueError(f"transport population condition mismatch: {name}")

    provenance = _strict_fields(
        document["provenance"],
        {
            "generator_commit",
            "pono_sha256",
            "phase1_summary_path",
            "phase1_summary_sha256",
            "representation_summary_path",
            "representation_summary_sha256",
            "representation_population_path",
            "representation_population_sha256",
            "representation_integrity_path",
            "representation_integrity_sha256",
            "pilot_path",
            "pilot_sha256",
            "source_certificate_timeout_ms",
            "show_invar_timeout_sec",
            "max_normalized_ast_nodes",
            "max_invariant_output_bytes",
            "invariant_normalization_timeout_sec",
            "llm_api_calls",
        },
        "transport population provenance",
    )
    if not isinstance(provenance["generator_commit"], str) or not _GIT_REVISION.fullmatch(
        provenance["generator_commit"].lower()
    ):
        raise ValueError("transport population generator_commit is invalid")
    for key in (
        "pono_sha256",
        "phase1_summary_sha256",
        "representation_summary_sha256",
        "representation_population_sha256",
        "representation_integrity_sha256",
        "pilot_sha256",
    ):
        _sha256(provenance[key], f"transport population provenance.{key}")
    for key in (
        "phase1_summary_path",
        "representation_summary_path",
        "representation_population_path",
        "representation_integrity_path",
        "pilot_path",
    ):
        _relative_path(provenance[key], f"transport population provenance.{key}")
    _positive_int(
        provenance["source_certificate_timeout_ms"],
        "transport population provenance.source_certificate_timeout_ms",
    )
    _positive_int(
        provenance["max_normalized_ast_nodes"],
        "transport population provenance.max_normalized_ast_nodes",
    )
    _positive_int(
        provenance["max_invariant_output_bytes"],
        "transport population provenance.max_invariant_output_bytes",
    )
    for key in ("show_invar_timeout_sec", "invariant_normalization_timeout_sec"):
        if (
            isinstance(provenance[key], bool)
            or not isinstance(provenance[key], (int, float))
            or not math.isfinite(provenance[key])
            or provenance[key] <= 0
        ):
            raise ValueError(f"transport population {key} is invalid")
    if provenance["llm_api_calls"] != 0:
        raise ValueError("Gate 5A0 population must record zero LLM/API calls")

    if not isinstance(document["exclusions"], list):
        raise ValueError("transport population exclusions must be a list")
    exclusion_counts: dict[str, int] = {}
    for index, row in enumerate(document["exclusions"]):
        if not isinstance(row, dict):
            raise ValueError(f"transport population exclusion {index} must be an object")
        reason = row.get("exclusion_reason")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"transport population exclusion {index} has no reason")
        exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
    if counts["exclusion_reason_counts"] != dict(sorted(exclusion_counts.items())):
        raise ValueError("transport population exclusion counts mismatch")
    return document
