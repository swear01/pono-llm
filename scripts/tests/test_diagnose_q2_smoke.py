"""Tests for diagnose_q2_smoke.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnose_q2_smoke as dsm  # noqa: E402


def test_classify_uses_clause_idx_from_rejected_json():
    fb = {
        "reason": "rejected_initial",
        "witness": {"ref": "state0", "next_value": "#b0"},
        "rejected_json": json.dumps(
            {
                "clause_idx": 1,
                "block_clauses": [
                    [{"ref": "state5", "op": "eq", "rhs": "0", "polarity": False}],
                    [{"ref": "state0", "op": "eq", "rhs": "1", "polarity": True}],
                ],
            }
        ),
    }
    entry = dsm.classify_ri_with_clause_idx(fb, None, {"state0", "state5"})
    assert entry["clause_idx"] == 1
    assert entry["category"] == "B2_single_witness_lit_false_at_witness"
    assert entry["used_clause_idx"] is True


def test_true_positive_cti_copy_vs_digest_neg():
    req = {
        "cti_digest": {
            "literal_stats": [{"lit": "state512=#b1", "count": 5}],
        },
        "cti_entries": [{"cti_id": "c1", "literals": ["state512=1"]}],
    }
    pos = {"ref": "state512", "op": "eq", "rhs": "#b1", "polarity": True}
    neg = {"ref": "state512", "op": "eq", "rhs": "#b1", "polarity": False}
    assert dsm.disjunct_is_true_positive_cti_copy(pos, req)
    assert not dsm.disjunct_is_true_positive_cti_copy(neg, req)
    assert dsm.disjunct_matches_digest_negation(neg, req)
    assert not dsm.disjunct_matches_digest_negation(pos, req)


def test_witness_forbidden_viol_init_wide():
    dj = {"ref": "state798", "op": "eq", "rhs": "#b000", "polarity": True}
    assert dsm.failed_disjunct_hits_witness_forbidden(dj, "state798", "#b000000000000")


def test_aggregate_runs_sums_accept():
    per = [
        {"llm_stats": {"accepted": 1, "requests": 10}, "rejected_initial_taxonomy": {"total": 2, "categories": {"B2_single_witness_lit_false_at_witness": 2}}, "response_shape": {}, "cti_literal_copy": {}},
        {"llm_stats": {"accepted": 2, "requests": 9}, "rejected_initial_taxonomy": {"total": 1, "categories": {"C2_multi_or_other_disjunct_at_init": 1}}, "response_shape": {}, "cti_literal_copy": {}},
    ]
    agg = dsm.aggregate_runs(per)
    assert agg["accepted"] == 3
    assert agg["requests"] == 19
    assert agg["accept_per_request_pct"] == round(100 * 3 / 19, 1)
