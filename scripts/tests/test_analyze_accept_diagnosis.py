"""Unit tests for analyze_accept_diagnosis.py (no archive required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_accept_diagnosis as diag  # noqa: E402


def test_bench_slug():
    assert diag.bench_slug("/a/microban_110.btor2", "2025", "bv") == "2025_bv_microban_110"


def test_parse_batch_id():
    assert diag.parse_batch_id("batch_f2_a3") == ("batch_f2", 3)


def test_negate_top1_mic_clause():
    clause = diag.negate_top1_mic_clause("state5=1")
    assert clause == [{"ref": "state5", "op": "eq", "rhs": "1", "polarity": False}]
    clause2 = diag.negate_top1_mic_clause("!state7=0")
    assert clause2 == [{"ref": "state7", "op": "eq", "rhs": "0", "polarity": True}]


def test_phase_d1_on_minimal_csv(tmp_path: Path):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(
        "benchmark,year,track,expected,mode,result,wall_time,category,match,"
        "llm_accepted,llm_rejected,llm_errors,llm_requests,llm_candidates,"
        "llm_schema_fail,llm_parse_fail,llm_vocab_fail,llm_induction_fail,"
        "llm_rejected_initial,llm_missing_block,llm_lookup_miss,llm_attempt_mismatch,"
        "llm_budget_skip,llm_predicates_added,llm_batch_timeouts,llm_batch_waits,"
        "llm_batch_wait_ms_total,llm_batch_wait_ms_max\n"
        "/x/microban_110.btor2,2025,bv,sat,llm,sat,1.0,fast,True,"
        "2,8,0,10,10,0,0,0,1,7,0,0,0,0,0,0,0,0,0\n"
    )
    rows = diag.load_csv(csv_path)
    out = diag.phase_d1(rows)
    assert out["totals"]["accepted"] == 2
    assert out["totals"]["requests"] == 10
    assert out["totals"]["accept_per_request_pct"] == 20.0


def test_classify_rejected_initial_b1_init_match():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state5", "next_value": "#b0"},
        "rejected_json": '{"source_cti_id":"batch_f1_a1","attempt":1,"sample_id":0}',
    }
    resp = {
        "source_cti_id": "batch_f1_a1",
        "attempt": 1,
        "sample_id": 0,
        "block_clauses": [
            [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": True}],
        ],
    }
    out = diag.classify_rejected_initial_entry(fb, resp, {"state5"})
    assert out["category"] == "B1_single_witness_lit_true_at_init"


def test_classify_rejected_initial_c2_multi_or():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state5", "next_value": "#b0"},
        "rejected_json": '{"source_cti_id":"batch_f1_a1","attempt":1,"sample_id":0}',
    }
    resp = {
        "source_cti_id": "batch_f1_a1",
        "attempt": 1,
        "sample_id": 0,
        "block_clauses": [
            [
                {"ref": "state5", "op": "eq", "rhs": "1", "polarity": True},
                {"ref": "state9", "op": "eq", "rhs": "0", "polarity": False},
            ],
        ],
    }
    out = diag.classify_rejected_initial_entry(fb, resp, {"state5"})
    assert out["category"] == "C2_multi_or_other_disjunct_at_init"


def test_collect_clauses_legacy_and_new():
    resp = {
        "block_clauses": [[{"ref": "state1", "op": "eq", "rhs": "0", "polarity": True}]],
    }
    assert len(diag.collect_clauses(resp)) == 1
    resp2 = {"block_disjuncts": [{"ref": "state2", "op": "eq", "rhs": "1", "polarity": False}]}
    assert len(diag.collect_clauses(resp2)) == 1
