from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import extract_btor_features  # noqa: E402
import experiment_manifest  # noqa: E402
import select_gate2_corpus  # noqa: E402
import select_gate2_survivors  # noqa: E402
import select_gate2_llm_targets  # noqa: E402
import summarize_gate2  # noqa: E402


def matrix_contract_rows(
    rows: list[dict],
    benchmark_hashes: dict[str, str],
    configs: list[str],
    trials: int = 1,
    manifest_sha256: str = "f" * 64,
) -> list[dict]:
    contract = experiment_manifest.replay_matrix_contract(
        benchmark_hashes, configs, trials
    )
    return [
        {
            **row,
            **contract,
            "benchmark_manifest_sha256": manifest_sha256,
        }
        for row in rows
    ]


def write_feature_circuit(path: Path) -> None:
    path.write_text("\n".join([
        "1 sort bitvec 8",
        "2 sort bitvec 1",
        "3 zero 1",
        "4 one 1",
        "5 state 1 acc",
        "6 state 1 counter",
        "7 init 1 5 3",
        "8 init 1 6 3",
        "9 mul 1 4 5",
        "10 mul 1 5 6",
        "11 add 1 6 4",
        "12 next 1 5 9",
        "13 next 1 6 11",
        "14 eq 2 5 6",
        "15 bad 14",
    ]) + "\n")


def test_extract_features_classifies_multiplication(tmp_path):
    root = tmp_path / "benchmarks"
    circuit = root / "2025" / "wordlevel" / "bv" / "2025" / "sosylab" / "suite" / "example.btor2"
    circuit.parent.mkdir(parents=True)
    write_feature_circuit(circuit)
    row = extract_btor_features.extract_features(circuit, root)
    assert row["software_origin"] == 1
    assert row["has_array"] == 0
    assert row["mul_count"] == 2
    assert row["mul_const_var_count"] == 1
    assert row["mul_var_var_count"] == 1
    assert row["arithmetic_class"] == "nonlinear"
    assert row["bad_count"] == 1
    assert len(row["content_sha256"]) == 64


def test_gate2_selector_deduplicates_and_round_robins(tmp_path):
    feature_file = tmp_path / "features.csv"
    rows = [
        {
            "benchmark_id": "a/one.btor2",
            "content_sha256": "same",
            "parse_status": "ok",
            "software_origin": "1",
            "has_array": "0",
            "producer": "p1",
            "suite": "s1",
            "arithmetic_class": "affine",
            "size_bucket": "lt1k",
        },
        {
            "benchmark_id": "b/duplicate.btor2",
            "content_sha256": "same",
            "parse_status": "ok",
            "software_origin": "1",
            "has_array": "0",
            "producer": "p1",
            "suite": "s1",
            "arithmetic_class": "affine",
            "size_bucket": "lt1k",
        },
        {
            "benchmark_id": "c/two.btor2",
            "content_sha256": "two",
            "parse_status": "ok",
            "software_origin": "1",
            "has_array": "0",
            "producer": "p2",
            "suite": "s2",
            "arithmetic_class": "nonlinear",
            "size_bucket": "1k-10k",
        },
        {
            "benchmark_id": "d/array.btor2",
            "content_sha256": "array",
            "parse_status": "ok",
            "software_origin": "1",
            "has_array": "1",
            "producer": "p3",
            "suite": "s3",
            "arithmetic_class": "affine",
            "size_bucket": "lt1k",
        },
    ]
    with feature_file.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    manifest = select_gate2_corpus.build_manifest(rows, feature_file, target=10)
    assert manifest["eligible_before_dedup"] == 3
    assert manifest["duplicate_instances_removed"] == 1
    assert manifest["unique_eligible"] == 2
    assert manifest["selected_count"] == 2
    assert manifest["feature_sha256"] == hashlib.sha256(
        feature_file.read_bytes()
    ).hexdigest()
    assert {row["benchmark_id"] for row in manifest["benchmarks"]} == {
        "a/one.btor2",
        "c/two.btor2",
    }


def test_gate2_survivors_exclude_any_decisive_baseline(tmp_path):
    matrix = tmp_path / "baseline.csv"
    hash_a = "a" * 64
    hash_b = "b" * 64
    rows = [
        {"trial": "0", "benchmark_id": "a.btor2", "config": "baseline", "verdict": "timeout", "benchmark_content_sha256": hash_a},
        {"trial": "0", "benchmark_id": "b.btor2", "config": "baseline", "verdict": "timeout", "benchmark_content_sha256": hash_b},
    ]
    rows[1]["verdict"] = "unsat"
    hashes = {"a.btor2": hash_a, "b.btor2": hash_b}
    manifest_sha256 = "e" * 64
    rows = matrix_contract_rows(
        rows, hashes, ["baseline"], manifest_sha256=manifest_sha256
    )
    with matrix.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    manifest = select_gate2_survivors.build_survivor_manifest(
        rows, matrix, hashes, manifest_sha256
    )
    assert manifest["source_benchmark_count"] == 2
    assert manifest["selected_count"] == 1
    assert manifest["benchmarks"] == [{
        "benchmark_id": "a.btor2",
        "content_sha256": hash_a,
        "screen_verdicts": ["timeout"],
    }]

    features = [
        {"benchmark_id": "a.btor2", "node_count": "100001", "content_sha256": hash_a},
        {"benchmark_id": "b.btor2", "node_count": "10", "content_sha256": hash_b},
    ]
    bounded = select_gate2_survivors.build_survivor_manifest(
        rows,
        matrix,
        hashes,
        manifest_sha256,
        features,
        max_nodes=100000,
    )
    assert bounded["selected_count"] == 0
    assert bounded["excluded_by_size"] == [{
        "benchmark_id": "a.btor2",
        "node_count": 100001,
    }]


def test_gate2_survivors_reject_missing_content_hash(tmp_path):
    matrix = tmp_path / "baseline.csv"
    rows = [{
        "trial": "0",
        "benchmark_id": "a.btor2",
        "config": "baseline",
        "verdict": "timeout",
    }]
    matrix.write_text("")
    with pytest.raises(ValueError, match="content hash mismatch"):
        select_gate2_survivors.build_survivor_manifest(
            rows, matrix, {"a.btor2": "a" * 64}, "b" * 64
        )


def test_gate2_llm_targets_are_new_and_deterministic_hard():
    old_hash = "a" * 64
    static_hash = "b" * 64
    target_hash = "c" * 64
    survivors = {
        "benchmarks": [
            {"benchmark_id": "old.btor2", "content_sha256": old_hash},
            {"benchmark_id": "static.btor2", "content_sha256": static_hash},
            {"benchmark_id": "target.btor2", "content_sha256": target_hash},
        ]
    }
    prior_hashes = {"old.btor2": old_hash}
    prior = matrix_contract_rows(
        [
            {
                "trial": "0",
                "benchmark_id": "old.btor2",
                "config": config,
                "verdict": "unknown",
                "benchmark_content_sha256": old_hash,
            }
            for config in select_gate2_llm_targets.PRIOR_CONFIGS
        ],
        prior_hashes,
        list(select_gate2_llm_targets.PRIOR_CONFIGS),
        manifest_sha256="d" * 64,
    )
    deterministic = matrix_contract_rows([
        {"trial": "0", "config": "static-quadratic-oracle", "benchmark_id": "old.btor2", "verdict": "unknown", "benchmark_content_sha256": old_hash},
        {"trial": "0", "config": "static-quadratic-oracle", "benchmark_id": "static.btor2", "verdict": "unsat", "benchmark_content_sha256": static_hash},
        {"trial": "0", "config": "static-quadratic-oracle", "benchmark_id": "target.btor2", "verdict": "timeout", "benchmark_content_sha256": target_hash},
    ], {
        "old.btor2": old_hash,
        "static.btor2": static_hash,
        "target.btor2": target_hash,
    }, ["static-quadratic-oracle"], manifest_sha256="c" * 64)
    manifest = select_gate2_llm_targets.build_target_manifest(
        survivors,
        "c" * 64,
        prior,
        prior_hashes,
        "d" * 64,
        deterministic,
    )
    assert manifest["selected_count"] == 1
    assert manifest["benchmarks"] == [{
        "benchmark_id": "target.btor2",
        "content_sha256": target_hash,
    }]


def test_gate2_survivors_reject_partial_matrix(tmp_path):
    hashes = {"a.btor2": "a" * 64, "b.btor2": "b" * 64}
    rows = matrix_contract_rows([
        {
            "trial": "0",
            "benchmark_id": "a.btor2",
            "config": "baseline",
            "verdict": "timeout",
            "benchmark_content_sha256": hashes["a.btor2"],
        }
    ], hashes, ["baseline"], manifest_sha256="c" * 64)
    matrix = tmp_path / "partial.csv"
    matrix.write_text("partial")
    with pytest.raises(ValueError, match="contract"):
        select_gate2_survivors.build_survivor_manifest(
            rows, matrix, hashes, "c" * 64
        )


def test_gate2_survivors_reject_stale_feature_hash(tmp_path):
    digest = "a" * 64
    rows = matrix_contract_rows([{
        "trial": "0",
        "benchmark_id": "a.btor2",
        "config": "baseline",
        "verdict": "timeout",
        "benchmark_content_sha256": digest,
    }], {"a.btor2": digest}, ["baseline"], manifest_sha256="c" * 64)
    matrix = tmp_path / "baseline.csv"
    matrix.write_text("baseline")
    with pytest.raises(ValueError, match="feature/model content hash mismatch"):
        select_gate2_survivors.build_survivor_manifest(
            rows,
            matrix,
            {"a.btor2": digest},
            "c" * 64,
            [{
                "benchmark_id": "a.btor2",
                "content_sha256": "b" * 64,
                "node_count": "1",
            }],
            max_nodes=10,
        )


def test_gate2_targets_reject_wrong_deterministic_config():
    digest = "a" * 64
    survivors = {
        "benchmarks": [{"benchmark_id": "a.btor2", "content_sha256": digest}]
    }
    prior = matrix_contract_rows([
        {
            "trial": "0",
            "benchmark_id": "old.btor2",
            "config": config,
            "verdict": "unknown",
            "benchmark_content_sha256": "b" * 64,
        }
        for config in select_gate2_llm_targets.PRIOR_CONFIGS
    ], {"old.btor2": "b" * 64}, list(select_gate2_llm_targets.PRIOR_CONFIGS), manifest_sha256="d" * 64)
    deterministic = matrix_contract_rows([{
        "trial": "0",
        "benchmark_id": "a.btor2",
        "config": "baseline",
        "verdict": "timeout",
        "benchmark_content_sha256": digest,
    }], {"a.btor2": digest}, ["baseline"], manifest_sha256="c" * 64)
    with pytest.raises(ValueError, match="unexpected config"):
        select_gate2_llm_targets.build_target_manifest(
            survivors,
            "c" * 64,
            prior,
            {"old.btor2": "b" * 64},
            "d" * 64,
            deterministic,
        )


def test_gate2_summary_verdicts_and_identity_validation():
    rows = [
        {
            "trial": "0",
            "benchmark_id": "safe.btor2",
            "config": "baseline",
            "verdict": "unsat",
            "proof_time_sec": "1.25",
            "candidate_generation_sec": "0.0",
            "end_to_end_sec": "1.25",
        },
        {
            "trial": "0",
            "benchmark_id": "miss.btor2",
            "config": "baseline",
            "verdict": "timeout",
            "proof_time_sec": "2.0",
            "candidate_generation_sec": "0.5",
            "end_to_end_sec": "2.5",
        },
    ]
    assert summarize_gate2.assert_unique(rows, expected_count=2) == {
        "safe.btor2",
        "miss.btor2",
    }
    summary = summarize_gate2.verdict_summary(rows)
    assert summary["verdict_counts"] == {"timeout": 1, "unsat": 1}
    assert summary["unsat_benchmark_ids"] == ["safe.btor2"]
    assert summary["total_proof_sec"] == 3.25
    assert summary["total_generation_sec"] == 0.5
    assert summary["total_end_to_end_sec"] == 3.75


def test_gate2_certificate_parser_requires_all_three_unsat_checks(tmp_path):
    certificate = tmp_path / "certificate.txt"
    certificate.write_text("\n".join([
        "  C1 Init⟹Inv      ✓ UNSAT(無反例)",
        "  C2 inductive     ✓ UNSAT(無反例)",
        "  C3 Inv⟹¬BAD      ✓ UNSAT(無反例)",
        "結論: ✅ SOUND PROOF — invariant 在原始電路成立",
    ]) + "\n")
    assert summarize_gate2.certificate_pass(certificate)
    certificate.write_text(certificate.read_text().replace("C2 inductive", "X2 inductive"))
    assert not summarize_gate2.certificate_pass(certificate)
