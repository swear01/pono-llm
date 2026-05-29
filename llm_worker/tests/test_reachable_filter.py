#!/usr/bin/env python3
"""Tests for reachable-sample filter.

Run: python3 -m pytest llm_worker/tests/test_reachable_filter.py -v
"""

import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reachable_filter import evaluate_on_sample, filter_candidates, filter_summary


class TestEvaluateOnSample(unittest.TestCase):

    def test_le_bound_violated(self):
        r = evaluate_on_sample("(<= state1536 14)", {"state1536_next": "15"})
        self.assertEqual(r["result"], "violated")

    def test_disequality_violated(self):
        r = evaluate_on_sample("(not (= state1536 15))", {"state1536_next": "15"})
        self.assertEqual(r["result"], "violated")

    def test_implication_violated_by_ce(self):
        r = evaluate_on_sample(
            "(=> (= state1536 10) (= state790 0))",
            {"state1536_next": "10", "state790_next": "1"})
        self.assertEqual(r["result"], "violated")

    def test_implication_holds_on_ce(self):
        r = evaluate_on_sample(
            "(=> (= state1536 10) (= state790 1))",
            {"state1536_next": "10", "state790_next": "1"})
        self.assertEqual(r["result"], "holds")

    def test_implication_vacuously_holds(self):
        r = evaluate_on_sample(
            "(=> (= state1536 10) (= state790 0))",
            {"state1536_next": "5", "state790_next": "0"})
        self.assertEqual(r["result"], "holds")

    def test_missing_variable(self):
        r = evaluate_on_sample(
            "(=> (= state9999 0) (= state790 0))",
            {"state1536_next": "10", "state790_next": "1"})
        self.assertEqual(r["result"], "missing_variable")

    def test_mutex_violated(self):
        r = evaluate_on_sample(
            "(! (and (= state1536 10) (= state79 1)))",
            {"state1536_next": "10", "state79_next": "1"})
        self.assertEqual(r["result"], "violated")

    def test_mutex_holds(self):
        r = evaluate_on_sample(
            "(! (and (= state1536 10) (= state79 1)))",
            {"state1536_next": "10", "state79_next": "0"})
        self.assertEqual(r["result"], "holds")

    def test_empty_lemma(self):
        r = evaluate_on_sample("", {"state1536_next": "15"})
        self.assertEqual(r["result"], "unknown_parse")

    def test_ge_bound_holds(self):
        r = evaluate_on_sample("(>= state1536 10)", {"state1536_next": "15"})
        self.assertEqual(r["result"], "holds")

    def test_ge_bound_violated(self):
        r = evaluate_on_sample("(>= state1536 10)", {"state1536_next": "5"})
        self.assertEqual(r["result"], "violated")


class TestFilterCandidates(unittest.TestCase):

    def setUp(self):
        self.samples = [
            {"sample_id": "s1", "values": {"state1536_next": "15", "state2002_next": "1"}},
            {"sample_id": "s2", "values": {"state1536_next": "10", "state790_next": "1"}},
            {"sample_id": "init", "values": {"state1536_next": "0", "state790_next": "1"}},
        ]

    def test_filter_rejects_contradicting_candidate(self):
        cands = [{"candidate_id": "test_001", "lemma": "(<= state1536 14)"}]
        results = filter_candidates(cands, self.samples)
        self.assertEqual(results[0]["filter_result"], "violates_reachable_sample")

    def test_filter_accepts_consistent_candidate(self):
        cands = [{"candidate_id": "test_002", "lemma": "(=> (= state1536 10) (= state790 1))"}]
        results = filter_candidates(cands, self.samples)
        self.assertEqual(results[0]["filter_result"], "consistent_with_samples")

    def test_filter_skips_rejected(self):
        cands = [{"candidate_id": "test_003", "lemma": "reject"}]
        results = filter_candidates(cands, self.samples)
        self.assertEqual(results[0]["filter_result"], "not_applicable")

    def test_filter_summary(self):
        cands = [
            {"candidate_id": "a", "lemma": "(<= state1536 14)"},
            {"candidate_id": "b", "lemma": "(=> (= state1536 10) (= state790 1))"},
            {"candidate_id": "c", "lemma": "reject"},
        ]
        results = filter_candidates(cands, self.samples)
        summary = filter_summary(results)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["violates_reachable_sample"], 1)
        self.assertEqual(summary["consistent_with_samples"], 1)
        self.assertEqual(summary["not_applicable"], 1)


if __name__ == "__main__":
    unittest.main()
