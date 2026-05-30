#!/usr/bin/env python3
"""Tests for lemma impact analyzer.

Run: python3 -m pytest llm_worker/tests/test_analyze_impact.py -v
"""

import json, os, sys, unittest, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from analyze_lemma_impact import LemmaImpactAnalyzer


class TestImpactAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = LemmaImpactAnalyzer()

    def _write_fixtures(self, ctis, frames):
        cti_path = os.path.join(tempfile.mkdtemp(), "ctis.jsonl")
        frame_path = os.path.join(tempfile.mkdtemp(), "frames.jsonl")
        with open(cti_path, "w") as f:
            for c in ctis:
                f.write(json.dumps(c) + "\n")
        with open(frame_path, "w") as f:
            for c in frames:
                f.write(json.dumps(c) + "\n")
        return cti_path, frame_path

    def test_cti_violates_lemma(self):
        ctis = [{"frame": 5, "cube": [
            {"varname": "state2002", "value": "1"},
            {"varname": "state790", "value": "0"}]}]
        path, _ = self._write_fixtures(ctis, [])
        result = self.analyzer.analyze_ctis(path)
        self.assertEqual(result["ctis_violating_lemma"], 1)

    def test_cti_satisfies_lemma(self):
        ctis = [{"frame": 5, "cube": [
            {"varname": "state2002", "value": "1"},
            {"varname": "state790", "value": "1"}]}]
        path, _ = self._write_fixtures(ctis, [])
        result = self.analyzer.analyze_ctis(path)
        self.assertEqual(result["ctis_satisfying_lemma"], 1)
        self.assertEqual(result["ctis_violating_lemma"], 0)

    def test_cti_irrelevant_no_target_vars(self):
        ctis = [{"frame": 5, "cube": [
            {"varname": "state1536", "value": "10"}]}]
        path, _ = self._write_fixtures(ctis, [])
        result = self.analyzer.analyze_ctis(path)
        self.assertEqual(result["ctis_with_state2002"], 0)
        self.assertEqual(result["ctis_with_state790"], 0)

    def test_cti_antecedent_true(self):
        ctis = [{"frame": 5, "cube": [
            {"varname": "state2002", "value": "1"}]},
            {"frame": 8, "cube": [
                {"varname": "state2002", "value": "1"},
                {"varname": "state790", "value": "1"}]}]
        path, _ = self._write_fixtures(ctis, [])
        result = self.analyzer.analyze_ctis(path)
        self.assertEqual(result["ctis_antecedent_true"], 2)

    def test_clause_with_both_vars(self):
        clauses = [{"frame": 8, "literals": [
            {"varname": "state2002", "polarity": "negated"},
            {"varname": "state790", "polarity": "positive"},
        ], "variables": ["state2002", "state790"]}]
        _, path = self._write_fixtures([], clauses)
        result = self.analyzer.analyze_frames(path)
        self.assertEqual(result["clauses_with_both"], 1)

    def test_highest_frame(self):
        ctis = [{"frame": 5}, {"frame": 12}, {"frame": 3}]
        path, _ = self._write_fixtures(ctis, [])
        result = self.analyzer.analyze_ctis(path)
        self.assertEqual(result["highest_frame_any_cti"], 12)

    def test_missing_files_handled(self):
        result = self.analyzer.run(cti_path="nonexistent.jsonl", frame_path="nonexistent.jsonl")
        self.assertEqual(result["impact_classification"], "unknown_no_trace_data")
        self.assertEqual(len(result["missing_files"]), 2)

    def test_classification_high(self):
        cti = {"total_ctis": 10, "ctis_violating_lemma": 3}
        frame = {"total_clauses": 20, "clauses_with_both": 3}
        impact = self.analyzer.classify_impact(cti, frame)
        self.assertEqual(impact, "high_potential")

    def test_classification_low(self):
        cti = {"total_ctis": 10, "ctis_violating_lemma": 0}
        frame = {"total_clauses": 20, "clauses_with_both": 0}
        impact = self.analyzer.classify_impact(cti, frame)
        self.assertEqual(impact, "low_potential")

    def test_variables_from_literals(self):
        record = {"literals": [
            {"varname": "state2002 = 1", "expr": "state2002 = 1"},
            {"varname": "state790_neg", "expr": "state790 = 0"},
        ]}
        vars_found = self.analyzer._extract_variables(record)
        self.assertIn("state2002", vars_found)
        self.assertIn("state790", vars_found)


class TestPredicateMapResolution(unittest.TestCase):

    def setUp(self):
        self.analyzer = LemmaImpactAnalyzer()
        # Load predicate map
        preds = [
            {"label": "pred_1", "variables": ["state2002"], "state_values": {"state2002": "1"}},
            {"label": "pred_2", "variables": ["state790"], "state_values": {"state790": "1"}},
            {"label": "pred_3", "variables": ["state1536"], "state_values": {"state1536": "15"}},
        ]
        for p in preds:
            self.analyzer.predicate_map[p["label"]] = p

    def test_pos_pred1_neg_pred2_violates_lemma(self):
        cti = {"cube": [
            {"label": "pred_1", "polarity": True},
            {"label": "pred_2", "polarity": False},
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        # pred_1=true => state2002=1, pred_2=false on 1-bit => state790=0
        self.assertFalse(result)  # lemma violated

    def test_pos_pred1_pos_pred2_satisfies_lemma(self):
        cti = {"cube": [
            {"label": "pred_1", "polarity": True},
            {"label": "pred_2", "polarity": True},
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        self.assertTrue(result)  # lemma satisfied

    def test_only_pred1_present_antecedent_known(self):
        cti = {"cube": [
            {"label": "pred_1", "polarity": True},
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        self.assertIsNone(result)  # can't evaluate (no consequent)

    def test_unknown_label_handled_gracefully(self):
        cti = {"cube": [
            {"label": "pred_unknown", "polarity": True},
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        self.assertIsNone(result)  # unknown label

    def test_negated_non_1bit_not_resolved(self):
        cti = {"cube": [
            {"label": "pred_3", "polarity": False},  # state1536=15 negated — 4-bit, unsafe
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        self.assertIsNone(result)  # cannot resolve negated 4-bit equality

    def test_resolved_expr_in_literal(self):
        cti = {"cube": [
            {"resolved_expr": "state2002 = 1 state790 = 0"},
        ]}
        result = self.analyzer._evaluate_lemma_on_cti(cti)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
