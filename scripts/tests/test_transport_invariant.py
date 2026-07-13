from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import transport_invariant  # noqa: E402
import transport_schema  # noqa: E402
import build_transport_population  # noqa: E402
import grammar_routes  # noqa: E402
import run_phase_grammar  # noqa: E402


def ref(name: str) -> dict:
    return {"form": "ref", "ref": name}


def const(value: int, width: int) -> dict:
    return {"form": "const", "const": str(value), "width": width}


def write_model(path: Path, *, second_bad: bool = False) -> None:
    lines = [
        "1 sort bitvec 8",
        "2 sort bitvec 1",
        "3 zero 1",
        "4 one 1",
        "5 state 1 x",
        "6 init 1 5 3",
        "7 next 1 5 5",
        "8 eq 2 5 4",
        "9 bad 8",
    ]
    if second_bad:
        lines += ["10 constd 1 2", "11 eq 2 5 10", "12 bad 11"]
    path.write_text("\n".join(lines) + "\n")


def invariant_document() -> dict:
    return transport_schema.normalize_invariant_document({
        "schema": transport_schema.INVARIANT_SCHEMA,
        "source": {"benchmark_id": "suite/source.btor2", "sha256": "a" * 64},
        "predicates": [{"form": "eq", "args": [ref("state5"), const(0, 8)]}],
        "origin": {
            "kind": "frozen-candidate-houdini",
            "artifacts": [{"path": "artifacts/source.jsonl", "sha256": "b" * 64}],
        },
    })


def map_document(source: dict) -> dict:
    parameters = {"offset": 1}
    return {
        "schema": transport_schema.MAP_SCHEMA,
        "source": source["source"],
        "target": {"benchmark_id": "transport/target.btor2", "sha256": "c" * 64},
        "transformation": {
            "family": "affine-recode",
            "version": 1,
            "seed": 11,
            "parameters": parameters,
            "parameters_sha256": transport_schema.canonical_sha256(parameters),
        },
        "projection": {"state5": {"form": "sub", "args": [ref("state9"), const(1, 8)]}},
        "input_map": {},
        "inverse_embedding": {"state9": {"form": "add", "args": [ref("state5"), const(1, 8)]}},
        "observation_predicate": None,
        "property_map": [{"source_bad_index": 0, "target_bad_index": 0}],
        "generated_map_invariants": [],
        "source_certificate_sha256": transport_schema.canonical_sha256(source),
        "generator_commit": "d" * 40,
        "validator_version_sha256": "e" * 64,
    }


def test_substitution_is_structural_and_does_not_rewrite_replacement():
    ast = {
        "form": "eq",
        "args": [ref("state5"), {"form": "add", "args": [ref("state6"), const(1, 8)]}],
    }
    result = transport_invariant.substitute_ast(ast, {
        "state5": {"form": "add", "args": [ref("state6"), const(2, 8)]},
        "state6": ref("state9"),
    })
    assert result["args"][0]["args"][0] == ref("state6")
    assert result["args"][1]["args"][0] == ref("state9")


def test_transport_document_requires_complete_ref_coverage():
    source = invariant_document()
    mapping = map_document(source)
    transported = transport_invariant.transport_document(source, mapping)
    assert transported["source"] == mapping["target"]
    assert transported["predicates"][0]["args"][0]["form"] == "sub"
    mapping["projection"] = {}
    with pytest.raises(ValueError, match="projection must not be empty"):
        transport_invariant.transport_document(source, mapping)


def test_exact_certification_checks_every_bad(tmp_path):
    model = tmp_path / "model.btor2"
    write_model(model, second_bad=True)
    report = transport_invariant.certify_predicates(
        model,
        [{"form": "eq", "args": [ref("state5"), const(0, 8)]}],
        timeout_ms=2000,
    )
    assert report["ok"] is True
    assert report["bad_count"] == 2
    assert [check["result"] for check in report["checks"]] == [
        "unsat", "unsat", "unsat", "unsat"
    ]


def test_false_candidate_is_rejected(tmp_path):
    model = tmp_path / "model.btor2"
    write_model(model)
    report = transport_invariant.certify_predicates(
        model,
        [{"form": "eq", "args": [ref("state5"), const(1, 8)]}],
        timeout_ms=2000,
    )
    assert report["ok"] is False
    assert report["checks"][0]["result"] == "sat"


def test_model_without_bad_is_rejected(tmp_path):
    model = tmp_path / "no-bad.btor2"
    write_model(model)
    model.write_text("\n".join(
        line for line in model.read_text().splitlines() if " bad " not in line
    ) + "\n")
    with pytest.raises(ValueError, match="no bad property"):
        transport_invariant.certify_predicates(
            model,
            [{"form": "eq", "args": [ref("state5"), const(0, 8)]}],
            timeout_ms=2000,
        )


def test_pono_invariant_conversion_supports_let_bvcomp_and_ite(tmp_path):
    model = tmp_path / "model.btor2"
    write_model(model)
    output = (
        "INVAR: (let ((_let0 (= state5 #x00))) "
        "(and _let0 (= (bvcomp state5 (ite _let0 #x00 #x01)) #b1)))\n"
        "unsat\n"
    )
    ast = transport_invariant.pono_invariant_to_ast(model, output)
    forms = []
    stack = [ast]
    while stack:
        node = stack.pop()
        forms.append(node["form"])
        stack.extend(node.get("args", []))
    assert "bvcomp" in forms
    assert "ite" in forms
    report = transport_invariant.certify_predicates(model, [ast], timeout_ms=2000)
    assert report["ok"] is True


def test_pono_conversion_rejects_multiple_invariant_lines(tmp_path):
    model = tmp_path / "model.btor2"
    write_model(model)
    with pytest.raises(ValueError, match="exactly one INVAR"):
        transport_invariant.pono_invariant_to_ast(
            model,
            "INVAR: (= state5 #x00)\nINVAR: (= state5 #x00)\n",
        )


def test_ast_node_limit_is_enforced():
    import z3

    values = [z3.Bool(f"state{i}") for i in range(10)]
    expression = z3.And(*values)
    with pytest.raises(ValueError, match="exceeds 5 AST nodes"):
        transport_invariant.z3_to_ast(expression, max_nodes=5)


def test_transform_applicability_requires_frozen_structural_features(tmp_path):
    model = tmp_path / "coupled.btor2"
    model.write_text("\n".join([
        "1 sort bitvec 8",
        "2 sort bitvec 1",
        "3 state 1 x",
        "4 state 1 y",
        "5 input 1 u",
        "6 add 1 4 5",
        "7 add 1 3 5",
        "8 next 1 3 6",
        "9 next 1 4 7",
        "10 zero 1",
        "11 eq 2 3 10",
        "12 bad 11",
    ]) + "\n")
    predicates = [{"form": "eq", "args": [ref("state3"), const(0, 8)]}]
    applicability = build_transport_population._applicability(model, predicates)
    assert applicability["T1"]["applicable"] is True
    assert applicability["T1"]["candidate_groups"] == [
        {"width": 8, "state_refs": ["state3", "state4"]}
    ]
    assert applicability["T2"]["applicable"] is True
    assert applicability["T3"]["applicable"] is True
    assert applicability["T3"]["input_driven"] is True


def test_phase_class_is_distinct_from_syntactic_conjunction():
    affine = {"form": "eq", "args": [ref("state5"), const(0, 8)]}
    guarded = {
        "form": "implies",
        "args": [
            {"form": "eq", "args": [ref("state6"), const(1, 8)]},
            affine,
        ],
    }
    assert build_transport_population._invariant_classes([affine, affine]) == [
        "affine-relational",
        "conjunctive",
    ]
    assert build_transport_population._invariant_classes([guarded]) == [
        "affine-relational",
        "phase-guarded",
    ]


def test_phase_report_replay_preserves_requested_symbols(tmp_path):
    model = tmp_path / "model.btor2"
    write_model(model)
    original = {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "constants": [0, 1],
        }],
    }
    original_routes, _, original_entries = run_phase_grammar.prepare_entries(
        str(model), original, phase_mode="global", cap=20
    )
    report_routes = json.loads(
        grammar_routes.canonical_route_document(original_routes)
    )["routes"]
    replay_payload = build_transport_population._phase_route_payload({
        "routes": report_routes
    })
    replay_routes, _, replay_entries = run_phase_grammar.prepare_entries(
        str(model), replay_payload, phase_mode="global", cap=20
    )
    assert replay_routes == original_routes
    assert replay_entries == original_entries
    assert replay_routes[0].requested_variables == ("x",)


def test_phase_report_replay_rejects_incomplete_canonical_route():
    route = {
        "variables": ["state5"],
        "family": "unary",
        "relations": ["eq"],
        "signedness": "unsigned",
        "constants": [0],
        "width": 8,
        "route_id": "a" * 64,
    }
    with pytest.raises(ValueError, match="requested_variables"):
        build_transport_population._phase_route_payload({"routes": [route]})


def test_representation_integrity_requires_self_hash_and_summary_link(tmp_path):
    (tmp_path / "summary.json").write_text("{}\n")
    (tmp_path / "evidence.txt").write_text("evidence\n")
    files = [
        {
            "path": name,
            "sha256": transport_schema.file_sha256(tmp_path / name),
        }
        for name in ("evidence.txt", "summary.json")
    ]
    document = {
        "schema": "pono-llm-representation-phase-artifact-integrity-v1",
        "status": "completed",
        "summary_sha256": transport_schema.file_sha256(tmp_path / "summary.json"),
        "files": files,
    }
    document["integrity_sha256"] = transport_schema.canonical_sha256(document)
    (tmp_path / "integrity.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    verified, path = build_transport_population._verify_integrity(tmp_path)
    assert path == tmp_path / "integrity.json"
    assert verified["summary.json"] == document["summary_sha256"]

    (tmp_path / "evidence.txt").write_text("tampered\n")
    with pytest.raises(ValueError, match="integrity mismatch"):
        build_transport_population._verify_integrity(tmp_path)


def test_show_invar_asan_address_limit_failure_is_deterministic():
    reason, error = build_transport_population._classify_show_invar_failure(
        b"==1371347==ERROR: AddressSanitizer failed to allocate shadow\n"
        b"==1371347==ReserveShadowMemoryRange failed\n"
    )

    assert reason == "show-invar-runtime-incompatible"
    assert "1371347" not in error
    assert error.count("==PID==") == 2
