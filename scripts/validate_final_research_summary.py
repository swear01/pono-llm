#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pono-llm-final-research-summary-v1"
CLOSURE_COMMIT = "6fdb7cfd7ddf2f50aff87a8658174bd4cfbb9b2c"
CLOSURE_TAG = "soundness-audit-final-v1"
ADDENDUM_COMMIT = "536a1753f5bb8c0be475dd5f7700045f11ab9f14"
GATE_DECISIONS = {
    "S0": "rejected",
    "S1": "supported",
    "S2": "rejected",
    "S3": "rejected",
    "S4": "mixed-negative",
    "S5": "not-run",
    "S6": "rejected",
    "S7": "not-run-population-insufficient",
}
GATE_EVIDENCE_PATHS = {
    "S0": {
        "scripts/audit_proof_soundness.py",
        "scripts/scan_hint_truth.py",
        "scripts/cert_check.py",
    },
    "S1": {
        "engines/ic3ia.cpp",
        "llm_worker/invariant_arith.py",
        "scripts/candidate_cert_check.py",
    },
    "S2": {"artifacts/phase1_2_summary_v1.json"},
    "S3": {"artifacts/gate2_summary_v1.json"},
    "S4": {
        "artifacts/representation_phase_v1/population.json",
        "artifacts/representation_phase_v1/summary.json",
    },
    "S5": {
        "artifacts/algebraic_certificate_v1/population.json",
        "artifacts/algebraic_certificate_v1/summary.json",
    },
    "S6": {"artifacts/inductiveness_gap_v1/summary.json"},
    "S7": {"artifacts/certified_transport_v1/population.json"},
}
ADDENDUM_EVIDENCE_PATHS = {
    "artifacts/capability_gate_ledger_v1/ledger.json",
    "artifacts/capability_gate_ledger_v1/external_replication.json",
}
ENVIRONMENT_LIMITATIONS = {
    "gate5-asan-address-space",
    "cpp-leaksanitizer",
    "python-smt-switch-binding",
    "openrouter-live-timeout",
}

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def summary_sha256(document: dict[str, object]) -> str:
    unhashed = dict(document)
    unhashed.pop("summary_sha256", None)
    return hashlib.sha256(canonical_bytes(unhashed)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_strict(path: Path) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(), object_pairs_hook=hook)
    if not isinstance(value, dict):
        raise ValueError("summary must be a JSON object")
    return value


def strict_fields(value: object, expected: set[str], location: str) -> dict[str, object]:
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


def nonempty_text_list(value: object, location: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location} must be a non-empty list")
    for index, item in enumerate(value):
        nonempty_text(item, f"{location}[{index}]")
    return value


def validate_commit(value: object, location: str, root: Path, check_git: bool) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError(f"{location} must be a full Git commit")
    if check_git:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{value}^{{commit}}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise ValueError(f"{location} does not resolve to a commit: {value}")
    return value


def validate_reference(
    value: object,
    location: str,
    root: Path,
    check_files: bool,
) -> dict[str, object]:
    record = strict_fields(value, {"kind", "path", "sha256"}, location)
    nonempty_text(record["kind"], f"{location}.kind")
    raw_path = nonempty_text(record["path"], f"{location}.path")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{location}.path must be repository-relative and contain no '..'")
    digest = record["sha256"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ValueError(f"{location}.sha256 must be a lowercase SHA-256 digest")
    resolved_root = root.resolve()
    resolved_path = (root / relative).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{location}.path escapes the repository") from exc
    if check_files:
        if not resolved_path.is_file():
            raise ValueError(f"{location}.path is not a file: {raw_path}")
        actual = sha256_file(resolved_path)
        if actual != digest:
            raise ValueError(f"{location} SHA-256 mismatch: expected {digest}, got {actual}")
    return record


def validate_source_semantics(root: Path) -> None:
    phase1 = load_strict(root / "artifacts/phase1_2_summary_v1.json")
    if (
        phase1.get("schema") != "pono-llm-phase1-2-summary-v1"
        or phase1.get("matched_set_equal") is not True
        or phase1.get("llm_specific_unsat_benchmark_ids") != []
    ):
        raise ValueError("Phase 1+2 source semantics mismatch")
    portfolio = phase1.get("deterministic_portfolio")
    if (
        not isinstance(portfolio, dict)
        or len(portfolio.get("unsat_benchmark_ids", [])) != 8
        or len(portfolio.get("sat_benchmark_ids", [])) != 2
    ):
        raise ValueError("Phase 1+2 portfolio counts mismatch")

    gate2 = load_strict(root / "artifacts/gate2_summary_v1.json")
    if (
        gate2.get("schema") != "pono-llm-gate2-summary-v1"
        or gate2.get("matched_unsat_set_equal") is not True
        or gate2.get("llm_specific_unsat_benchmark_ids") != []
    ):
        raise ValueError("Gate 2 source semantics mismatch")

    representation = load_strict(
        root / "artifacts/representation_phase_v1/summary.json"
    )
    if representation.get("decisions") != {
        "H1_phase_local": False,
        "H2_source_representation": False,
        "H3_llm_routing": False,
        "H4_soundness": True,
    }:
        raise ValueError("representation/phase source decisions mismatch")

    algebraic = load_strict(root / "artifacts/algebraic_certificate_v1/summary.json")
    decisions = algebraic.get("decisions")
    if not isinstance(decisions, dict) or {
        "H5a_kernel_value": decisions.get("H5a_kernel_value"),
        "H5b_llm_value": decisions.get("H5b_llm_value"),
        "H5c_development_soundness": decisions.get("H5c_development_soundness"),
        "paid_llm_capture_performed": decisions.get("paid_llm_capture_performed"),
    } != {
        "H5a_kernel_value": "not-run",
        "H5b_llm_value": "not-authorized",
        "H5c_development_soundness": True,
        "paid_llm_capture_performed": False,
    }:
        raise ValueError("algebraic source decisions mismatch")

    inductiveness = load_strict(root / "artifacts/inductiveness_gap_v1/summary.json")
    if (
        inductiveness.get("classification_counts") != {"FALSE_CANDIDATE": 6}
        or inductiveness.get("false_safe") != 0
    ):
        raise ValueError("inductiveness-gap source decisions mismatch")

    transport = load_strict(root / "artifacts/certified_transport_v1/population.json")
    counts = transport.get("counts")
    applicability = counts.get("applicability_counts") if isinstance(counts, dict) else None
    if (
        transport.get("decision") != "population-insufficient"
        or not isinstance(counts, dict)
        or not isinstance(applicability, dict)
        or counts.get("safe_base_count") != 11
        or applicability.get("T1") != 6
    ):
        raise ValueError("transport source decision mismatch")

    ledger = load_strict(root / "artifacts/capability_gate_ledger_v1/ledger.json")
    external = ledger.get("prospective_external_replication")
    if (
        ledger.get("schema") != "oracle-first-capability-ledger-v1"
        or ledger.get("study_count") != 8
        or not isinstance(external, dict)
        or external.get("decision") != "STOP_EXTERNAL_ARTIFACTS_UNAVAILABLE"
    ):
        raise ValueError("post-boundary addendum source semantics mismatch")


def validate_document(
    document: dict[str, object],
    root: Path = ROOT,
    *,
    check_files: bool = True,
    check_git: bool = True,
) -> dict[str, object]:
    summary = strict_fields(
        document,
        {
            "schema",
            "program",
            "closure_boundary",
            "closure_record",
            "final_scoped_conclusion",
            "claim_ledger",
            "narrative",
            "gates",
            "post_boundary_addenda",
            "environment_limitations",
            "future_work_boundary",
            "summary_sha256",
        },
        "summary",
    )
    if summary["schema"] != SCHEMA:
        raise ValueError("unsupported final-summary schema")
    saved_hash = summary["summary_sha256"]
    if not isinstance(saved_hash, str) or not _SHA256.fullmatch(saved_hash):
        raise ValueError("summary_sha256 must be a lowercase SHA-256 digest")
    actual_hash = summary_sha256(summary)
    if saved_hash != actual_hash:
        raise ValueError(f"summary self-hash mismatch: expected {saved_hash}, got {actual_hash}")

    program = strict_fields(
        summary["program"], {"repository", "branch", "status", "scope"}, "program"
    )
    if program["repository"] != "swear01/pono-llm" or program["branch"] != "soundness-audit":
        raise ValueError("program repository/branch mismatch")
    if program["status"] != "closed":
        raise ValueError("research program must be closed")
    nonempty_text(program["scope"], "program.scope")

    boundary = strict_fields(summary["closure_boundary"], {"tag", "commit"}, "closure_boundary")
    if boundary != {"tag": CLOSURE_TAG, "commit": CLOSURE_COMMIT}:
        raise ValueError("closure boundary mismatch")
    validate_commit(boundary["commit"], "closure_boundary.commit", root, check_git)
    if check_git:
        result = subprocess.run(
            ["git", "rev-parse", f"{CLOSURE_TAG}^{{}}"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.stdout.strip() != CLOSURE_COMMIT:
            raise ValueError("closure tag does not resolve to the frozen commit")

    closure = strict_fields(
        summary["closure_record"],
        {
            "closed_date",
            "evidence_frozen_at",
            "closure_only",
            "new_pono_or_llm_experiment_data",
            "new_llm_or_api_calls",
            "threshold_changes",
            "gate6_authorized",
        },
        "closure_record",
    )
    if (
        closure["closed_date"] != "2026-07-14"
        or closure["evidence_frozen_at"] != CLOSURE_COMMIT
    ):
        raise ValueError("closure date or evidence boundary mismatch")
    if closure["closure_only"] is not True:
        raise ValueError("closure_only must be true")
    if closure["new_pono_or_llm_experiment_data"] is not False:
        raise ValueError("closure must not add Pono/LLM experiment data")
    if closure["new_llm_or_api_calls"] != 0:
        raise ValueError("closure must record zero new LLM/API calls")
    if (
        closure["threshold_changes"] is not False
        or closure["gate6_authorized"] is not False
    ):
        raise ValueError("closure cannot change thresholds or authorize Gate 6")

    nonempty_text(summary["final_scoped_conclusion"], "final_scoped_conclusion")
    validate_reference(summary["claim_ledger"], "claim_ledger", root, check_files)
    validate_reference(summary["narrative"], "narrative", root, check_files)

    gates = summary["gates"]
    if not isinstance(gates, list):
        raise ValueError("gates must be a list")
    gate_ids = [gate.get("gate_id") if isinstance(gate, dict) else None for gate in gates]
    if gate_ids != list(GATE_DECISIONS):
        raise ValueError(f"gate order/set mismatch: {gate_ids}")
    for gate_index, raw_gate in enumerate(gates):
        location = f"gates[{gate_index}]"
        gate = strict_fields(
            raw_gate,
            {
                "gate_id",
                "title",
                "hypothesis",
                "threshold",
                "decision",
                "observed_result",
                "commits",
                "evidence",
                "authorized_follow_on",
                "prohibited_interpretations",
            },
            location,
        )
        gate_id = gate["gate_id"]
        if gate["decision"] != GATE_DECISIONS[gate_id]:
            raise ValueError(f"{location}.decision mismatch")
        for field in ("title", "hypothesis", "threshold", "observed_result"):
            nonempty_text(gate[field], f"{location}.{field}")
        commits = strict_fields(
            gate["commits"],
            {"preregistration", "implementation", "decision"},
            f"{location}.commits",
        )
        preregistration = commits["preregistration"]
        if preregistration is not None:
            validate_commit(
                preregistration,
                f"{location}.commits.preregistration",
                root,
                check_git,
            )
        implementations = commits["implementation"]
        if not isinstance(implementations, list) or not implementations:
            raise ValueError(f"{location}.commits.implementation must be non-empty")
        for commit_index, commit in enumerate(implementations):
            validate_commit(
                commit,
                f"{location}.commits.implementation[{commit_index}]",
                root,
                check_git,
            )
        validate_commit(commits["decision"], f"{location}.commits.decision", root, check_git)
        evidence = gate["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{location}.evidence must be non-empty")
        for evidence_index, reference in enumerate(evidence):
            validate_reference(
                reference,
                f"{location}.evidence[{evidence_index}]",
                root,
                check_files,
            )
        evidence_paths = {reference["path"] for reference in evidence}
        if evidence_paths != GATE_EVIDENCE_PATHS[gate_id]:
            raise ValueError(f"{location}.evidence path set mismatch")
        if gate["authorized_follow_on"] != []:
            raise ValueError(f"{location}.authorized_follow_on must be empty")
        nonempty_text_list(
            gate["prohibited_interpretations"],
            f"{location}.prohibited_interpretations",
        )

    addenda = summary["post_boundary_addenda"]
    if not isinstance(addenda, list) or len(addenda) != 1:
        raise ValueError("exactly one post-boundary methodology addendum is required")
    addendum = strict_fields(
        addenda[0],
        {
            "addendum_id",
            "commit",
            "status",
            "scope",
            "evidence",
            "changes_final_claims",
            "authorizes_follow_on",
        },
        "post_boundary_addenda[0]",
    )
    if (
        addendum["addendum_id"] != "A1"
        or addendum["status"] != "frozen-methodology-addendum"
    ):
        raise ValueError("post-boundary addendum identity/status mismatch")
    if addendum["commit"] != ADDENDUM_COMMIT:
        raise ValueError("post-boundary addendum commit mismatch")
    validate_commit(addendum["commit"], "post_boundary_addenda[0].commit", root, check_git)
    nonempty_text(addendum["scope"], "post_boundary_addenda[0].scope")
    evidence = addendum["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("post-boundary addendum evidence must be non-empty")
    for index, reference in enumerate(evidence):
        validate_reference(
            reference,
            f"post_boundary_addenda[0].evidence[{index}]",
            root,
            check_files,
        )
    if {reference["path"] for reference in evidence} != ADDENDUM_EVIDENCE_PATHS:
        raise ValueError("post-boundary addendum evidence path set mismatch")
    if (
        addendum["changes_final_claims"] is not False
        or addendum["authorizes_follow_on"] is not False
    ):
        raise ValueError("post-boundary addendum cannot change claims or authorize follow-on work")

    limitations = summary["environment_limitations"]
    if not isinstance(limitations, list):
        raise ValueError("environment_limitations must be a list")
    limitation_ids: set[str] = set()
    for index, raw_limitation in enumerate(limitations):
        location = f"environment_limitations[{index}]"
        limitation = strict_fields(
            raw_limitation,
            {"limitation_id", "status", "effect", "prohibited_remediation"},
            location,
        )
        limitation_id = limitation["limitation_id"]
        if limitation_id in limitation_ids:
            raise ValueError(f"duplicate environment limitation: {limitation_id}")
        limitation_ids.add(limitation_id)
        for field in ("status", "effect", "prohibited_remediation"):
            nonempty_text(limitation[field], f"{location}.{field}")
    if limitation_ids != ENVIRONMENT_LIMITATIONS:
        raise ValueError(f"environment limitation set mismatch: {sorted(limitation_ids)}")

    future = strict_fields(
        summary["future_work_boundary"],
        {
            "current_program_extension_authorized",
            "gate6_authorized",
            "next_project_must_be_independent",
            "requirements",
        },
        "future_work_boundary",
    )
    if (
        future["current_program_extension_authorized"] is not False
        or future["gate6_authorized"] is not False
    ):
        raise ValueError("future work cannot extend this program or authorize Gate 6")
    if future["next_project_must_be_independent"] is not True:
        raise ValueError("future work must be an independent research project")
    nonempty_text_list(future["requirements"], "future_work_boundary.requirements")
    if check_files:
        validate_source_semantics(root)
    return summary


def validate(path: Path = ROOT / "artifacts/final_research_summary_v1.json") -> dict[str, object]:
    return validate_document(load_strict(path), ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "summary",
        nargs="?",
        type=Path,
        default=ROOT / "artifacts/final_research_summary_v1.json",
    )
    args = parser.parse_args()
    checked = validate(args.summary)
    print(f"valid {args.summary} ({checked['summary_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
