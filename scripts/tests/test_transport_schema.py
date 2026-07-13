from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import transport_schema  # noqa: E402


def ref(name: str) -> dict:
    return {"form": "ref", "ref": name}


def const(value: int, width: int) -> dict:
    return {"form": "const", "const": str(value), "width": width}


def invariant_document() -> dict:
    return {
        "schema": transport_schema.INVARIANT_SCHEMA,
        "source": {"benchmark_id": "suite/source.btor2", "sha256": "a" * 64},
        "predicates": [{"form": "eq", "args": [ref("state4"), const(0, 8)]}],
        "origin": {
            "kind": "frozen-candidate-houdini",
            "artifacts": [{"path": "artifacts/source.jsonl", "sha256": "b" * 64}],
        },
    }


def map_document() -> dict:
    invariant = transport_schema.normalize_invariant_document(invariant_document())
    parameters = {"matrix": [[1]], "offset": [1]}
    return {
        "schema": transport_schema.MAP_SCHEMA,
        "source": invariant["source"],
        "target": {"benchmark_id": "transport/target.btor2", "sha256": "c" * 64},
        "transformation": {
            "family": "affine-recode",
            "version": 1,
            "seed": 11,
            "parameters": parameters,
            "parameters_sha256": transport_schema.canonical_sha256(parameters),
        },
        "projection": {"state4": {"form": "sub", "args": [ref("state9"), const(1, 8)]}},
        "input_map": {},
        "inverse_embedding": {"state9": {"form": "add", "args": [ref("state4"), const(1, 8)]}},
        "observation_predicate": None,
        "property_map": [{"source_bad_index": 0, "target_bad_index": 0}],
        "generated_map_invariants": [],
        "source_certificate_sha256": transport_schema.canonical_sha256(invariant),
        "generator_commit": "d" * 40,
        "validator_version_sha256": "e" * 64,
    }


def population_document() -> dict:
    row = {
        "benchmark_id": "suite/source.btor2",
        "benchmark_sha256": "1" * 64,
        "source_family_key": "suite/source",
        "source_family_id": "2" * 64,
        "source_certificate_path": "artifacts/transport/source.json",
        "source_certificate_file_sha256": "3" * 64,
        "source_certificate_sha256": "4" * 64,
        "source_certificate_origin": "frozen-candidate-houdini",
        "prior_evidence": "frozen-test",
        "predicate_count": 1,
        "ast_node_count": 3,
        "invariant_classes": ["affine-relational"],
        "certificate": {
            "ok": True,
            "checks": [
                {"name": "C1 Init=>H", "result": "unsat", "time_sec": 0.1, "unknown_reason": ""},
                {"name": "C2 inductive", "result": "unsat", "time_sec": 0.2, "unknown_reason": ""},
                {
                    "name": "C3[0] H=>notBAD",
                    "result": "unsat",
                    "time_sec": 0.1,
                    "unknown_reason": "",
                },
            ],
            "bad_count": 1,
            "predicate_count": 1,
            "ast_node_count": 3,
        },
        "applicability": {
            "T1": {"applicable": False, "reason": "none", "candidate_groups": []},
            "T2": {"applicable": True, "reason": "", "candidate_state_refs": ["state4"]},
            "T3": {
                "applicable": True,
                "reason": "",
                "state_update_count": 2,
                "input_driven": True,
                "input_driven_state_refs": ["state4"],
            },
        },
    }
    document = {
        "schema": transport_schema.POPULATION_SCHEMA,
        "decision": "population-insufficient",
        "failed_conditions": [
            "T1_applicable_base_count",
            "T2_applicable_base_count",
            "T3_applicable_base_count",
            "T3_input_driven_source_family_count",
            "phase_guarded_or_genuinely_conjunctive_class",
            "quadratic_polynomial_class",
            "safe_base_count",
            "source_family_count",
            "unsafe_control_count",
        ],
        "conditions": {
            "safe_base_count": {"actual": 1, "required": 12, "pass": False},
            "source_family_count": {"actual": 1, "required": 8, "pass": False},
            "affine_relational_class": {"actual": 1, "required": 1, "pass": True},
            "quadratic_polynomial_class": {"actual": 0, "required": 1, "pass": False},
            "phase_guarded_or_genuinely_conjunctive_class": {
                "actual": 0,
                "required": 1,
                "pass": False,
            },
            "T1_applicable_base_count": {"actual": 0, "required": 8, "pass": False},
            "T2_applicable_base_count": {"actual": 1, "required": 8, "pass": False},
            "T3_applicable_base_count": {"actual": 1, "required": 8, "pass": False},
            "T3_input_driven_source_family_count": {
                "actual": 1,
                "required": 3,
                "pass": False,
            },
            "unsafe_control_count": {"actual": 1, "required": 4, "pass": False},
        },
        "counts": {
            "discovered_record_count": 1,
            "eligible_before_dedup_count": 1,
            "safe_base_count": 1,
            "source_family_count": 1,
            "source_origin_counts": {"frozen-candidate-houdini": 1},
            "invariant_class_counts": {"affine-relational": 1},
            "applicability_counts": {"T1": 0, "T2": 1, "T3": 1},
            "T3_input_driven_source_family_count": 1,
            "unsafe_control_count": 1,
            "exclusion_reason_counts": {},
        },
        "provenance": {
            "generator_commit": "5" * 40,
            "pono_sha256": "6" * 64,
            "phase1_summary_path": "artifacts/phase1.json",
            "phase1_summary_sha256": "7" * 64,
            "representation_summary_path": "artifacts/representation/summary.json",
            "representation_summary_sha256": "8" * 64,
            "representation_population_path": "artifacts/representation/population.json",
            "representation_population_sha256": "9" * 64,
            "representation_integrity_path": "artifacts/representation/integrity.json",
            "representation_integrity_sha256": "d" * 64,
            "pilot_path": "artifacts/representation/pilot.json",
            "pilot_sha256": "a" * 64,
            "source_certificate_timeout_ms": 20000,
            "show_invar_timeout_sec": 20.0,
            "max_normalized_ast_nodes": 50000,
            "max_invariant_output_bytes": 5 * 1024 * 1024,
            "invariant_normalization_timeout_sec": 20.0,
            "llm_api_calls": 0,
        },
        "safe_bases": [row],
        "unsafe_controls": [{
            "benchmark_id": "suite/unsafe.btor2",
            "benchmark_sha256": "b" * 64,
            "source_family_id": "c" * 64,
        }],
        "exclusions": [],
    }
    document["population_sha256"] = transport_schema.canonical_sha256(document)
    return document


def test_invariant_schema_is_canonical_and_strict():
    document = invariant_document()
    normalized = transport_schema.normalize_invariant_document(document)
    assert normalized == document
    assert transport_schema.canonical_sha256(normalized) == hashlib.sha256(
        transport_schema.canonical_json(normalized).encode()
    ).hexdigest()
    document["fallback"] = True
    with pytest.raises(ValueError, match="fields mismatch"):
        transport_schema.normalize_invariant_document(document)


def test_ast_schema_rejects_unknown_form_and_fields():
    with pytest.raises(ValueError, match="unsupported form"):
        transport_schema.normalize_ast({"form": "read", "args": []})
    with pytest.raises(ValueError, match="fields mismatch"):
        transport_schema.normalize_ast({
            "form": "ref", "ref": "state4", "symbol": "x"
        })
    with pytest.raises(ValueError, match="stateN or inputN"):
        transport_schema.normalize_ast({"form": "ref", "ref": "x"})
    with pytest.raises(ValueError, match="invalid BV constant"):
        transport_schema.normalize_ast({
            "form": "const", "const": "#b1", "width": 8
        })


def test_strict_json_loader_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        transport_schema.load_json_strict(path)


def test_map_schema_checks_parameter_hash_and_frozen_seed():
    document = map_document()
    assert transport_schema.normalize_map_document(document) == document
    document["transformation"]["parameters_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="parameters hash mismatch"):
        transport_schema.normalize_map_document(document)
    document = map_document()
    document["transformation"]["seed"] = 99
    with pytest.raises(ValueError, match="seed is not frozen"):
        transport_schema.normalize_map_document(document)


def test_map_schema_enforces_family_specific_fields():
    exact = map_document()
    exact["inverse_embedding"] = {}
    with pytest.raises(ValueError, match="requires a non-empty inverse_embedding"):
        transport_schema.normalize_map_document(exact)

    stutter = map_document()
    stutter["transformation"]["family"] = "stutter"
    stutter["inverse_embedding"] = {}
    with pytest.raises(ValueError, match="requires an observation_predicate"):
        transport_schema.normalize_map_document(stutter)
    stutter["observation_predicate"] = {
        "form": "eq", "args": [ref("state12"), const(0, 2)]
    }
    normalized = transport_schema.normalize_map_document(stutter)
    assert normalized["transformation"]["family"] == "stutter"


def test_generated_map_invariants_must_remain_empty():
    document = map_document()
    document["generated_map_invariants"] = [
        {"form": "eq", "args": [ref("state4"), const(0, 8)]}
    ]
    with pytest.raises(ValueError, match="must be present and empty"):
        transport_schema.normalize_map_document(document)


def test_map_property_indices_are_one_to_one():
    document = map_document()
    document["property_map"].append({
        "source_bad_index": 0, "target_bad_index": 1
    })
    with pytest.raises(ValueError, match="one-to-one"):
        transport_schema.normalize_map_document(document)


def test_population_schema_checks_proofs_counts_and_self_hash():
    document = population_document()
    assert transport_schema.validate_population_document(document) == document
    document["counts"]["safe_base_count"] = 2
    document["population_sha256"] = transport_schema.canonical_sha256({
        key: value for key, value in document.items() if key != "population_sha256"
    })
    with pytest.raises(ValueError, match="count mismatch"):
        transport_schema.validate_population_document(document)


def test_population_schema_rejects_unknown_as_proof():
    document = population_document()
    document["safe_bases"][0]["certificate"]["checks"][1]["result"] = "unknown"
    document["population_sha256"] = transport_schema.canonical_sha256({
        key: value for key, value in document.items() if key != "population_sha256"
    })
    with pytest.raises(ValueError, match="non-proof check"):
        transport_schema.validate_population_document(document)
