#!/usr/bin/env python3
"""WP4: Tests for generalization DSL."""

import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generalization_dsl import (
    validate_dsl_candidate, SUPPORTED_SCHEMAS
)


class TestDSLValidation(unittest.TestCase):

    def test_valid_single_guard(self):
        c = {"schema": "single_guard_implication",
             "guard": {"var": "state469", "value": "0"},
             "consequent": {"var": "state15", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok, reason)
        self.assertIn("state469", smt)
        self.assertIn("state15", smt)

    def test_valid_guarded_2(self):
        c = {"schema": "guarded_implication_2",
             "guards": [{"var": "state469", "value": "0"}, {"var": "state471", "value": "0"}],
             "consequent": {"var": "state15", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok, reason)
        self.assertIn("(and", smt)

    def test_valid_guarded_3(self):
        c = {"schema": "guarded_implication_3",
             "guards": [{"var": "state10", "value": "0"}, {"var": "state11", "value": "0"},
                        {"var": "state12", "value": "0"}],
             "consequent": {"var": "state13", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok, reason)

    def test_valid_nary_mutex_3(self):
        c = {"schema": "nary_mutex_3",
             "literals": [{"var": "state10", "value": "0"}, {"var": "state11", "value": "0"},
                          {"var": "state12", "value": "0"}],
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok, reason)
        self.assertIn("(not (and", smt)

    def test_reject_schema(self):
        c = {"schema": "reject", "reason": "No good generalization",
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok)

    def test_missing_source_artifact(self):
        c = {"schema": "single_guard_implication",
             "guard": {"var": "state1", "value": "0"},
             "consequent": {"var": "state2", "value": "0"}}
        ok, reason, _, _ = validate_dsl_candidate(c)
        self.assertFalse(ok)
        self.assertIn("source_artifact_id", reason)

    def test_invalid_variable(self):
        c = {"schema": "single_guard_implication",
             "guard": {"var": "notState", "value": "0"},
             "consequent": {"var": "state2", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, _, _ = validate_dsl_candidate(c)
        self.assertFalse(ok)

    def test_invalid_value(self):
        c = {"schema": "single_guard_implication",
             "guard": {"var": "state1", "value": "3"},
             "consequent": {"var": "state2", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, _, _ = validate_dsl_candidate(c)
        self.assertFalse(ok)

    def test_unsupported_schema(self):
        c = {"schema": "quantum_implication", "source_artifact_id": "a1",
             "generalization_operator": "x"}
        ok, reason, _, _ = validate_dsl_candidate(c)
        self.assertFalse(ok)

    def test_duplicate_guard_vars(self):
        c = {"schema": "guarded_implication_2",
             "guards": [{"var": "state1", "value": "0"}, {"var": "state1", "value": "1"}],
             "consequent": {"var": "state2", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, reason, _, _ = validate_dsl_candidate(c)
        self.assertFalse(ok)
        self.assertIn("duplicate", reason)

    def test_lowered_smt_matches_expected(self):
        c = {"schema": "single_guard_implication",
             "guard": {"var": "state469", "value": "0"},
             "consequent": {"var": "state15", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        ok, _, smt, _ = validate_dsl_candidate(c)
        self.assertTrue(ok)
        self.assertEqual(smt, "(=> (= state469 #b0) (= state15 #b0))")

    def test_extract_vars(self):
        from generalization_dsl import validate_dsl_candidate
        c = {"schema": "guarded_implication_2",
             "guards": [{"var": "state10", "value": "0"}, {"var": "state11", "value": "0"}],
             "consequent": {"var": "state12", "value": "0"},
             "source_artifact_id": "a1", "generalization_operator": "x"}
        _, _, _, vars_found = validate_dsl_candidate(c)
        self.assertEqual(sorted(vars_found), ["state10", "state11", "state12"])


if __name__ == "__main__":
    unittest.main()
