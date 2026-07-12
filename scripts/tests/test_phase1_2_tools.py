from __future__ import annotations

import hashlib
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import z3

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import candidate_cert_check  # noqa: E402
import capture_candidates  # noqa: E402
import experiment_manifest  # noqa: E402
import hash_research_artifacts  # noqa: E402
import run_matrix  # noqa: E402
import static_predicate_baseline  # noqa: E402
import summarize_phase1_2  # noqa: E402
import summarize_reliability  # noqa: E402


def write_btor2(path: Path, *, multiple_bad: bool = False) -> None:
    lines = [
        "1 sort bitvec 1",
        "2 zero 1",
        "3 one 1",
        "4 state 1 x",
        "5 init 1 4 2",
        "6 next 1 4 4",
        "7 eq 1 4 2",
        "8 eq 1 4 3",
    ]
    if multiple_bad:
        lines += ["9 bad 7", "10 bad 8"]
    else:
        lines += ["9 bad 8"]
    path.write_text("\n".join(lines) + "\n")


def predicate(form: str, lhs: dict, rhs: dict) -> dict:
    return {"predicate_ast": {"form": form, "args": [lhs, rhs]}}


def ref(name: str) -> dict:
    return {"form": "ref", "ref": name}


def const(value: int, width: int) -> dict:
    return {"form": "const", "const": str(value), "width": width}


def write_legacy_capture_bundle(
    directory: Path,
    benchmark: experiment_manifest.BenchmarkSpec,
    entries: list[dict],
    *,
    latency_sec: float = 0.0,
) -> dict:
    slug = experiment_manifest.stable_slug(benchmark.benchmark_id)
    predicate_file = f"{slug}.jsonl"
    metadata_file = f"{slug}.meta.json"
    prompt_file = f"{slug}.prompt.txt"
    predicate_text = "\n".join(json.dumps(entry) for entry in entries)
    if predicate_text:
        predicate_text += "\n"
    prompt_text = "frozen test prompt\n"
    (directory / predicate_file).write_text(predicate_text)
    (directory / prompt_file).write_text(prompt_text)
    meta = {
        "schema": "pono-llm-candidate-meta-v2-migrated",
        "benchmark_id": benchmark.benchmark_id,
        "slug": slug,
        "predicates_file": predicate_file,
        "predicates_sha256": hashlib.sha256(predicate_text.encode()).hexdigest(),
        "prompt_file": prompt_file,
        "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
        "responses_file": None,
        "rounds": 1,
        "llm_calls": [{"round": 0, "response_sha256": None}],
        "dedup_candidate_count": len(entries),
        "linear_candidate_count": len(entries),
        "latency_sec": latency_sec,
        "provider": "test-provider",
        "model": "test-model",
        "total_tokens": 123,
        "legacy_metadata_incomplete": True,
    }
    (directory / metadata_file).write_text(json.dumps(meta))
    manifest = {
        "schema": "pono-llm-candidate-capture-v2-migrated",
        "benchmarks": [{
            "benchmark_id": benchmark.benchmark_id,
            "slug": slug,
            "predicates_file": predicate_file,
            "metadata_file": metadata_file,
            "prompt_file": prompt_file,
            "responses_file": None,
        }],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    digest = experiment_manifest.file_sha256(benchmark.path)
    experiment_manifest.write_capture_integrity(
        directory,
        {benchmark.benchmark_id: digest},
        recorded_after_capture=True,
    )
    return experiment_manifest.validate_capture_bundle(directory, [benchmark])


def test_stable_slug_is_independent_of_root(tmp_path):
    first_root = tmp_path / "root-a"
    second_root = tmp_path / "root-b"
    relative = Path("2025/set/example.btor2")
    for root in (first_root, second_root):
        (root / relative).parent.mkdir(parents=True)
        (root / relative).write_text("")
    first = experiment_manifest.make_spec(first_root / relative, first_root)
    second = experiment_manifest.make_spec(second_root / relative, second_root)
    assert first.benchmark_id == second.benchmark_id == relative.as_posix()
    assert experiment_manifest.stable_slug(first.benchmark_id) == (
        experiment_manifest.stable_slug(second.benchmark_id)
    )


def test_manifest_explicit_id_can_reference_external_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    external = tmp_path / "external.btor2"
    external.write_text("")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        f"benchmark_id,path\ncustom/external.btor2,{external}\n"
    )
    specs = experiment_manifest.load_manifest(manifest, root)
    assert specs == [
        experiment_manifest.BenchmarkSpec("custom/external.btor2", external)
    ]


def test_manifest_csv_ignores_leading_comments(tmp_path):
    root = tmp_path / "root"
    circuit = root / "suite" / "example.btor2"
    circuit.parent.mkdir(parents=True)
    circuit.write_text("")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "# frozen sample\nbenchmark_id,path\nsuite/example.btor2,suite/example.btor2\n"
    )
    assert experiment_manifest.load_manifest(manifest, root) == [
        experiment_manifest.BenchmarkSpec("suite/example.btor2", circuit)
    ]


def test_manifest_preserves_and_verifies_content_hash(tmp_path):
    root = tmp_path / "root"
    circuit = root / "suite" / "example.btor2"
    circuit.parent.mkdir(parents=True)
    circuit.write_text("original\n")
    digest = hashlib.sha256(circuit.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": "suite/example.btor2",
            "content_sha256": digest,
        }]
    }))
    spec = experiment_manifest.load_manifest(manifest, root)[0]
    assert spec.content_sha256 == digest
    assert experiment_manifest.verify_benchmark_content(spec) == digest
    circuit.write_text("changed\n")
    with pytest.raises(ValueError, match="content hash mismatch"):
        experiment_manifest.verify_benchmark_content(spec)


def test_zero_round_capture_uses_portable_metadata(tmp_path):
    circuit = tmp_path / "capture.btor2"
    write_btor2(circuit)
    output = tmp_path / "capture"
    output.mkdir()

    class NoClient:
        def call(self, *args, **kwargs):
            raise AssertionError("rounds=0 must not call the client")

    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/capture.btor2", circuit
    )
    meta = capture_candidates.capture_one(
        benchmark, output, NoClient(), rounds=0, effort="none", cap=20
    )
    assert meta["benchmark_id"] == "suite/capture.btor2"
    assert "path" not in meta
    assert Path(meta["prompt_file"]).is_absolute() is False
    assert meta["predicates_sha256"] == hashlib.sha256(b"").hexdigest()
    assert meta["schema"] == "pono-llm-candidate-meta-v4"
    assert meta["benchmark_content_sha256"] == hashlib.sha256(
        circuit.read_bytes()
    ).hexdigest()
    assert meta["status"] == "completed"
    assert (output / meta["responses_file"]).read_text() == ""
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["system_prompt_sha256"] == hashlib.sha256(
        (output / "system_prompt.txt").read_bytes()
    ).hexdigest()
    assert provenance["source_sha256"]["scripts/capture_candidates.py"]


def test_capture_main_finalizes_v4_integrity(tmp_path, monkeypatch):
    root = tmp_path / "benchmarks"
    circuit = root / "suite" / "capture.btor2"
    circuit.parent.mkdir(parents=True)
    write_btor2(circuit)
    digest = hashlib.sha256(circuit.read_bytes()).hexdigest()
    manifest = tmp_path / "input.json"
    manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": "suite/capture.btor2",
            "content_sha256": digest,
        }]
    }))
    output = tmp_path / "capture-v4"
    monkeypatch.setattr(sys, "argv", [
        "capture_candidates.py",
        "--benchmark-root", str(root),
        "--manifest", str(manifest),
        "--out", str(output),
        "--rounds", "0",
    ])
    assert capture_candidates.main() == 0
    capture_manifest = json.loads((output / "manifest.json").read_text())
    assert capture_manifest["schema"] == "pono-llm-candidate-capture-v4"
    assert capture_manifest["integrity_file"] == "integrity.json"
    spec = experiment_manifest.load_manifest(manifest, root)[0]
    bundle = experiment_manifest.validate_capture_bundle(output, [spec])
    assert bundle["integrity"]["recorded_after_capture"] is False


def test_capture_persists_completed_round_before_api_failure(tmp_path):
    circuit = tmp_path / "partial.btor2"
    write_btor2(circuit)
    output = tmp_path / "partial"
    output.mkdir()

    class FailingClient:
        provider = "test-provider"
        model_name = "test-model"
        last_call_stats = {"provider": "test-provider"}

        def __init__(self):
            self.calls = 0

        def call(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("injected API failure")
            return json.dumps({
                "candidates": [{
                    "id": 1,
                    "kind": "Type1_invariant",
                    "predicate_ast": {
                        "form": "eq",
                        "args": [ref("state4"), const(0, 1)],
                    },
                }]
            }), 17, 12.0

    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/partial.btor2", circuit
    )
    with pytest.raises(RuntimeError, match="injected API failure"):
        capture_candidates.capture_one(
            benchmark, output, FailingClient(), rounds=2, effort="none", cap=20
        )

    slug = experiment_manifest.stable_slug(benchmark.benchmark_id)
    meta = json.loads((output / f"{slug}.meta.json").read_text())
    assert meta["status"] == "in_progress"
    assert len(meta["llm_calls"]) == 1
    assert meta["dedup_candidate_count"] == 1
    assert len((output / f"{slug}.responses.jsonl").read_text().splitlines()) == 1


def test_capture_integrity_rejects_tampered_predicates(tmp_path):
    circuit = tmp_path / "integrity.btor2"
    write_btor2(circuit)
    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/integrity.btor2", circuit
    )
    bundle = write_legacy_capture_bundle(
        tmp_path,
        benchmark,
        [predicate("eq", ref("state4"), const(0, 1))],
    )
    assert bundle["records"][benchmark.benchmark_id]["content_sha256"] == (
        hashlib.sha256(circuit.read_bytes()).hexdigest()
    )
    predicate_path = bundle["records"][benchmark.benchmark_id]["predicate_path"]
    predicate_path.write_text(predicate_path.read_text() + "{}\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        experiment_manifest.validate_capture_bundle(tmp_path, [benchmark])


def test_capture_archive_rejects_tampered_metadata(tmp_path):
    circuit = tmp_path / "metadata-integrity.btor2"
    write_btor2(circuit)
    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/metadata-integrity.btor2", circuit
    )
    bundle = write_legacy_capture_bundle(
        tmp_path,
        benchmark,
        [predicate("eq", ref("state4"), const(0, 1))],
    )
    metadata_path = tmp_path / bundle["records"][benchmark.benchmark_id][
        "entry"
    ]["metadata_file"]
    metadata = json.loads(metadata_path.read_text())
    metadata["total_tokens"] += 1
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="metadata_file hash mismatch"):
        experiment_manifest.validate_capture_archive(tmp_path)


def test_capture_v4_requires_native_global_provenance(tmp_path, monkeypatch):
    root = tmp_path / "benchmarks"
    circuit = root / "suite" / "capture.btor2"
    circuit.parent.mkdir(parents=True)
    write_btor2(circuit)
    digest = hashlib.sha256(circuit.read_bytes()).hexdigest()
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": "suite/capture.btor2",
            "content_sha256": digest,
        }]
    }))
    output = tmp_path / "capture-v4"
    monkeypatch.setattr(sys, "argv", [
        "capture_candidates.py",
        "--benchmark-root", str(root),
        "--manifest", str(input_manifest),
        "--out", str(output),
        "--rounds", "0",
    ])
    assert capture_candidates.main() == 0
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["provenance_file"]
    manifest_path.write_text(json.dumps(manifest))
    experiment_manifest.write_capture_integrity(
        output,
        {"suite/capture.btor2": digest},
        recorded_after_capture=False,
    )
    with pytest.raises(ValueError, match="must declare provenance_file"):
        experiment_manifest.validate_capture_archive(output)


def test_replay_matrix_contract_rejects_partial_coverage():
    hashes = {"a.btor2": "a" * 64, "b.btor2": "b" * 64}
    contract = experiment_manifest.replay_matrix_contract(
        hashes, ["baseline"], 1
    )
    rows = [{
        "trial": "0",
        "benchmark_id": "a.btor2",
        "benchmark_content_sha256": hashes["a.btor2"],
        "benchmark_manifest_sha256": "c" * 64,
        "config": "baseline",
        **contract,
    }]
    with pytest.raises(ValueError, match="does not satisfy"):
        experiment_manifest.validate_replay_matrix(
            rows,
            hashes,
            ["baseline"],
            1,
            benchmark_manifest_sha256="c" * 64,
        )


def test_balanced_static_cap_reaches_every_family(tmp_path):
    circuit = tmp_path / "three.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 zero 1",
            "4 state 1 x",
            "5 state 1 y",
            "6 state 1 z",
            "7 init 1 4 3",
            "8 init 1 5 3",
            "9 init 1 6 3",
            "10 next 1 4 4",
            "11 next 1 5 5",
            "12 next 1 6 6",
            "13 eq 2 4 5",
            "14 bad 13",
        ])
        + "\n"
    )
    entries = static_predicate_baseline.generate_entries(str(circuit), cap=20)
    counts = Counter(entry["template_family"] for entry in entries)
    assert counts == {
        "unary": 5,
        "pairwise": 5,
        "affine2": 5,
        "affine3": 5,
    }


def test_static_variable_selection_prioritizes_clean_software_names(tmp_path):
    circuit = tmp_path / "software-priority.btor2"
    lines = ["1 sort bitvec 1", "2 sort bitvec 8", "3 zero 1"]
    for lineno in range(4, 9):
        lines.append(f"{lineno} state 1")
    for lineno, name in zip(range(9, 13), ("i", "j", "k", "n")):
        lines.append(f"{lineno} state 2 {name}")
    lines += [
        "13 and 1 4 5",
        "14 and 1 13 6",
        "15 and 1 14 7",
        "16 and 1 15 8",
        "17 bad 16",
    ]
    circuit.write_text("\n".join(lines) + "\n")
    info = static_predicate_baseline.parse_btor2(str(circuit))
    selected = static_predicate_baseline.scalar_vars(info, max_vars=8)
    assert [ref for ref, _ in selected[:4]] == [
        "state9", "state10", "state11", "state12"
    ]


def test_ranked_static_templates_prioritize_orders_then_sums(tmp_path):
    circuit = tmp_path / "ranked.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 zero 1",
            "4 state 1 i",
            "5 state 1 j",
            "6 state 1 n",
            "7 init 1 4 3",
            "8 init 1 5 3",
            "9 init 1 6 3",
            "10 next 1 4 4",
            "11 next 1 5 5",
            "12 next 1 6 6",
            "13 eq 2 4 5",
            "14 bad 13",
        ])
        + "\n"
    )
    entries = static_predicate_baseline.generate_ranked_entries(
        str(circuit), cap=9
    )
    assert [entry["template_family"] for entry in entries] == (
        ["ranked_pairwise_order"] * 6 + ["ranked_sum_equality"] * 3
    )
    assert entries[0]["predicate_ast"] == {
        "form": "ule",
        "args": [ref("state4"), ref("state5")],
    }
    assert entries[6]["predicate_ast"] == {
        "form": "eq",
        "args": [
            {"form": "add", "args": [ref("state5"), ref("state6")]},
            ref("state4"),
        ],
    }


def test_phase_summary_rejects_incomplete_config():
    rows = [
        {
            "trial": "0",
            "benchmark_id": "a.btor2",
            "config": "baseline",
            "verdict": "unsat",
        }
    ]
    with pytest.raises(ValueError, match="canonical corpus"):
        summarize_phase1_2.indexed_configs(rows, {"a.btor2", "b.btor2"})
    assert summarize_phase1_2.summarize_config(rows) == {
        "verdict_counts": {"unsat": 1},
        "sat_benchmark_ids": [],
        "unsat_benchmark_ids": ["a.btor2"],
    }


def test_artifact_hash_manifest_is_sorted_and_rejects_duplicates(
    tmp_path, monkeypatch
):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "b.txt").write_text("b")
    (artifacts / "a.txt").write_text("a")
    monkeypatch.setattr(hash_research_artifacts, "ARTIFACTS", artifacts)
    hash_research_artifacts.write_manifest(
        "hashes.json", "test-schema", ["b.txt", "a.txt"]
    )
    payload = json.loads((artifacts / "hashes.json").read_text())
    assert payload["schema"] == "test-schema"
    assert [row["path"] for row in payload["files"]] == [
        "artifacts/a.txt",
        "artifacts/b.txt",
    ]
    with pytest.raises(ValueError, match="duplicate artifact paths"):
        hash_research_artifacts.write_manifest(
            "hashes.json", "test-schema", ["a.txt", "a.txt"]
        )


def test_static_unary_templates_include_exact_initial_constant(tmp_path):
    circuit = tmp_path / "initial-constant.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 constd 1 150",
            "4 state 1 bound",
            "5 init 1 4 3",
            "6 next 1 4 4",
            "7 eq 2 4 3",
            "8 bad 7",
        ])
        + "\n"
    )
    entries = static_predicate_baseline.generate_entries(str(circuit), cap=1)
    assert entries == [{
        "predicate_ast": {
            "form": "eq",
            "args": [ref("state4"), const(150, 8)],
        },
        "template_family": "unary",
    }]


def test_static_initial_decimal_ten_is_not_parsed_as_binary_two(tmp_path):
    circuit = tmp_path / "decimal-ten.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 constd 1 10",
            "4 state 1 bound",
            "5 init 1 4 3",
            "6 next 1 4 4",
            "7 eq 2 4 3",
            "8 bad 7",
        ])
        + "\n"
    )
    entry = static_predicate_baseline.generate_entries(str(circuit), cap=1)[0]
    assert entry["predicate_ast"]["args"][1] == const(10, 8)

    info = capture_candidates.parse_btor2(str(circuit))
    prompt = capture_candidates.build_software_prompt(
        {"benchmark": circuit.name, "btor2_path": str(circuit)}, info
    )
    assert "bound (8-bit, ref=state4, init=10)" in prompt
    assert "bound (8-bit, ref=state4, init=2)" not in prompt


def test_array_prompt_rejects_unsupported_read_candidates(tmp_path):
    circuit = tmp_path / "array-prompt.btor2"
    circuit.write_text("\n".join([
        "1 sort bitvec 8",
        "2 sort bitvec 1",
        "3 sort array 1 1",
        "4 state 3 memory",
        "5 state 1 index",
        "6 zero 1",
        "7 init 1 5 6",
        "8 next 1 5 5",
        "9 eq 2 5 6",
        "10 bad 9",
    ]) + "\n")
    info = capture_candidates.parse_btor2(str(circuit))
    prompt = capture_candidates.build_software_prompt(
        {"benchmark": circuit.name, "btor2_path": str(circuit)}, info
    )
    assert "ARRAY LIMITATION" in prompt
    assert "Do not propose read/write predicates" in prompt
    assert '"form":"read"' not in prompt


def test_quadratic_templates_include_triangular_relation(tmp_path):
    circuit = tmp_path / "quadratic.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 8",
            "2 sort bitvec 1",
            "3 zero 1",
            "4 state 1 acc",
            "5 state 1 counter",
            "6 state 1 bound",
            "7 init 1 4 3",
            "8 init 1 5 3",
            "9 init 1 6 3",
            "10 next 1 4 4",
            "11 next 1 5 5",
            "12 next 1 6 6",
            "13 eq 2 4 5",
            "14 bad 13",
        ])
        + "\n"
    )
    entries = static_predicate_baseline.generate_quadratic_entries(
        str(circuit), cap=2000
    )
    target = {
        "form": "ule",
        "args": [
            {
                "form": "mul",
                "args": [const(2, 8), ref("state4")],
            },
            {
                "form": "mul",
                "args": [
                    ref("state5"),
                    {
                        "form": "sub",
                        "args": [ref("state5"), const(1, 8)],
                    },
                ],
            },
        ],
    }
    keys = {
        static_predicate_baseline.candidate_key(entry["predicate_ast"])
        for entry in entries
    }
    assert static_predicate_baseline.candidate_key(target) in keys


def test_static_quadratic_oracle_certifies_triangular_recurrence(tmp_path):
    circuit = tmp_path / "triangular.btor2"
    circuit.write_text(
        "\n".join([
            "1 sort bitvec 4",
            "2 sort bitvec 1",
            "3 zero 1",
            "4 state 1 acc",
            "5 state 1 counter",
            "6 init 1 4 3",
            "7 init 1 5 3",
            "8 one 1",
            "9 add 1 5 8",
            "10 add 1 4 5",
            "11 next 1 4 10",
            "12 next 1 5 9",
            "13 constd 1 2",
            "14 mul 1 13 4",
            "15 sub 1 5 8",
            "16 mul 1 5 15",
            "17 neq 2 14 16",
            "18 bad 17",
        ])
        + "\n"
    )
    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/triangular.btor2", circuit
    )
    result = run_matrix.run_static_oracle(
        benchmark,
        timeout=5,
        pool_cap=20,
        inject_cap=20,
        cert_timeout_ms=5000,
        max_refinements=0,
        quadratic_pool_cap=20,
    )
    assert result["verdict"] == "unsat"
    assert result["engine"] == "static-houdini-certificate"
    assert result["quadratic_tested_count"] >= 1
    assert result["quadratic_candidate_count"] == 1


def test_affine_projection_closure_adds_component_bounds():
    three_i = {
        "form": "mul",
        "args": [const(3, 8), ref("state1")],
    }
    x_plus_y = {
        "form": "add",
        "args": [ref("state2"), ref("state3")],
    }
    entries = [{
        "predicate_ast": {"form": "eq", "args": [three_i, x_plus_y]},
        "template_family": "affine3",
    }]
    closure = static_predicate_baseline.abstraction_closure(entries)
    assert [entry["predicate_ast"] for entry in closure] == [
        {"form": "ule", "args": [ref("state2"), three_i]},
        {"form": "ule", "args": [ref("state3"), three_i]},
    ]


def test_candidate_checker_certifies_safe_single_bad(tmp_path):
    circuit = tmp_path / "safe.btor2"
    write_btor2(circuit)
    asts = [predicate("eq", ref("state4"), const(0, 1))["predicate_ast"]]
    results = candidate_cert_check.certify(str(circuit), asts, 1000)
    assert all(result == z3.unsat for _, result in results)


def test_candidate_checker_checks_every_bad(tmp_path):
    circuit = tmp_path / "multi.btor2"
    write_btor2(circuit, multiple_bad=True)
    asts = [predicate("eq", ref("state4"), const(0, 1))["predicate_ast"]]
    results = dict(candidate_cert_check.certify(str(circuit), asts, 1000))
    assert results["C3 H=>notBAD"] == z3.sat


def test_candidate_checker_rejects_implicit_width_extension(tmp_path):
    circuit = tmp_path / "width.btor2"
    write_btor2(circuit)
    asts = [predicate("eq", ref("state4"), const(0, 2))["predicate_ast"]]
    with pytest.raises(TypeError, match="equal bit-vector widths"):
        candidate_cert_check.certify(str(circuit), asts, 1000)


def test_houdini_removes_false_candidate_and_certifies(tmp_path):
    circuit = tmp_path / "houdini.btor2"
    write_btor2(circuit)
    asts = [
        predicate("eq", ref("state4"), const(0, 1))["predicate_ast"],
        predicate("eq", ref("state4"), const(1, 1))["predicate_ast"],
    ]
    report = candidate_cert_check.houdini_certify(str(circuit), asts, 1000)
    assert report["ok"] is True
    assert report["selected_indices"] == [0]
    assert report["removed_initial_indices"] == [1]


def test_houdini_reports_and_rejects_unsupported_candidate(tmp_path):
    circuit = tmp_path / "unsupported.btor2"
    write_btor2(circuit)
    asts = [
        {"form": "div", "args": [ref("state4"), const(1, 1)]},
        predicate("eq", ref("state4"), const(0, 1))["predicate_ast"],
    ]
    report = candidate_cert_check.houdini_certify(str(circuit), asts, 1000)
    assert report["ok"] is True
    assert report["selected_indices"] == [1]
    assert report["unsupported_candidates"] == [{
        "index": 0,
        "error": "unsupported predicate_ast form: div",
    }]


def test_replay_houdini_certificate_reports_proof_time(tmp_path):
    circuit = tmp_path / "replay.btor2"
    write_btor2(circuit)
    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/replay.btor2", circuit
    )
    entries = [
        predicate("eq", ref("state4"), const(0, 1)),
        predicate("eq", ref("state4"), const(1, 1)),
    ]
    bundle = write_legacy_capture_bundle(
        tmp_path, benchmark, entries, latency_sec=2.5
    )

    result = run_matrix.run_llm_houdini_cert(
        benchmark,
        tmp_path,
        cap=20,
        cert_timeout_ms=1000,
        capture_bundle=bundle,
    )

    assert result["verdict"] == "unsat"
    assert result["selected_candidate_count"] == 1
    assert result["certificate_time"] > 0
    assert result["model_checker_time"] == 0
    assert result["proof_time"] == result["certificate_time"]
    assert result["end_to_end_time"] >= 2.5 + result["proof_time"]
    assert result["llm_provider"] == "test-provider"
    assert result["llm_model"] == "test-model"
    assert result["llm_total_tokens"] == 123
    assert result["llm_call_count"] == 1


def test_parse_verdict_requires_an_exact_line():
    assert run_matrix.parse_verdict(b"solver built an unsat core\n") is None
    assert run_matrix.parse_verdict(b"log\nunsat\nb0\n") == "unsat"
    assert run_matrix.parse_verdict(b"sat\nunsat\n") is None
    assert run_matrix.verdict_matches_exit("sat", 0)
    assert run_matrix.verdict_matches_exit("unsat", 1)
    assert run_matrix.verdict_matches_exit("unknown", 255)
    assert not run_matrix.verdict_matches_exit("unsat", 2)


def test_run_pono_rejects_verdict_exit_mismatch(monkeypatch):
    monkeypatch.setattr(
        run_matrix.subprocess,
        "run",
        lambda *args, **kwargs: run_matrix.subprocess.CompletedProcess(
            args[0], 2, stdout=b"unsat\n", stderr=b"backend failed\n"
        ),
    )
    result = run_matrix.run_pono(["dummy.btor2"], 1.0)
    assert result["verdict"] == "error"
    assert result["exit"] == 2


def test_two_tier_replay_stops_on_decisive_sat(tmp_path, monkeypatch):
    circuit = tmp_path / "tier-sat.btor2"
    write_btor2(circuit)
    benchmark = experiment_manifest.BenchmarkSpec(
        "suite/tier-sat.btor2", circuit
    )
    bundle = write_legacy_capture_bundle(
        tmp_path,
        benchmark,
        [predicate("eq", ref("state4"), const(0, 1))],
    )
    calls = []

    def fake_run_with_predicates(path, lines, timeout, max_refinements):
        calls.append((path, lines, timeout, max_refinements))
        return {"verdict": "sat", "time": 0.01, "exit": 0, "error": ""}

    monkeypatch.setattr(run_matrix, "run_with_predicates", fake_run_with_predicates)
    result = run_matrix.run_llm_config(
        benchmark,
        "llm-two-tier",
        tmp_path,
        timeout=70,
        cap=20,
        max_refinements=0,
        capture_bundle=bundle,
    )
    assert result["verdict"] == "sat"
    assert result["tier"] == 1
    assert len(calls) == 1


def test_portfolio_capture_metadata_only_when_llm_runs():
    assert run_matrix.uses_candidate_capture(
        "portfolio", {"tier": "llm-after-baseline"}
    )
    assert not run_matrix.uses_candidate_capture(
        "portfolio", {"tier": "baseline"}
    )
    assert run_matrix.uses_candidate_capture("llm-linear", {})


def test_run_matrix_atomically_writes_empty_matrix(tmp_path, monkeypatch):
    manifest = tmp_path / "empty.json"
    manifest.write_text('{"benchmarks": []}')
    output = tmp_path / "matrix.csv"
    monkeypatch.setattr(sys, "argv", [
        "run_matrix.py",
        "--manifest", str(manifest),
        "--benchmark-root", str(tmp_path),
        "--configs", "baseline",
        "--out", str(output),
    ])
    assert run_matrix.main() == 0
    assert output.exists()
    assert not (tmp_path / "matrix.csv.partial").exists()
    assert output.read_text().splitlines()[0].split(",") == list(
        run_matrix.ROW_FIELDS
    )


def test_run_matrix_records_selected_benchmark_contract(tmp_path, monkeypatch):
    circuit = tmp_path / "contract.btor2"
    write_btor2(circuit)
    digest = hashlib.sha256(circuit.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": circuit.name,
            "content_sha256": digest,
        }]
    }))
    output = tmp_path / "matrix.csv"

    def fake_run_config(*args, **kwargs):
        return {
            "verdict": "unknown",
            "proof_time": 0.0,
            "offline_time": 0.0,
            "end_to_end_time": 0.0,
        }

    monkeypatch.setattr(run_matrix, "run_config", fake_run_config)
    monkeypatch.setattr(sys, "argv", [
        "run_matrix.py",
        "--manifest", str(manifest),
        "--benchmark-root", str(tmp_path),
        "--configs", "baseline",
        "--out", str(output),
    ])
    assert run_matrix.main() == 0
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    experiment_manifest.validate_replay_matrix(
        rows,
        {circuit.name: digest},
        ["baseline"],
        1,
        benchmark_manifest_sha256=hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest(),
    )


def test_run_matrix_rejects_benchmark_hash_mismatch(tmp_path, monkeypatch):
    circuit = tmp_path / "bad-hash.btor2"
    write_btor2(circuit)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": circuit.name,
            "content_sha256": "0" * 64,
        }]
    }))
    monkeypatch.setattr(sys, "argv", [
        "run_matrix.py",
        "--manifest", str(manifest),
        "--benchmark-root", str(tmp_path),
        "--configs", "baseline",
    ])
    with pytest.raises(ValueError, match="content hash mismatch"):
        run_matrix.main()


def test_run_matrix_rejects_missing_capture_integrity(tmp_path, monkeypatch):
    circuit = tmp_path / "missing-capture.btor2"
    write_btor2(circuit)
    digest = hashlib.sha256(circuit.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "benchmarks": [{
            "benchmark_id": circuit.name,
            "content_sha256": digest,
        }]
    }))
    capture = tmp_path / "capture"
    capture.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "run_matrix.py",
        "--manifest", str(manifest),
        "--benchmark-root", str(tmp_path),
        "--pred-dir", str(capture),
        "--configs", "llm-linear",
    ])
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        run_matrix.main()


def test_replay_filters_unsupported_ast_with_diagnostic(tmp_path):
    path = tmp_path / "predicates.jsonl"
    entries = [
        {"predicate_ast": {
            "form": "div",
            "args": [ref("state1"), const(2, 8)],
        }},
        predicate("eq", ref("state1"), const(0, 8)),
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
    lines, _, errors, indices = run_matrix.load_predicate_lines(path, "full", 20)
    assert len(lines) == 1
    assert indices == [1]
    assert errors == [{
        "index": 0,
        "error": "predicate_ast uses unsupported form div",
    }]


def test_replay_semantic_filter_rejects_width_mismatch(tmp_path):
    circuit = tmp_path / "width-filter.btor2"
    write_btor2(circuit)
    lines = [json.dumps(predicate("eq", ref("state4"), const(0, 2)))]
    supported, errors = run_matrix.semantic_filter_predicate_lines(
        circuit, lines, [7]
    )
    assert supported == []
    assert errors == [{
        "index": 7,
        "error": "eq requires equal bit-vector widths, got 1 and 2",
    }]


def test_static_json_is_valid_predicate_input(tmp_path):
    circuit = tmp_path / "static.btor2"
    write_btor2(circuit)
    entries = static_predicate_baseline.generate_entries(str(circuit), cap=4)
    output = tmp_path / "predicates.jsonl"
    output.write_text("\n".join(json.dumps(entry, sort_keys=True) for entry in entries))
    loaded = candidate_cert_check.load_predicate_entries(str(output))
    assert loaded == entries


def test_reliability_summary_keeps_independent_capture_identity(tmp_path):
    paths = []
    for index, verdict in enumerate(("unsat", "timeout"), start=1):
        path = tmp_path / f"matrix-{index}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "trial",
                "benchmark_id",
                "circuit",
                "config",
                "verdict",
                "capture_manifest_sha256",
                "candidate_sha256",
                "proof_time_sec",
                "llm_total_tokens",
                "unsupported_candidate_count",
            ])
            writer.writeheader()
            writer.writerow({
                "trial": 0,
                "benchmark_id": "suite/example.btor2",
                "circuit": "example.btor2",
                "config": "llm-two-tier",
                "verdict": verdict,
                "capture_manifest_sha256": f"capture-{index}",
                "candidate_sha256": f"candidate-{index}",
                "proof_time_sec": index,
                "llm_total_tokens": 100 * index,
                "unsupported_candidate_count": index - 1,
            })
        paths.append(path)

    rows, _ = summarize_reliability.read_rows(paths)
    report = summarize_reliability.summarize(rows)
    group = report["groups"][0]
    assert group["runs"] == 2
    assert group["capture_count"] == 2
    assert group["candidate_hash_count"] == 2
    assert group["unsat_rate"] == 0.5
    assert group["proof_time_sec"]["median"] == 1.5


def test_reliability_summary_does_not_count_empty_capture_hash():
    report = summarize_reliability.summarize([{
        "benchmark_id": "suite/example.btor2",
        "circuit": "example.btor2",
        "config": "baseline",
        "verdict": "unknown",
        "capture_manifest_sha256": "",
        "candidate_sha256": "",
    }])
    group = report["groups"][0]
    assert group["capture_count"] == 0
    assert group["candidate_hash_count"] == 0
