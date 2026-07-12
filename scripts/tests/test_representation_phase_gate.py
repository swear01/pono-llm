from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import grammar_routes  # noqa: E402
import run_phase_grammar  # noqa: E402
import build_paired_corpus  # noqa: E402
import representation_views  # noqa: E402
import capture_grammar_routes  # noqa: E402
import audit_frozen_routes  # noqa: E402
import run_routed_phase_matrix  # noqa: E402


def write_scalar_model(path: Path, *, duplicate_symbol: bool = False) -> None:
    y_symbol = "x" if duplicate_symbol else "y"
    path.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 zero 1",
            "4 zero 2",
            "5 state 1 x",
            f"6 state 1 {y_symbol}",
            "7 state 1 z",
            "8 init 1 5 3",
            "9 init 1 6 3",
            "10 init 1 7 3",
            "11 next 1 5 5",
            "12 next 1 6 6",
            "13 next 1 7 7",
            "14 eq 2 5 3",
            "15 bad 14",
        ])
        + "\n"
    )


def write_functional_pc_model(path: Path, *, second_pc: bool = False) -> None:
    lines = [
        "1 sort bitvec 3",
        "2 sort bitvec 1",
        "3 sort bitvec 8",
        "4 const 1 001",
        "5 const 1 010",
        "6 const 1 100",
        "7 state 1 !pc",
        "8 eq 2 7 4",
        "9 eq 2 7 5",
        "10 eq 2 7 6",
        "11 zero 3",
        "12 one 3",
        "13 state 3 x",
        "14 add 3 13 12",
        "15 ite 3 8 14 13",
        "16 next 3 13 15",
        "17 ite 1 8 5 6",
        "18 next 1 7 17",
        "19 init 1 7 4",
        "20 init 3 13 11",
        "21 constraint -10",
        "22 bad 9",
    ]
    if second_pc:
        lines.insert(11, "23 state 1 !pc")
        lines.append("24 next 1 23 23")
    path.write_text("\n".join(lines) + "\n")


def write_phase_certificate_model(path: Path, *, safe: bool) -> None:
    x_next = "11" if safe else "10"
    path.write_text(
        "\n".join([
            "1 sort bitvec 3",
            "2 sort bitvec 1",
            "3 const 1 001",
            "4 const 1 010",
            "5 const 1 100",
            "6 state 1 !pc",
            "7 eq 2 6 3",
            "8 eq 2 6 4",
            "9 eq 2 6 5",
            "10 zero 2",
            "11 one 2",
            "12 state 2 x",
            "13 next 1 6 4",
            "14 init 1 6 3",
            f"15 next 2 12 {x_next}",
            "16 init 2 12 10",
            "17 eq 2 12 10",
            "18 and 2 8 17",
            "19 bad 18",
        ])
        + "\n"
    )


def write_paired_model(path: Path) -> None:
    path.write_text(
        "\n".join([
            "1 sort bitvec 3",
            "2 sort bitvec 1",
            "3 sort bitvec 8",
            "4 const 1 001",
            "5 const 1 010",
            "6 state 1 !pc",
            "7 eq 2 6 4",
            "8 eq 2 6 5",
            "9 zero 3",
            "10 state 3 x",
            "11 state 3 y",
            "12 next 1 6 5",
            "13 init 1 6 4",
            "14 next 3 10 10",
            "15 init 3 10 9",
            "16 next 3 11 11",
            "17 init 3 11 9",
            "18 bad 8",
        ])
        + "\n"
    )


def route_payload(**updates) -> dict:
    route = {
        "variables": ["x", "y"],
        "family": "pairwise_offset",
        "relations": ["eq"],
        "signedness": "unsigned",
        "offsets": [0, 1],
    }
    route.update(updates)
    return {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [route],
    }


def test_route_schema_rejects_unknown_top_level_field(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload()
    payload["fallback"] = True
    with pytest.raises(ValueError, match="unknown fields"):
        grammar_routes.compile_route_document(str(circuit), payload)


def test_route_schema_rejects_unknown_route_field(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload(temperature=0.2)
    with pytest.raises(ValueError, match="unknown route fields"):
        grammar_routes.compile_route_document(str(circuit), payload)


def test_symbol_and_state_ref_have_same_route_identity(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    by_symbol = grammar_routes.compile_route_document(
        str(circuit), route_payload()
    )
    by_ref = grammar_routes.compile_route_document(
        str(circuit), route_payload(variables=["state5", "state6"])
    )
    assert by_symbol[0].route_id == by_ref[0].route_id
    assert by_symbol[0].variables == ("state5", "state6")


def test_ambiguous_symbol_is_rejected(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit, duplicate_symbol=True)
    payload = route_payload(variables=["x", "state7"])
    with pytest.raises(ValueError, match="ambiguous state symbol"):
        grammar_routes.compile_route_document(str(circuit), payload)


def test_family_rejects_wrong_variable_count(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload(
        family="quadratic_recurrence",
        variables=["x", "y", "z"],
        scales=[2],
        counter_shifts=[-1],
    )
    payload["routes"][0].pop("offsets")
    with pytest.raises(ValueError, match="exactly 2 variables"):
        grammar_routes.compile_route_document(str(circuit), payload)


def test_irrelevant_family_field_is_rejected(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload(scales=[2])
    with pytest.raises(ValueError, match="does not allow fields"):
        grammar_routes.compile_route_document(str(circuit), payload)


def test_pairwise_route_expands_deterministically(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    routes = grammar_routes.compile_route_document(
        str(circuit), route_payload()
    )
    first = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    second = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    assert first == second
    assert len(first) == 2
    assert first[0]["template_family"] == "pairwise_offset"
    assert first[0]["predicate_ast"] == {
        "form": "eq",
        "args": [
            {"form": "ref", "ref": "state5"},
            {
                "form": "add",
                "args": [
                    {"form": "ref", "ref": "state6"},
                    {"form": "const", "const": "0", "width": 8},
                ],
            },
        ],
    }


def test_bounded_exhaustive_routes_are_deterministic_and_width_safe(tmp_path):
    variables = [
        {"state_ref": "state7", "width": 8},
        {"state_ref": "state5", "width": 8},
        {"state_ref": "state6", "width": 16},
    ]
    first = grammar_routes.bounded_exhaustive_route_document(variables)
    second = grammar_routes.bounded_exhaustive_route_document(variables)
    assert first == second
    assert first["schema"] == grammar_routes.ROUTE_SCHEMA
    unary_refs = []
    for route in first["routes"]:
        if route["family"] == "unary" and route["variables"] not in unary_refs:
            unary_refs.append(route["variables"])
    assert unary_refs == [
        ["state5"],
        ["state6"],
        ["state7"],
    ]
    multi_variable_routes = [
        route for route in first["routes"] if len(route["variables"]) > 1
    ]
    assert multi_variable_routes
    assert all("state6" not in route["variables"] for route in multi_variable_routes)


def test_structural_router_is_deterministic_and_budgeted(tmp_path):
    circuit = tmp_path / "pair.btor2"
    write_paired_model(circuit)
    variables = [
        {"state_ref": "state10", "width": 8},
        {"state_ref": "state11", "width": 8},
    ]
    first, first_diagnostics = grammar_routes.structural_route_document(
        str(circuit), variables, max_routes=8
    )
    second, second_diagnostics = grammar_routes.structural_route_document(
        str(circuit), variables, max_routes=8
    )
    assert first == second
    assert first_diagnostics == second_diagnostics
    assert 1 <= len(first["routes"]) <= 8
    grammar_routes.compile_route_document(str(circuit), first)


def test_signed_relation_compiles_to_signed_bv_compare(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload(
        relations=["le"], signedness="signed", offsets=[0]
    )
    routes = grammar_routes.compile_route_document(str(circuit), payload)
    entries = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    assert entries[0]["predicate_ast"]["form"] == "sle"


def test_quadratic_route_uses_ordered_accumulator_and_counter(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    payload = route_payload(
        family="quadratic_recurrence",
        variables=["x", "y"],
        scales=[2],
        counter_shifts=[-1],
    )
    payload["routes"][0].pop("offsets")
    routes = grammar_routes.compile_route_document(str(circuit), payload)
    entries = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    assert entries == [{
        "predicate_ast": {
            "form": "eq",
            "args": [
                {
                    "form": "mul",
                    "args": [
                        {"form": "const", "const": "2", "width": 8},
                        {"form": "ref", "ref": "state5"},
                    ],
                },
                {
                    "form": "mul",
                    "args": [
                        {"form": "ref", "ref": "state6"},
                        {
                            "form": "sub",
                            "args": [
                                {"form": "ref", "ref": "state6"},
                                {"form": "const", "const": "1", "width": 8},
                            ],
                        },
                    ],
                },
            ],
        },
        "route_id": routes[0].route_id,
        "template_family": "quadratic_recurrence",
        "phase_id": None,
        "provenance": {
            "requested_variables": ["x", "y"],
            "variables": ["state5", "state6"],
            "width": 8,
            "signedness": "unsigned",
        },
    }]


def test_expansion_cap_is_strict_and_positive(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    routes = grammar_routes.compile_route_document(
        str(circuit), route_payload(relations=["eq", "le", "ge"])
    )
    assert len(grammar_routes.expand_routes(str(circuit), routes, cap=2)) == 2
    with pytest.raises(ValueError, match="cap must be positive"):
        grammar_routes.expand_routes(str(circuit), routes, cap=0)


def test_route_document_round_trip_is_canonical(tmp_path):
    circuit = tmp_path / "model.btor2"
    write_scalar_model(circuit)
    routes = grammar_routes.compile_route_document(
        str(circuit), route_payload(relations=["ge", "eq", "le"])
    )
    encoded = grammar_routes.canonical_route_document(routes)
    decoded = json.loads(encoded)
    assert decoded["routes"][0]["relations"] == ["eq", "le", "ge"]
    assert decoded["routes"][0]["route_id"] == routes[0].route_id


def test_extract_functional_pc_phases(tmp_path):
    circuit = tmp_path / "pc.btor2"
    write_functional_pc_model(circuit)
    phases = grammar_routes.extract_functional_phases(str(circuit))
    assert [(phase.value, phase.is_initial, phase.is_bad) for phase in phases] == [
        (1, True, False),
        (2, False, True),
        (4, False, False),
    ]
    assert phases[0].phase_id == "pc_state7_w3_v1"
    assert phases[0].guard_ast == {
        "form": "eq",
        "args": [
            {"form": "ref", "ref": "state7"},
            {"form": "const", "const": "1", "width": 3},
        ],
    }


def test_extract_functional_pc_rejects_ambiguous_pc(tmp_path):
    circuit = tmp_path / "pc.btor2"
    write_functional_pc_model(circuit, second_pc=True)
    with pytest.raises(ValueError, match="exactly one !pc state"):
        grammar_routes.extract_functional_phases(str(circuit))


def test_all_phase_mode_wraps_every_candidate(tmp_path):
    circuit = tmp_path / "pc.btor2"
    write_functional_pc_model(circuit)
    payload = {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "constants": [0],
        }],
    }
    routes = grammar_routes.compile_route_document(str(circuit), payload)
    global_entries = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    phases = grammar_routes.extract_functional_phases(str(circuit))
    guarded = grammar_routes.apply_phase_mode(
        global_entries, phases, mode="all", cap=20
    )
    assert len(global_entries) == 1
    assert len(guarded) == 3
    assert [entry["phase_id"] for entry in guarded] == [
        "pc_state7_w3_v1",
        "pc_state7_w3_v2",
        "pc_state7_w3_v4",
    ]
    assert guarded[0]["predicate_ast"] == {
        "form": "implies",
        "args": [phases[0].guard_ast, global_entries[0]["predicate_ast"]],
    }


def test_global_phase_mode_preserves_entries(tmp_path):
    circuit = tmp_path / "pc.btor2"
    write_functional_pc_model(circuit)
    payload = {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "constants": [0],
        }],
    }
    routes = grammar_routes.compile_route_document(str(circuit), payload)
    entries = grammar_routes.expand_routes(str(circuit), routes, cap=20)
    assert grammar_routes.apply_phase_mode(
        entries, [], mode="global", cap=20
    ) == entries


def test_phase_mode_rejects_unknown_mode(tmp_path):
    circuit = tmp_path / "pc.btor2"
    write_functional_pc_model(circuit)
    with pytest.raises(ValueError, match="phase mode"):
        grammar_routes.apply_phase_mode([], [], mode="guess", cap=1)


def unary_one_route() -> dict:
    return {
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "constants": [1],
        }],
    }


def test_phase_guarded_certificate_succeeds_when_global_fails(tmp_path):
    circuit = tmp_path / "safe.btor2"
    write_phase_certificate_model(circuit, safe=True)
    _, _, global_entries = run_phase_grammar.prepare_entries(
        str(circuit), unary_one_route(), phase_mode="global", cap=20
    )
    _, _, phase_entries = run_phase_grammar.prepare_entries(
        str(circuit), unary_one_route(), phase_mode="all", cap=20
    )
    global_report, _ = run_phase_grammar.certify_entries(
        str(circuit), global_entries, 5000
    )
    phase_report, _ = run_phase_grammar.certify_entries(
        str(circuit), phase_entries, 5000
    )
    assert not global_report["ok"]
    assert phase_report["ok"]
    assert phase_report["checks"] == [
        {"name": "C1 Init=>H", "result": "unsat"},
        {"name": "C2 inductive", "result": "unsat"},
        {"name": "C3 H=>notBAD", "result": "unsat"},
    ]


def test_phase_guard_does_not_certify_unsafe_model(tmp_path):
    circuit = tmp_path / "unsafe.btor2"
    write_phase_certificate_model(circuit, safe=False)
    _, _, entries = run_phase_grammar.prepare_entries(
        str(circuit), unary_one_route(), phase_mode="all", cap=20
    )
    report, _ = run_phase_grammar.certify_entries(
        str(circuit), entries, 5000
    )
    assert not report["ok"]
    checks = {check["name"]: check["result"] for check in report["checks"]}
    assert checks["C3 H=>notBAD"] == "sat"


def test_direct_phase_run_records_original_model_certificate(tmp_path):
    circuit = tmp_path / "safe.btor2"
    write_phase_certificate_model(circuit, safe=True)
    report = run_phase_grammar.run_gate(
        str(circuit),
        unary_one_route(),
        phase_mode="all",
        cap=20,
        cert_timeout_ms=5000,
        pono_timeout=5.0,
        max_refinements=0,
    )
    assert report["schema"] == run_phase_grammar.REPORT_SCHEMA
    assert report["verdict"] == "unsat"
    assert report["engine"] == "phase-grammar-certificate"
    assert report["certificate"]["ok"]
    assert len(report["benchmark_sha256"]) == 64


def test_paired_yaml_parser_is_strict(tmp_path):
    yaml_path = tmp_path / "task.yml"
    yaml_path.write_text(
        "format_version: '2.0'\n"
        "input_files: 'task.c'\n"
        "properties:\n"
        "- expected_verdict: true\n"
        "  property_file: ../properties/unreach-call.prp\n"
    )
    assert build_paired_corpus.parse_single_input_file(yaml_path) == "task.c"
    assert build_paired_corpus.parse_translated_property(yaml_path) == (True, 1)
    yaml_path.write_text("input_files:\n  - one.c\n  - two.c\n")
    with pytest.raises(ValueError, match="one inline input_files scalar"):
        build_paired_corpus.parse_single_input_file(yaml_path)


def test_source_family_normalization_is_explicit(tmp_path):
    family, family_id, rules = build_paired_corpus.source_family(
        "loop-invgen", tmp_path / "apache.i.p+lhb-reducer.yml"
    )
    assert family == "loop-invgen/apache"
    assert len(family_id) == 64
    assert rules == ["reducer-variant"]
    family, _, rules = build_paired_corpus.source_family(
        "nla-digbench", tmp_path / "geo1-u.yml"
    )
    assert family == "nla-digbench/geo1"
    assert rules == ["nla-verdict-variant"]


def test_paired_task_records_source_target_mapping_and_phases(tmp_path):
    translation_root = tmp_path / "translation" / "translated" / "safety-func"
    source_root = tmp_path / "source" / "c"
    translated_dir = translation_root / "loop-simple"
    source_dir = source_root / "loop-simple"
    translated_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    btor2 = translated_dir / "pair.btor2"
    write_paired_model(btor2)
    (translated_dir / "pair.yml").write_text(
        "format_version: '2.0'\n"
        "input_files: pair.btor2\n"
        "properties:\n"
        "- expected_verdict: true\n"
        "  property_file: ../properties/unreach-call.prp\n"
    )
    (source_dir / "pair.yml").write_text(
        "format_version: '2.0'\ninput_files: 'pair.c'\n"
    )
    (source_dir / "pair.c").write_text(
        "int main(void) { unsigned x = 0, y = 0; return x == y; }\n"
    )
    task = build_paired_corpus.build_task_record(
        btor2, translation_root, source_root
    )
    assert task["eligible"] is True
    assert task["expected_verdict"] == "safe"
    assert task["source_family_key"] == "loop-simple/pair"
    assert [row["source_name"] for row in task["source_state_mapping"]] == [
        "x",
        "y",
    ]
    assert [phase["value"] for phase in task["phases"]] == [1, 2]

    raw = representation_views.render_raw(btor2, {
        "source_state_mapping": task["source_state_mapping"],
        "phases": task["phases"],
    })
    assert "REPRESENTATION: RAW BTOR2" in raw
    assert "18 bad 8" in raw
    assert "13 init 1 6 4" in raw
    lifted = representation_views.render_lifted(btor2, {
        "source_state_mapping": task["source_state_mapping"],
        "phases": task["phases"],
    })
    assert "TARGET-DERIVED LIFTED RECURRENCE" in lifted
    assert "x' = x" in lifted


def test_lexical_truncation_is_deterministic_and_bounded():
    text = " ".join(f"token{i}" for i in range(100))
    first, first_truncated = representation_views.truncate_lexically(text, 20)
    second, second_truncated = representation_views.truncate_lexically(text, 20)
    assert first == second
    assert first_truncated and second_truncated
    assert representation_views.lexical_token_count(first) <= 20
    assert "deterministic middle truncation" in first


def test_route_capture_validation_is_strict_and_counts_phases(tmp_path):
    circuit = tmp_path / "pair.btor2"
    write_paired_model(circuit)
    response = json.dumps({
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "constants": [0],
        }],
    })
    canonical, error, global_count, all_phase_count = (
        capture_grammar_routes.parse_and_validate_route(response, circuit, 2)
    )
    assert error == ""
    assert canonical is not None
    assert global_count == 1
    assert all_phase_count == 2
    invalid = json.dumps({
        "schema": grammar_routes.ROUTE_SCHEMA,
        "routes": [{
            "variables": ["x"],
            "family": "unary",
            "relations": ["eq"],
            "signedness": "unsigned",
            "fallback": True,
        }],
    })
    canonical, error, _, _ = capture_grammar_routes.parse_and_validate_route(
        invalid, circuit, 2
    )
    assert canonical is None
    assert "unknown route fields" in error


def test_frozen_route_audit_normalizes_semantic_noops():
    direct = {
        "form": "ule",
        "args": [
            {"form": "ref", "ref": "state5"},
            {"form": "ref", "ref": "state6"},
        ],
    }
    routed = {
        "form": "uge",
        "args": [
            {
                "form": "add",
                "args": [
                    {"form": "ref", "ref": "state6"},
                    {"form": "const", "const": "0", "width": 8},
                ],
            },
            {
                "form": "mul",
                "args": [
                    {"form": "const", "const": "1", "width": 8},
                    {"form": "ref", "ref": "state5"},
                ],
            },
        ],
    }
    assert audit_frozen_routes.semantic_ast_key(direct) == (
        audit_frozen_routes.semantic_ast_key(routed)
    )


def test_random_budget_route_is_deterministic(tmp_path):
    circuit = tmp_path / "pair.btor2"
    write_paired_model(circuit)
    variables = [
        {"state_ref": "state10", "width": 8},
        {"state_ref": "state11", "width": 8},
    ]
    first, first_diagnostics = run_routed_phase_matrix.random_budget_route_document(
        circuit, variables, "loop-simple/pair.btor2", "source", 20
    )
    second, second_diagnostics = run_routed_phase_matrix.random_budget_route_document(
        circuit, variables, "loop-simple/pair.btor2", "source", 20
    )
    assert first == second
    assert first_diagnostics == second_diagnostics
    assert first["routes"]
    grammar_routes.compile_route_document(str(circuit), first)
