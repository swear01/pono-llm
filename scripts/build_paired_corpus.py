#!/usr/bin/env python3
"""Build the pinned SV-COMP 2025 source/BTOR2 paired population."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import parse_btor2  # noqa: E402
from experiment_manifest import file_sha256  # noqa: E402
from grammar_routes import extract_functional_phases  # noqa: E402
from invariant_arith import get_software_vars  # noqa: E402


POPULATION_SCHEMA = "pono-llm-paired-population-v1"
TRANSLATION_REVISION = "d9838013ea48568a21a106a7fc94f11c13ac5ad6"
SOURCE_REVISION = "1e5856db49f3a4766f416cc60382aa92012b2939"
CPV_REVISION = "2b20529bf4cd49922a14e0514631a148ce69236f"
TRANSLATION_SUBDIR = Path("translated/safety-func")
SOURCE_SUBDIR = Path("c")
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_INPUT_FILES = re.compile(
    r"^input_files:[ \t]*(.*?)[ \t]*$", re.MULTILINE
)
_EXPECTED_VERDICT = re.compile(
    r"^[ \t]*(?:-[ \t]*)?expected_verdict:[ \t]*(true|false)[ \t]*$",
    re.MULTILINE,
)
_PROPERTY_FILE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?property_file:[ \t]*(.*?)[ \t]*$", re.MULTILINE
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_repository(repo: Path, expected_revision: str, label: str) -> dict:
    if not repo.is_dir():
        raise ValueError(f"{label} repository does not exist: {repo}")
    revision = git_output(repo, "rev-parse", "HEAD")
    if revision != expected_revision:
        raise ValueError(
            f"{label} revision mismatch: expected {expected_revision}, got {revision}"
        )
    tracked_status = git_output(repo, "status", "--short", "--untracked-files=no")
    if tracked_status:
        raise ValueError(f"{label} repository has tracked changes:\n{tracked_status}")
    return {
        "revision": revision,
        "remote": git_output(repo, "remote", "get-url", "origin"),
    }


def verify_translation_pins(translation_repo: Path) -> dict:
    row = git_output(translation_repo, "ls-tree", "HEAD", "cpv", "sv-benchmarks")
    pins = {}
    for line in row.splitlines():
        fields = line.split()
        if len(fields) != 4 or fields[0] != "160000" or fields[1] != "commit":
            raise ValueError(f"unexpected translation submodule row: {line}")
        pins[fields[3]] = fields[2]
    expected = {"cpv": CPV_REVISION, "sv-benchmarks": SOURCE_REVISION}
    if pins != expected:
        raise ValueError(
            f"translation submodule pins mismatch: expected {expected}, got {pins}"
        )
    return pins


def parse_single_input_file(yaml_path: Path) -> str:
    text = yaml_path.read_text()
    matches = _INPUT_FILES.findall(text)
    if len(matches) != 1 or not matches[0]:
        raise ValueError(f"{yaml_path} must have one inline input_files scalar")
    try:
        values = shlex.split(matches[0])
    except ValueError as exc:
        raise ValueError(f"invalid input_files scalar in {yaml_path}: {exc}") from exc
    if len(values) != 1:
        raise ValueError(f"{yaml_path} must name exactly one input file")
    value = values[0]
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe input_files path in {yaml_path}: {value}")
    return path.as_posix()


def parse_translated_property(yaml_path: Path) -> tuple[bool, int]:
    text = yaml_path.read_text()
    properties = [shlex.split(value)[0] for value in _PROPERTY_FILE.findall(text)]
    verdicts = _EXPECTED_VERDICT.findall(text)
    if len(properties) != 1 or len(verdicts) != 1:
        raise ValueError(
            f"{yaml_path} must contain exactly one property and expected verdict"
        )
    if Path(properties[0]).name != "unreach-call.prp":
        raise ValueError(f"{yaml_path} is not an unreach-call task")
    return verdicts[0] == "true", len(properties)


def source_family(category: str, source_yaml: Path) -> tuple[str, str, list[str]]:
    stem = source_yaml.stem
    rules = []
    reduced = re.sub(r"\.i\.[pv]\+[^/]+-reducer$", "", stem)
    if reduced != stem:
        stem = reduced
        rules.append("reducer-variant")
    reduced = re.sub(r"_abstracted$", "", stem)
    if reduced != stem:
        stem = reduced
        rules.append("abstracted-variant")
    reduced = re.sub(r"_(?:unwind|value)bound\d+$", "", stem)
    if reduced != stem:
        stem = reduced
        rules.append("bound-variant")
    if category == "nla-digbench":
        reduced = re.sub(r"-(?:ll\d*|u)$", "", stem)
        if reduced != stem:
            stem = reduced
            rules.append("nla-verdict-variant")
    family_key = f"{category}/{stem}"
    return family_key, canonical_sha256({"source_family": family_key}), rules


def source_state_mapping(info, source_text: str) -> tuple[list[dict], list[str], int]:
    identifiers = set(_IDENTIFIER.findall(source_text))
    by_name = defaultdict(list)
    for state in get_software_vars(info):
        if state.width > 0 and state.symbol:
            by_name[state.symbol].append(state)
    ambiguous = sorted(name for name, states in by_name.items() if len(states) > 1)
    unique_states = [
        states[0]
        for name, states in sorted(by_name.items())
        if len(states) == 1 and name in identifiers
    ]
    mapping = [
        {
            "source_name": state.symbol,
            "state_ref": state.ref,
            "width": state.width,
            "init": state.init_value,
        }
        for state in unique_states
    ]
    return mapping, ambiguous, len(by_name)


def has_arrays(info) -> bool:
    return bool(
        info.array_sort_count
        or any(state.is_array for state in info.states)
        or any(op in {"read", "write"} for op in info.ops.values())
    )


def build_task_record(
    btor2_path: Path,
    translation_root: Path,
    source_root: Path,
) -> dict:
    relative = btor2_path.relative_to(translation_root)
    benchmark_id = relative.as_posix()
    translated_yaml = btor2_path.with_suffix(".yml")
    if not translated_yaml.is_file():
        raise ValueError(f"missing translated YAML for {benchmark_id}")
    declared_btor = parse_single_input_file(translated_yaml)
    if declared_btor != btor2_path.name:
        raise ValueError(
            f"translated YAML input mismatch for {benchmark_id}: {declared_btor}"
        )
    expected_safe, property_count = parse_translated_property(translated_yaml)

    source_yaml = source_root / relative.with_suffix(".yml")
    if not source_yaml.is_file():
        raise ValueError(f"missing source YAML for {benchmark_id}: {source_yaml}")
    source_input = parse_single_input_file(source_yaml)
    source_path = source_yaml.parent / source_input
    if not source_path.is_file():
        raise ValueError(f"missing source input for {benchmark_id}: {source_path}")

    info = parse_btor2(str(btor2_path))
    source_text = source_path.read_text(errors="strict")
    mapping, ambiguous, clean_state_count = source_state_mapping(info, source_text)
    category = relative.parts[0]
    family_key, family_id, family_rules = source_family(category, source_yaml)

    reasons = []
    array_present = has_arrays(info)
    if array_present:
        reasons.append("array-theory")
    if info.bad_count != 1:
        reasons.append(f"bad-count-{info.bad_count}")
    phases = []
    phase_error = ""
    if not array_present and info.bad_count == 1:
        try:
            phases = [
                phase.canonical_payload()
                for phase in extract_functional_phases(str(btor2_path))
            ]
        except ValueError as exc:
            phase_error = str(exc)
            reasons.append("functional-phase-extraction")
    else:
        phase_error = "not attempted because scalar single-BAD prerequisites failed"
    if len(mapping) < 2:
        reasons.append("fewer-than-two-unique-source-mapped-states")

    source_relative = source_path.relative_to(source_root.parent)
    source_yaml_relative = source_yaml.relative_to(source_root.parent)
    translated_relative = translated_yaml.relative_to(translation_root.parent.parent)
    btor_relative = btor2_path.relative_to(translation_root.parent.parent)
    mapping_ratio = len(mapping) / clean_state_count if clean_state_count else 0.0
    return {
        "benchmark_id": benchmark_id,
        "category": category,
        "expected_verdict": "safe" if expected_safe else "unsafe",
        "property_count": property_count,
        "btor2_path": btor_relative.as_posix(),
        "btor2_sha256": file_sha256(btor2_path),
        "translation_yaml_path": translated_relative.as_posix(),
        "translation_yaml_sha256": file_sha256(translated_yaml),
        "source_path": source_relative.as_posix(),
        "source_sha256": file_sha256(source_path),
        "source_yaml_path": source_yaml_relative.as_posix(),
        "source_yaml_sha256": file_sha256(source_yaml),
        "source_input_kind": source_path.suffix.lstrip("."),
        "source_family_key": family_key,
        "source_family_id": family_id,
        "source_family_normalization": family_rules,
        "state_count": len(info.states),
        "scalar_state_count": sum(not state.is_array for state in info.states),
        "input_count": len(info.inputs),
        "node_count": info.node_count,
        "has_array": array_present,
        "bad_count": info.bad_count,
        "constraint_count": info.constraint_count,
        "clean_state_name_count": clean_state_count,
        "source_mapped_state_count": len(mapping),
        "source_mapping_ratio": f"{mapping_ratio:.6f}",
        "ambiguous_state_symbols": ambiguous,
        "source_state_mapping": mapping,
        "phase_extraction_error": phase_error,
        "phases": phases,
        "eligible": not reasons,
        "exclusion_reasons": reasons,
    }


def build_population(translation_repo: Path, source_repo: Path) -> dict:
    translation_meta = verify_repository(
        translation_repo, TRANSLATION_REVISION, "translation"
    )
    source_meta = verify_repository(source_repo, SOURCE_REVISION, "source")
    submodules = verify_translation_pins(translation_repo)
    translation_root = translation_repo / TRANSLATION_SUBDIR
    source_root = source_repo / SOURCE_SUBDIR
    if not translation_root.is_dir() or not source_root.is_dir():
        raise ValueError("pinned translation/source population directories are missing")

    btor_paths = sorted(translation_root.rglob("*.btor2"))
    if not btor_paths:
        raise ValueError(f"no BTOR2 tasks under {translation_root}")
    tasks = [
        build_task_record(path, translation_root, source_root)
        for path in btor_paths
    ]
    btor_groups = defaultdict(list)
    family_groups = defaultdict(list)
    for task in tasks:
        btor_groups[task["btor2_sha256"]].append(task["benchmark_id"])
        family_groups[task["source_family_id"]].append(task["benchmark_id"])
    duplicate_groups = {
        digest: sorted(ids)
        for digest, ids in sorted(btor_groups.items())
        if len(ids) > 1
    }
    exclusion_counts = Counter(
        reason for task in tasks for reason in task["exclusion_reasons"]
    )
    verdict_counts = Counter(task["expected_verdict"] for task in tasks)
    eligible_verdicts = Counter(
        task["expected_verdict"] for task in tasks if task["eligible"]
    )
    population = {
        "schema": POPULATION_SCHEMA,
        "provenance": {
            "translation_repository": translation_meta["remote"],
            "translation_revision": translation_meta["revision"],
            "source_repository": source_meta["remote"],
            "source_revision": source_meta["revision"],
            "cpv_revision": submodules["cpv"],
            "translation_subdir": TRANSLATION_SUBDIR.as_posix(),
            "source_subdir": SOURCE_SUBDIR.as_posix(),
        },
        "selection_status": "population-only; no LLM result used",
        "task_count": len(tasks),
        "eligible_count": sum(task["eligible"] for task in tasks),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "eligible_verdict_counts": dict(sorted(eligible_verdicts.items())),
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "exact_btor_duplicate_groups": duplicate_groups,
        "source_family_count": len(family_groups),
        "source_family_groups": {
            family_id: sorted(ids)
            for family_id, ids in sorted(family_groups.items())
            if len(ids) > 1
        },
        "tasks": tasks,
    }
    population["population_sha256"] = canonical_sha256({
        key: value
        for key, value in population.items()
        if key != "population_sha256"
    })
    return population


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("translation_repo")
    parser.add_argument("source_repo")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    output = Path(args.out)
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise FileExistsError(f"refusing to overwrite paired population: {output}")
    population = build_population(
        Path(args.translation_repo).expanduser().resolve(),
        Path(args.source_repo).expanduser().resolve(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text(json.dumps(population, indent=2, sort_keys=True) + "\n")
    partial.replace(output)
    print(json.dumps({
        "task_count": population["task_count"],
        "eligible_count": population["eligible_count"],
        "eligible_verdict_counts": population["eligible_verdict_counts"],
        "source_family_count": population["source_family_count"],
        "population_sha256": population["population_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
