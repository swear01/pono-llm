#!/usr/bin/env python3
"""Build and re-certify the preregistered Gate 5A0 source population."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

import z3

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

import build_paired_corpus  # noqa: E402
import candidate_cert_check  # noqa: E402
import experiment_manifest  # noqa: E402
import grammar_routes  # noqa: E402
import run_phase_grammar  # noqa: E402
import transport_invariant  # noqa: E402
import transport_schema  # noqa: E402
from btor2_reader import parse_btor2  # noqa: E402


SOURCE_CERTIFICATE_TIMEOUT_MS = 20000
PONO_SHOW_INVAR_TIMEOUT_SEC = 20.0
MAX_NORMALIZED_AST_NODES = 50000
MAX_INVARIANT_OUTPUT_BYTES = 5 * 1024 * 1024
INVARIANT_NORMALIZATION_TIMEOUT_SEC = 20.0
MIN_SAFE_BASES = transport_schema.MIN_SAFE_BASES
MIN_SOURCE_FAMILIES = transport_schema.MIN_SOURCE_FAMILIES
MIN_PER_PRIMARY_TRANSFORM = transport_schema.MIN_PER_PRIMARY_TRANSFORM
MIN_INPUT_DRIVEN_T3_FAMILIES = transport_schema.MIN_INPUT_DRIVEN_T3_FAMILIES
MIN_UNSAFE_CONTROLS = transport_schema.MIN_UNSAFE_CONTROLS


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact path is outside repository: {resolved}") from exc


def _verify_summary(path: Path, schema: str) -> dict:
    value = transport_schema.load_json_strict(path)
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise ValueError(f"unexpected summary schema in {path}")
    if "summary_sha256" in value:
        declared = value["summary_sha256"]
        payload = {key: item for key, item in value.items() if key != "summary_sha256"}
        if transport_schema.canonical_sha256(payload) != declared:
            raise ValueError(f"summary self-hash mismatch: {path}")
    return value


def _verify_integrity(root: Path) -> tuple[dict[str, str], Path]:
    path = root / "integrity.json"
    document = transport_schema.load_json_strict(path)
    if not isinstance(document, dict) or set(document) != {
        "schema", "status", "summary_sha256", "files", "integrity_sha256"
    }:
        raise ValueError(f"invalid recursive integrity manifest: {path}")
    if (
        document["schema"] != "pono-llm-representation-phase-artifact-integrity-v1"
        or document["status"] != "completed"
        or not isinstance(document["files"], list)
    ):
        raise ValueError(f"invalid recursive integrity metadata: {path}")
    payload = {
        key: value for key, value in document.items() if key != "integrity_sha256"
    }
    if transport_schema.canonical_sha256(payload) != document["integrity_sha256"]:
        raise ValueError(f"recursive integrity self-hash mismatch: {path}")
    summary_path = root / "summary.json"
    if transport_schema.file_sha256(summary_path) != document["summary_sha256"]:
        raise ValueError(f"recursive integrity summary hash mismatch: {path}")
    files = {}
    for index, row in enumerate(document["files"]):
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ValueError(f"invalid integrity row {index}: {path}")
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe integrity path: {row['path']}")
        target = root / relative
        actual = transport_schema.file_sha256(target)
        if actual != row["sha256"]:
            raise ValueError(f"integrity mismatch: {target}")
        if relative.as_posix() in files:
            raise ValueError(f"duplicate integrity path: {relative}")
        files[relative.as_posix()] = actual
    if files.get("summary.json") != document["summary_sha256"]:
        raise ValueError(f"recursive integrity omits or mismatches summary.json: {path}")
    return files, path


class InvariantNormalizationTimeout(TimeoutError):
    pass


@contextmanager
def _normalization_deadline(seconds: float = INVARIANT_NORMALIZATION_TIMEOUT_SEC):
    if seconds <= 0:
        raise ValueError("normalization deadline must be positive")
    prior_handler = signal.getsignal(signal.SIGALRM)
    prior_timer = signal.getitimer(signal.ITIMER_REAL)
    if prior_timer != (0.0, 0.0):
        raise RuntimeError("refusing to replace an active process timer")

    def timeout_handler(_signum, _frame):
        raise InvariantNormalizationTimeout(
            f"Pono invariant normalization exceeded {seconds:g}s"
        )

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior_handler)


def _pono_output_to_ast(model_path: Path, output: str) -> dict:
    if len(output.encode()) > MAX_INVARIANT_OUTPUT_BYTES:
        raise ValueError(
            f"Pono invariant output exceeds {MAX_INVARIANT_OUTPUT_BYTES} bytes"
        )
    with _normalization_deadline():
        return transport_invariant.pono_invariant_to_ast(
            model_path,
            output,
            max_nodes=MAX_NORMALIZED_AST_NODES,
        )


def _checks_are_unsat(raw: str) -> bool:
    try:
        checks = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid certificate_status JSON: {exc}") from exc
    return bool(checks) and all(check.get("result") == "unsat" for check in checks)


def _hwmcc_family(benchmark_id: str) -> tuple[str, str]:
    path = Path(benchmark_id)
    stem = path.stem
    stem = re.sub(r"_(?:unwind|value)bound\d+$", "", stem)
    parts = list(path.parts)
    anchors = [
        "arithmetic_circuits",
        "nla-digbench-scaling",
        "crafted",
    ]
    anchor_index = next(
        (parts.index(anchor) for anchor in anchors if anchor in parts),
        max(0, len(parts) - 3),
    )
    prefix = [
        part
        for part in parts[anchor_index:-1]
        if part not in {"bv", "btor2", "wordlevel"} and not part.isdigit()
    ]
    key = "hwmcc/" + "/".join([*prefix, stem])
    return key, transport_schema.canonical_sha256({"source_family": key})


def _phase_route_payload(report: dict) -> dict:
    family_fields = {
        "unary": {"constants"},
        "pairwise_offset": {"offsets"},
        "affine": {"coefficient_bound"},
        "sum_equality": set(),
        "quadratic_recurrence": {"scales", "counter_shifts"},
    }
    routes = []
    for index, route in enumerate(report["routes"]):
        family = route.get("family")
        if family not in family_fields:
            raise ValueError(f"report route {index} has unsupported family: {family}")
        fields = {"variables", "family", "relations", "signedness"} | family_fields[family]
        routes.append({key: route[key] for key in fields if key in route})
    return {"schema": grammar_routes.ROUTE_SCHEMA, "routes": routes}


def _candidate_source(
    *,
    benchmark_id: str,
    model_path: Path,
    model_sha256: str,
    family_key: str,
    family_id: str,
    predicates: list[dict],
    kind: str,
    artifacts: list[Path],
    prior_evidence: str,
) -> dict:
    actual = transport_schema.file_sha256(model_path)
    if actual != model_sha256:
        raise ValueError(f"source model hash mismatch for {benchmark_id}")
    normalized = [
        transport_schema.normalize_ast(ast, f"{benchmark_id} predicate {index}")
        for index, ast in enumerate(predicates)
    ]
    report = transport_invariant.certify_predicates(
        model_path, normalized, timeout_ms=SOURCE_CERTIFICATE_TIMEOUT_MS
    )
    if not report["ok"]:
        return {
            "eligible": False,
            "benchmark_id": benchmark_id,
            "source_family_key": family_key,
            "source_family_id": family_id,
            "exclusion_reason": "source-recertification-failed",
            "certificate": report,
            "prior_evidence": prior_evidence,
        }
    origin_artifacts = [
        {
            "path": _repo_relative(path),
            "sha256": transport_schema.file_sha256(path),
        }
        for path in sorted(set(path.resolve() for path in artifacts))
    ]
    document = transport_schema.normalize_invariant_document({
        "schema": transport_schema.INVARIANT_SCHEMA,
        "source": {"benchmark_id": benchmark_id, "sha256": model_sha256},
        "predicates": normalized,
        "origin": {"kind": kind, "artifacts": origin_artifacts},
    })
    return {
        "eligible": True,
        "benchmark_id": benchmark_id,
        "model_path": model_path,
        "model_sha256": model_sha256,
        "source_family_key": family_key,
        "source_family_id": family_id,
        "document": document,
        "document_sha256": transport_schema.canonical_sha256(document),
        "certificate": report,
        "prior_evidence": prior_evidence,
    }


def _phase1_sources(summary_path: Path, summary: dict, hwmcc_root: Path) -> list[dict]:
    sources = [ROOT_DIR / path for path in summary["source_files"]]
    for path in sources:
        if not path.is_file():
            raise ValueError(f"missing Phase 1/2 source artifact: {path}")
    matrix_path = next(
        path for path in sources if path.name == "phase1_2_llm_houdini_full21.csv"
    )
    capture_manifest_path = next(
        path
        for path in sources
        if path.name == "manifest.json" and path.parent.name == "phase1_2_frozen_v2"
    )
    capture_dir = capture_manifest_path.parent
    rows = list(csv.DictReader(matrix_path.open(newline="")))
    matrix_hashes = {
        row["benchmark_id"]: row["benchmark_content_sha256"] for row in rows
    }
    specs = [
        experiment_manifest.BenchmarkSpec(
            benchmark_id,
            hwmcc_root / benchmark_id,
            content_sha256,
        )
        for benchmark_id, content_sha256 in sorted(matrix_hashes.items())
    ]
    bundle = experiment_manifest.validate_capture_bundle(capture_dir, specs)
    records = {
        record["benchmark_id"]: record for record in bundle["manifest"]["benchmarks"]
    }
    results = []
    for row in sorted(rows, key=lambda item: item["benchmark_id"]):
        if row["config"] != "llm-houdini-cert" or row["verdict"] != "unsat":
            continue
        if not _checks_are_unsat(row["certificate_status"]):
            raise ValueError(f"Phase 1/2 UNSAT row lacks exact certificate: {row['benchmark_id']}")
        benchmark_id = row["benchmark_id"]
        model_path = hwmcc_root / benchmark_id
        record = records[benchmark_id]
        candidate_path = capture_dir / record["predicates_file"]
        entries = candidate_cert_check.load_predicate_entries(str(candidate_path))
        asts = [entry["predicate_ast"] for entry in entries]
        houdini = candidate_cert_check.houdini_certify(
            str(model_path), asts, SOURCE_CERTIFICATE_TIMEOUT_MS
        )
        if not houdini["ok"]:
            results.append({
                "eligible": False,
                "benchmark_id": benchmark_id,
                "exclusion_reason": "fresh-houdini-failed",
                "certificate": houdini,
                "prior_evidence": "phase1_2_llm_houdini_full21",
            })
            continue
        predicates = [asts[index] for index in houdini["selected_indices"]]
        family_key, family_id = _hwmcc_family(benchmark_id)
        results.append(_candidate_source(
            benchmark_id=benchmark_id,
            model_path=model_path,
            model_sha256=row["benchmark_content_sha256"],
            family_key=family_key,
            family_id=family_id,
            predicates=predicates,
            kind="frozen-candidate-houdini",
            artifacts=[
                summary_path,
                matrix_path,
                candidate_path,
                capture_manifest_path,
                capture_dir / "integrity.json",
            ],
            prior_evidence="phase1_2_llm_houdini_full21",
        ))
    return results


def _representation_task_index(root: Path) -> tuple[dict[str, dict], Path, Path]:
    population_path = root / "population.json"
    pilot_path = root / "pilot.json"
    population = transport_schema.load_json_strict(population_path)
    if (
        not isinstance(population, dict)
        or population.get("schema") != "pono-llm-paired-population-v1"
    ):
        raise ValueError("invalid representation population schema")
    if transport_schema.canonical_sha256({
        key: value for key, value in population.items() if key != "population_sha256"
    }) != population["population_sha256"]:
        raise ValueError("representation population self-hash mismatch")
    tasks = {task["benchmark_id"]: task for task in population["tasks"]}
    return tasks, population_path, pilot_path


def _representation_direct_sources(
    summary_path: Path,
    root: Path,
    tasks: dict[str, dict],
    translation_repo: Path,
) -> list[dict]:
    reports = sorted(
        list((root / "exhaustive_phase_matrix" / "reports").glob("*.json"))
        + list((root / "routed_phase_matrix" / "reports").glob("*.json"))
    )
    results = []
    for report_path in reports:
        report = transport_schema.load_json_strict(report_path)
        certificate = report.get("certificate", {}) if isinstance(report, dict) else {}
        if not certificate.get("ok"):
            continue
        benchmark_id = report["benchmark_id"]
        task = tasks[benchmark_id]
        model_path = translation_repo / task["btor2_path"]
        if transport_schema.file_sha256(model_path) != report["benchmark_sha256"]:
            raise ValueError(f"phase report model hash mismatch: {benchmark_id}")
        route_payload = _phase_route_payload(report)
        _, _, entries = run_phase_grammar.prepare_entries(
            str(model_path),
            route_payload,
            phase_mode=report["phase_mode"],
            cap=report["pool_candidate_count"],
        )
        lines = run_phase_grammar.entry_lines(entries)
        candidate_text = "\n".join(lines) + "\n"
        if hashlib.sha256(candidate_text.encode()).hexdigest() != report["candidate_sha256"]:
            raise ValueError(f"reconstructed phase candidate hash mismatch: {benchmark_id}")
        indices = certificate["selected_indices"]
        predicates = [entries[index]["predicate_ast"] for index in indices]
        results.append(_candidate_source(
            benchmark_id=benchmark_id,
            model_path=model_path,
            model_sha256=report["benchmark_sha256"],
            family_key=f"svcomp/{task['source_family_id']}",
            family_id=task["source_family_id"],
            predicates=predicates,
            kind="phase-grammar-houdini",
            artifacts=[summary_path, report_path, root / "population.json"],
            prior_evidence=f"{report_path.parent.parent.name}/{report['config']}",
        ))
    return results


def _representation_returned_sources(
    summary_path: Path,
    root: Path,
    tasks: dict[str, dict],
    translation_repo: Path,
) -> list[dict]:
    audit_path = root / "routed_unsat_audit" / "manifest.json"
    audit = transport_schema.load_json_strict(audit_path)
    grouped = defaultdict(list)
    for row in audit["returned_invariant_certificates"]:
        if row.get("certified"):
            grouped[row["benchmark_id"]].append(row)
    results = []
    for benchmark_id, rows in sorted(grouped.items()):
        row = min(rows, key=lambda item: (
            (root / "routed_unsat_audit" / item["invariant_path"]).stat().st_size,
            item["config"],
        ))
        invariant_path = root / "routed_unsat_audit" / row["invariant_path"]
        if transport_schema.file_sha256(invariant_path) != row["invariant_sha256"]:
            raise ValueError(f"returned invariant hash mismatch: {benchmark_id}")
        task = tasks[benchmark_id]
        model_path = translation_repo / task["btor2_path"]
        try:
            predicate = _pono_output_to_ast(model_path, invariant_path.read_text())
        except (
            ValueError,
            KeyError,
            TypeError,
            InvariantNormalizationTimeout,
            z3.Z3Exception,
        ) as exc:
            result = {
                "eligible": False,
                "benchmark_id": benchmark_id,
                "source_family_key": f"svcomp/{task['source_family_id']}",
                "source_family_id": task["source_family_id"],
                "exclusion_reason": "returned-invariant-normalization-failed",
                "error": str(exc),
                "prior_evidence": f"routed_unsat_audit/{row['config']}",
            }
        else:
            result = _candidate_source(
                benchmark_id=benchmark_id,
                model_path=model_path,
                model_sha256=row["content_sha256"],
                family_key=f"svcomp/{task['source_family_id']}",
                family_id=task["source_family_id"],
                predicates=[predicate],
                kind="pono-returned-invariant",
                artifacts=[summary_path, audit_path, invariant_path],
                prior_evidence=f"routed_unsat_audit/{row['config']}",
            )
        results.append(result)
    return results


def _baseline_interp_sources(
    summary_path: Path,
    root: Path,
    tasks: dict[str, dict],
    translation_repo: Path,
    pono: Path,
    transcript_dir: Path,
) -> list[dict]:
    screen_path = root / "baseline_screen.csv"
    rows = list(csv.DictReader(screen_path.open(newline="")))
    results = []
    for row in sorted(rows, key=lambda item: item["benchmark_id"]):
        if (
            row["expected_verdict"] != "safe"
            or row["baseline_verdict"] != "unsat"
            or "interp" not in row["engine"].split("+")
        ):
            continue
        benchmark_id = row["benchmark_id"]
        task = tasks[benchmark_id]
        model_path = translation_repo / task["btor2_path"]
        command = [str(pono), "-e", "interp", "-k", "50", "--show-invar", str(model_path)]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=PONO_SHOW_INVAR_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            results.append({
                "eligible": False,
                "benchmark_id": benchmark_id,
                "source_family_key": f"svcomp/{task['source_family_id']}",
                "source_family_id": task["source_family_id"],
                "exclusion_reason": "show-invar-timeout",
                "prior_evidence": "representation_baseline_screen/interp",
            })
            continue
        raw = completed.stdout + completed.stderr
        transcript_name = experiment_manifest.stable_slug(benchmark_id) + ".interp.log"
        transcript_path = transcript_dir / transcript_name
        if completed.returncode != 1:
            results.append({
                "eligible": False,
                "benchmark_id": benchmark_id,
                "source_family_key": f"svcomp/{task['source_family_id']}",
                "source_family_id": task["source_family_id"],
                "exclusion_reason": "show-invar-not-unsat",
                "error": raw.decode(errors="replace")[-500:],
                "prior_evidence": "representation_baseline_screen/interp",
            })
            continue
        try:
            predicate = _pono_output_to_ast(
                model_path, raw.decode(errors="strict")
            )
        except (
            UnicodeDecodeError,
            ValueError,
            KeyError,
            TypeError,
            InvariantNormalizationTimeout,
            z3.Z3Exception,
        ) as exc:
            result = {
                "eligible": False,
                "benchmark_id": benchmark_id,
                "source_family_key": f"svcomp/{task['source_family_id']}",
                "source_family_id": task["source_family_id"],
                "exclusion_reason": "show-invar-normalization-failed",
                "error": str(exc),
                "prior_evidence": "representation_baseline_screen/interp",
            }
        else:
            with transcript_path.open("xb") as stream:
                stream.write(raw)
            result = _candidate_source(
                benchmark_id=benchmark_id,
                model_path=model_path,
                model_sha256=row["btor2_sha256"],
                family_key=f"svcomp/{task['source_family_id']}",
                family_id=task["source_family_id"],
                predicates=[predicate],
                kind="pono-returned-invariant",
                artifacts=[summary_path, screen_path, transcript_path],
                prior_evidence="representation_baseline_screen/interp",
            )
        results.append(result)
    return results


def _dependency_catalog(model_path: Path) -> tuple[dict[str, set[str]], set[str]]:
    info = parse_btor2(str(model_path))
    state_nodes = {state.lineno: state.ref for state in info.states if not state.is_array}
    input_nodes = {item.lineno: item.ref for item in info.inputs}
    graph = {ref: set() for ref in state_nodes.values()}
    input_driven = set()
    for owner, next_node in info.next_map.items():
        queue = [abs(next_node)]
        visited = set()
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            if node in state_nodes:
                graph[owner].add(state_nodes[node])
                continue
            if node in input_nodes:
                input_driven.add(owner)
                continue
            queue.extend(abs(dep) for dep in info.deps.get(node, []))
    return graph, input_driven


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices = {}
    lowlinks = {}
    stack = []
    on_stack = set()
    components = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for successor in sorted(graph[node]):
            if successor not in indices:
                visit(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            components.append(sorted(component, key=lambda ref: int(ref[5:])))

    for node in sorted(graph, key=lambda ref: int(ref[5:])):
        if node not in indices:
            visit(node)
    return components


def _applicability(model_path: Path, predicates: list[dict]) -> dict:
    info = parse_btor2(str(model_path))
    if info.array_sort_count or any(state.is_array for state in info.states):
        return {
            family: {"applicable": False, "reason": "array-theory"}
            for family in ("T1", "T2", "T3")
        }
    state_widths = {state.ref: state.width for state in info.states}
    invariant_refs = {
        ref
        for predicate in predicates
        for ref in transport_invariant.ast_refs(predicate)
        if ref.startswith("state")
    }
    graph, input_driven_updates = _dependency_catalog(model_path)
    t1_groups = []
    for component in _strongly_connected_components(graph):
        by_width = defaultdict(list)
        for ref in component:
            by_width[state_widths[ref]].append(ref)
        for width, refs in sorted(by_width.items()):
            if len(refs) >= 2 and invariant_refs.intersection(refs):
                t1_groups.append({"width": width, "state_refs": refs[:3]})
    t2_refs = sorted(
        [ref for ref in invariant_refs if state_widths.get(ref, 0) >= 4],
        key=lambda ref: int(ref[5:]),
    )
    update_count = len(info.next_map)
    return {
        "T1": {
            "applicable": bool(t1_groups),
            "reason": "" if t1_groups else "no-invariant-relevant-same-width-multi-state-scc",
            "candidate_groups": t1_groups,
        },
        "T2": {
            "applicable": bool(t2_refs),
            "reason": "" if t2_refs else "no-invariant-relevant-state-width-at-least-4",
            "candidate_state_refs": t2_refs,
        },
        "T3": {
            "applicable": update_count >= 2,
            "reason": "" if update_count >= 2 else "fewer-than-two-state-updates",
            "state_update_count": update_count,
            "input_driven": bool(input_driven_updates),
            "input_driven_state_refs": sorted(
                input_driven_updates, key=lambda ref: int(ref[5:])
            ),
        },
    }


def _polynomial_degree(ast: dict) -> int | None:
    form = ast["form"]
    if form == "const":
        return 0
    if form == "ref":
        return 1
    degrees = [_polynomial_degree(arg) for arg in ast.get("args", [])]
    if form in {"add", "sub"} and all(value is not None for value in degrees):
        return max(degrees, default=0)
    if form == "mul" and all(value is not None for value in degrees):
        return sum(degrees)
    logical_forms = {
        "eq", "ne", "ult", "ule", "ugt", "uge", "slt", "sle", "sgt",
        "sge", "and", "or", "not", "implies",
    }
    if form in logical_forms:
        finite = [value for value in degrees if value is not None]
        return max(finite, default=0) if len(finite) == len(degrees) else None
    return None


def _invariant_classes(predicates: list[dict]) -> list[str]:
    forms = []
    stack = list(predicates)
    while stack:
        node = stack.pop()
        forms.append(node["form"])
        stack.extend(node.get("args", []))
    degrees = [_polynomial_degree(predicate) for predicate in predicates]
    classes = []
    if any(degree is not None and degree >= 2 for degree in degrees):
        classes.append("quadratic-polynomial")
    if any(degree is not None and degree <= 1 for degree in degrees) and any(
        form in {"eq", "ne", "ult", "ule", "ugt", "uge", "slt", "sle", "sgt", "sge"}
        for form in forms
    ):
        classes.append("affine-relational")
    if "implies" in forms:
        classes.append("phase-guarded")
    if len(predicates) >= 2:
        classes.append("conjunctive")
    return classes


def _deduplicate(records: list[dict]) -> tuple[list[dict], list[dict]]:
    eligible = [record for record in records if record.get("eligible")]
    excluded = [record for record in records if not record.get("eligible")]
    origin_rank = {
        "phase-grammar-houdini": 0,
        "frozen-candidate-houdini": 1,
        "pono-returned-invariant": 2,
    }
    by_content = defaultdict(list)
    for record in eligible:
        by_content[record["model_sha256"]].append(record)
    content_unique = []
    for digest, group in sorted(by_content.items()):
        winner = min(group, key=lambda record: (
            transport_invariant.predicate_node_count(record["document"]["predicates"]),
            origin_rank[record["document"]["origin"]["kind"]],
            record["benchmark_id"],
        ))
        content_unique.append(winner)
        for record in group:
            if record is not winner:
                excluded.append({
                    "eligible": False,
                    "benchmark_id": record["benchmark_id"],
                    "exclusion_reason": "exact-content-duplicate",
                    "duplicate_of": winner["benchmark_id"],
                })
    by_family = defaultdict(list)
    for record in content_unique:
        by_family[record["source_family_id"]].append(record)
    family_unique = []
    for family_id, group in sorted(by_family.items()):
        winner = min(group, key=lambda record: (
            transport_invariant.predicate_node_count(record["document"]["predicates"]),
            origin_rank[record["document"]["origin"]["kind"]],
            record["benchmark_id"],
        ))
        family_unique.append(winner)
        for record in group:
            if record is not winner:
                excluded.append({
                    "eligible": False,
                    "benchmark_id": record["benchmark_id"],
                    "exclusion_reason": "source-family-duplicate",
                    "duplicate_of": winner["benchmark_id"],
                })
    family_unique.sort(key=lambda record: record["benchmark_id"])
    return family_unique, excluded


def _unsafe_controls(root: Path, tasks: dict[str, dict], translation_repo: Path) -> list[dict]:
    pilot = transport_schema.load_json_strict(root / "pilot.json")
    controls = []
    for task in pilot["benchmarks"]:
        if task["selection_role"] != "unsafe-soundness-control":
            continue
        source = tasks[task["benchmark_id"]]
        model_path = translation_repo / source["btor2_path"]
        actual = transport_schema.file_sha256(model_path)
        if actual != task["content_sha256"] or task["expected_verdict"] != "unsafe":
            raise ValueError(f"unsafe control identity mismatch: {task['benchmark_id']}")
        controls.append({
            "benchmark_id": task["benchmark_id"],
            "benchmark_sha256": actual,
            "source_family_id": task["source_family_id"],
        })
    unique = {}
    for control in controls:
        unique.setdefault(control["source_family_id"], control)
    return sorted(unique.values(), key=lambda row: row["benchmark_id"])


def build_population(
    phase1_summary_path: Path,
    representation_summary_path: Path,
    output_path: Path,
) -> dict:
    phase1_summary = _verify_summary(
        phase1_summary_path, "pono-llm-phase1-2-summary-v1"
    )
    representation_summary = _verify_summary(
        representation_summary_path, "pono-llm-representation-phase-summary-v1"
    )
    representation_root = representation_summary_path.parent
    _, representation_integrity_path = _verify_integrity(representation_root)
    tasks, representation_population_path, pilot_path = _representation_task_index(
        representation_root
    )
    population_document = transport_schema.load_json_strict(representation_population_path)
    translation_revision = population_document["provenance"]["translation_revision"]
    translation_repo = Path(
        os.environ.get("SVCOMP_BTOR_REPO", "/tmp/svcomp25-sparse")
    ).resolve()
    build_paired_corpus.verify_repository(
        translation_repo, translation_revision, "translation"
    )
    hwmcc_root = Path(
        os.environ.get("HWMCC_ROOT", "/home/swear01/hwmcc_benchmarks")
    ).resolve()
    pono = ROOT_DIR / "build" / "pono"
    if not pono.is_file():
        raise ValueError(f"missing Pono executable: {pono}")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite population: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_dir = output_path.parent / "source_certificates"
    if certificate_dir.exists():
        raise FileExistsError(f"refusing to overwrite certificate directory: {certificate_dir}")
    transcript_dir = output_path.parent / "source_invariants"
    if transcript_dir.exists():
        raise FileExistsError(f"refusing to overwrite transcript directory: {transcript_dir}")
    transcript_dir.mkdir()
    certificate_dir_created = False
    output_created = False

    try:
        records = []
        records.extend(_phase1_sources(
            phase1_summary_path, phase1_summary, hwmcc_root
        ))
        records.extend(_representation_direct_sources(
            representation_summary_path,
            representation_root,
            tasks,
            translation_repo,
        ))
        records.extend(_representation_returned_sources(
            representation_summary_path,
            representation_root,
            tasks,
            translation_repo,
        ))
        records.extend(_baseline_interp_sources(
            representation_summary_path,
            representation_root,
            tasks,
            translation_repo,
            pono,
        transcript_dir,
    ))

        selected, exclusions = _deduplicate(records)
        certificate_dir.mkdir()
        certificate_dir_created = True

        population_rows = []
        for record in selected:
            slug = experiment_manifest.stable_slug(record["benchmark_id"])
            certificate_path = certificate_dir / f"{slug}.json"
            with certificate_path.open("x") as stream:
                stream.write(
                    json.dumps(record["document"], indent=2, sort_keys=True) + "\n"
                )
            applicability = _applicability(
                record["model_path"], record["document"]["predicates"]
            )
            classes = _invariant_classes(record["document"]["predicates"])
            population_rows.append({
                "benchmark_id": record["benchmark_id"],
                "benchmark_sha256": record["model_sha256"],
                "source_family_key": record["source_family_key"],
                "source_family_id": record["source_family_id"],
                "source_certificate_path": _repo_relative(certificate_path),
                "source_certificate_file_sha256": transport_schema.file_sha256(certificate_path),
                "source_certificate_sha256": record["document_sha256"],
                "source_certificate_origin": record["document"]["origin"]["kind"],
                "prior_evidence": record["prior_evidence"],
                "predicate_count": len(record["document"]["predicates"]),
                "ast_node_count": transport_invariant.predicate_node_count(
                    record["document"]["predicates"]
                ),
                "invariant_classes": classes,
                "certificate": record["certificate"],
                "applicability": applicability,
            })

        unsafe = _unsafe_controls(representation_root, tasks, translation_repo)
        class_counts = Counter(
            label for row in population_rows for label in row["invariant_classes"]
        )
        applicability_counts = {
            family: sum(
                row["applicability"][family]["applicable"]
                for row in population_rows
            )
            for family in ("T1", "T2", "T3")
        }
        t3_input_families = {
            row["source_family_id"]
            for row in population_rows
            if row["applicability"]["T3"]["applicable"]
            and row["applicability"]["T3"]["input_driven"]
        }
        conditions = {
            "safe_base_count": {
                "actual": len(population_rows),
                "required": MIN_SAFE_BASES,
                "pass": len(population_rows) >= MIN_SAFE_BASES,
            },
            "source_family_count": {
                "actual": len({row["source_family_id"] for row in population_rows}),
                "required": MIN_SOURCE_FAMILIES,
                "pass": (
                    len({row["source_family_id"] for row in population_rows})
                    >= MIN_SOURCE_FAMILIES
                ),
            },
            "affine_relational_class": {
                "actual": class_counts["affine-relational"],
                "required": 1,
                "pass": class_counts["affine-relational"] >= 1,
            },
            "quadratic_polynomial_class": {
                "actual": class_counts["quadratic-polynomial"],
                "required": 1,
                "pass": class_counts["quadratic-polynomial"] >= 1,
            },
            "phase_guarded_or_genuinely_conjunctive_class": {
                "actual": class_counts["phase-guarded"],
                "required": 1,
                "pass": class_counts["phase-guarded"] >= 1,
                "implementation_note": (
                    "v1 counts only the stricter phase-guarded disjunct; "
                    "syntactic multi-predicate conjunctions are reported but "
                    "do not pass this condition"
                ),
            },
            **{
                f"{family}_applicable_base_count": {
                    "actual": applicability_counts[family],
                    "required": MIN_PER_PRIMARY_TRANSFORM,
                    "pass": (
                        applicability_counts[family]
                        >= MIN_PER_PRIMARY_TRANSFORM
                    ),
                }
                for family in ("T1", "T2", "T3")
            },
            "T3_input_driven_source_family_count": {
                "actual": len(t3_input_families),
                "required": MIN_INPUT_DRIVEN_T3_FAMILIES,
                "pass": len(t3_input_families) >= MIN_INPUT_DRIVEN_T3_FAMILIES,
            },
            "unsafe_control_count": {
                "actual": len(unsafe),
                "required": MIN_UNSAFE_CONTROLS,
                "pass": len(unsafe) >= MIN_UNSAFE_CONTROLS,
            },
        }
        failed = sorted(
            name for name, condition in conditions.items() if not condition["pass"]
        )
        revision = subprocess.run(
            ["git", "-C", str(ROOT_DIR), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        report = {
            "schema": transport_schema.POPULATION_SCHEMA,
            "decision": (
                "population-sufficient" if not failed else "population-insufficient"
            ),
            "failed_conditions": failed,
            "conditions": conditions,
            "counts": {
                "discovered_record_count": len(records),
                "eligible_before_dedup_count": sum(
                    record.get("eligible", False) for record in records
                ),
                "safe_base_count": len(population_rows),
                "source_family_count": len({
                    row["source_family_id"] for row in population_rows
                }),
                "source_origin_counts": dict(sorted(Counter(
                    row["source_certificate_origin"] for row in population_rows
                ).items())),
                "invariant_class_counts": dict(sorted(class_counts.items())),
                "applicability_counts": applicability_counts,
                "T3_input_driven_source_family_count": len(t3_input_families),
                "unsafe_control_count": len(unsafe),
                "exclusion_reason_counts": dict(sorted(Counter(
                    row.get("exclusion_reason", "unknown") for row in exclusions
                ).items())),
            },
            "provenance": {
                "generator_commit": revision,
                "pono_sha256": transport_schema.file_sha256(pono),
                "phase1_summary_path": _repo_relative(phase1_summary_path),
                "phase1_summary_sha256": transport_schema.file_sha256(
                    phase1_summary_path
                ),
                "representation_summary_path": _repo_relative(
                    representation_summary_path
                ),
                "representation_summary_sha256": transport_schema.file_sha256(
                    representation_summary_path
                ),
                "representation_population_path": _repo_relative(
                    representation_population_path
                ),
                "representation_population_sha256": transport_schema.file_sha256(
                    representation_population_path
                ),
                "representation_integrity_path": _repo_relative(
                    representation_integrity_path
                ),
                "representation_integrity_sha256": transport_schema.file_sha256(
                    representation_integrity_path
                ),
                "pilot_path": _repo_relative(pilot_path),
                "pilot_sha256": transport_schema.file_sha256(pilot_path),
                "source_certificate_timeout_ms": SOURCE_CERTIFICATE_TIMEOUT_MS,
                "show_invar_timeout_sec": PONO_SHOW_INVAR_TIMEOUT_SEC,
                "max_normalized_ast_nodes": MAX_NORMALIZED_AST_NODES,
                "max_invariant_output_bytes": MAX_INVARIANT_OUTPUT_BYTES,
                "invariant_normalization_timeout_sec": (
                    INVARIANT_NORMALIZATION_TIMEOUT_SEC
                ),
                "llm_api_calls": 0,
            },
            "safe_bases": population_rows,
            "unsafe_controls": unsafe,
            "exclusions": sorted(
                [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"model_path", "document"}
                    }
                    for row in exclusions
                ],
                key=lambda row: (
                    row.get("benchmark_id", ""),
                    row.get("exclusion_reason", ""),
                ),
            ),
        }
        report["population_sha256"] = transport_schema.canonical_sha256(report)
        transport_schema.validate_population_document(report)
        with output_path.open("x") as stream:
            output_created = True
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return report
    except BaseException:
        if output_created and output_path.exists():
            output_path.unlink()
        if certificate_dir_created and certificate_dir.exists():
            shutil.rmtree(certificate_dir)
        if transcript_dir.exists():
            shutil.rmtree(transcript_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-summary", required=True)
    parser.add_argument("--representation-summary", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_population(
        Path(args.phase1_summary).resolve(),
        Path(args.representation_summary).resolve(),
        Path(args.out).resolve(),
    )
    print(json.dumps({
        "decision": report["decision"],
        "failed_conditions": report["failed_conditions"],
        "counts": report["counts"],
        "population_sha256": report["population_sha256"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
