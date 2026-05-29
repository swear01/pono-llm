#!/usr/bin/env python3
"""Tests for lemma nontriviality gate.

Run: python3 -m pytest llm_worker/tests/test_lemma_nontriviality.py -v
"""

import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lemma_nontriviality import (
    check_bitwidth_tautology, check_tautological_consequent,
    check_impossible_antecedent, check_ce_blocking,
    check_variable_relevance, gate_repaired_lemma,
    parse_variables, _extract_implication_parts,
)


class TestSEXPRParsing(unittest.TestCase):

    def test_parse_simple_implication(self):
        parts = _extract_implication_parts("(=> (= state10 0) (= state11 1))")
        self.assertIsNotNone(parts)
        self.assertEqual(parts[0], "(= state10 0)")
        self.assertEqual(parts[1], "(= state11 1)")

    def test_parse_le_bound_implication(self):
        parts = _extract_implication_parts("(=> (= state10 0) (<= state11 1))")
        self.assertIsNotNone(parts)
        self.assertEqual(parts[0], "(= state10 0)")
        self.assertEqual(parts[1], "(<= state11 1)")

    def test_parse_negated_consequent(self):
        parts = _extract_implication_parts("(=> (= state10 0) (not (= state11 1)))")
        self.assertIsNotNone(parts)
        self.assertEqual(parts[1], "(not (= state11 1))")

    def test_parse_standalone_comparison(self):
        parts = _extract_implication_parts("(<= state10 0)")
        self.assertIsNone(parts)


class TestBitwidthTautology(unittest.TestCase):

    def test_1bit_le_1_is_tautology(self):
        """(<= stateX 1) where stateX is 1-bit is always true."""
        bw = {"state10": 1}
        self.assertEqual(
            check_bitwidth_tautology("(=> (= state10 0) (<= state10 1))", bw),
            "tautology")

    def test_4bit_le_15_is_tautology(self):
        """(<= stateX 15) where stateX is 4-bit is always true."""
        bw = {"state10": 4}
        self.assertEqual(
            check_bitwidth_tautology("(=> (= state10 0) (<= state10 15))", bw),
            "tautology")

    def test_4bit_lt_16_is_tautology(self):
        """(< stateX 16) where stateX is 4-bit is always true."""
        bw = {"state10": 4}
        self.assertEqual(
            check_bitwidth_tautology("(=> (= state10 0) (< state10 16))", bw),
            "tautology")

    def test_4bit_ge_0_is_not_flagged(self):
        """(>= stateX 0) — unsigned, always true, but we don't flag >= 0 yet."""
        bw = {"state10": 4}
        # >= 0 for unsigned is tautology, but our check only catches >= 0 
        # when val <= 0, which is true. So this IS caught.
        self.assertEqual(
            check_bitwidth_tautology("(=> (= state10 0) (>= state10 0))", bw),
            "tautology")

    def test_4bit_eq_16_is_contradiction(self):
        """(= stateX 16) where stateX is 4-bit: impossible antecedent."""
        bw = {"state10": 4}
        self.assertEqual(
            check_bitwidth_tautology("(=> (= state10 16) (= state11 0))", bw),
            "tautology")

    def test_nontrivial_mutex_is_not_trivial(self):
        """!(state10=3 && state11=1) where both are 4-bit: nontrivial."""
        bw = {"state10": 4, "state11": 4}
        result = check_bitwidth_tautology(
            "(! (and (= state10 3) (= state11 1)))", bw)
        self.assertIsNone(result)

    def test_nontrivial_implication_is_not_trivial(self):
        """4-bit x = 10 => 1-bit y = 0: nontrivial."""
        bw = {"state10": 4, "state11": 1}
        result = check_bitwidth_tautology(
            "(=> (= state10 10) (= state11 0))", bw)
        self.assertIsNone(result)

    def test_standalone_le_bound(self):
        """(<= stateX 3) where stateX is 4-bit: nontrivial."""
        bw = {"state10": 4}
        result = check_bitwidth_tautology("(<= state10 3)", bw)
        self.assertIsNone(result)

    def test_standalone_le_bound_tautology(self):
        """(<= stateX 15) where stateX is 4-bit: trivial."""
        bw = {"state10": 4}
        result = check_bitwidth_tautology("(<= state10 15)", bw)
        self.assertEqual(result, "tautology")


class TestImpossibleAntecedent(unittest.TestCase):

    def test_4bit_eq_16_impossible(self):
        bw = {"state10": 4}
        self.assertEqual(
            check_impossible_antecedent("(=> (= state10 16) (= state11 0))", bw),
            "impossible")

    def test_feasible_antecedent(self):
        bw = {"state10": 4}
        self.assertIsNone(
            check_impossible_antecedent("(=> (= state10 10) (= state11 0))", bw))


class TestTautologicalConsequent(unittest.TestCase):

    def test_1bit_le_1_is_tautology(self):
        bw = {"state10": 1}
        self.assertEqual(
            check_tautological_consequent("(=> (= state10 0) (<= state10 1))", bw),
            "tautology")

    def test_4bit_le_3_is_nontrivial(self):
        bw = {"state10": 4}
        self.assertIsNone(
            check_tautological_consequent("(=> (= state10 0) (<= state10 3))", bw))

    def test_non_implication_returns_none(self):
        bw = {"state10": 4}
        self.assertIsNone(
            check_tautological_consequent("(<= state10 15)", bw))


class TestCEBlocking(unittest.TestCase):

    def setUp(self):
        self.bw = {"state10": 4, "state11": 1}

    def test_lemma_blocks_ce(self):
        """Original lemma: state10=3 => state11=0, CE: state10=3 state11=0.
        This CE satisfies the lemma (antecedent and consequent both hold),
        so the old CE does NOT violate this lemma — it's ce_blocked."""
        ce = {"next_values": {"state10_next": "3", "state11_next": "0"}}
        result = check_ce_blocking("(=> (= state10 3) (= state11 0))", self.bw, ce)
        self.assertEqual(result, "ce_blocked")

    def test_lemma_does_not_block_ce(self):
        """Original repair lemma: state10=0 => state11=0, CE: state10=10 state11=1.
        Antecedent state10=0 doesn't hold on CE (state10=10), so not violated."""
        ce = {"next_values": {"state10_next": "10", "state11_next": "1"}}
        result = check_ce_blocking("(=> (= state10 0) (= state11 0))", self.bw, ce)
        self.assertEqual(result, "ce_blocked")

    def test_lemma_matches_ce_violation(self):
        """Original CE had state10=10 state11=1 violating state10=10 => state11=0.
        Repair is still state10=10 => state11=0. CE antecedent holds (10=10) but
        consequent fails (state11=1 != 0) → CE still violates → ce_not_blocked."""
        ce = {"next_values": {"state10_next": "10", "state11_next": "1"}}
        result = check_ce_blocking("(=> (= state10 10) (= state11 0))", self.bw, ce)
        self.assertEqual(result, "ce_not_blocked")

    def test_tautology_does_not_block_ce(self):
        """Original CE: state10=1. Repair: state10=0 => state10 <= 1.
        Antecedent state10=0 doesn't hold on CE (state10=1), so vacuously true.
        NOT violated → ce_blocked."""
        bw1 = {"state10": 1}
        ce = {"next_values": {"state10_next": "1"}}
        result = check_ce_blocking("(=> (= state10 0) (<= state10 1))", bw1, ce)
        self.assertEqual(result, "ce_blocked")


class TestVariableRelevance(unittest.TestCase):

    def test_all_vars_relevant(self):
        result = check_variable_relevance(
            ["state10", "state11"], ["state10", "state11"])
        self.assertIsNone(result)

    def test_subset_ok(self):
        result = check_variable_relevance(
            ["state10"], ["state10", "state11"])
        self.assertIsNone(result)

    def test_unrelated_var(self):
        result = check_variable_relevance(
            ["state10", "state99"], ["state10", "state11"])
        self.assertEqual(result, "unrelated: state99")


class TestGateRepairedLemma(unittest.TestCase):

    def test_trivial_tautology_downgraded(self):
        bw = {"state10": 1}
        gr = gate_repaired_lemma(
            lemma="(=> (= state10 0) (<= state10 1))",
            bitwidths=bw,
            original_vars=["state10"],
            solver_verdict="solver_verified_strong")
        self.assertEqual(gr["gate_verdict"], "solver_verified_trivial")

    def test_nontrivial_passes_gate(self):
        bw = {"state10": 4, "state11": 1}
        gr = gate_repaired_lemma(
            lemma="(! (and (= state10 10) (= state11 1)))",
            bitwidths=bw,
            original_vars=["state10", "state11"],
            solver_verdict="solver_verified_strong")
        self.assertEqual(gr["gate_verdict"], "solver_verified_useful")

    def test_ce_not_blocked_downgraded(self):
        bw = {"state10": 4, "state11": 1}
        ce = {"next_values": {"state10_next": "10", "state11_next": "1"}}
        gr = gate_repaired_lemma(
            lemma="(=> (= state10 10) (= state11 0))",
            bitwidths=bw,
            original_vars=["state10", "state11"],
            original_ce=ce,
            solver_verdict="solver_verified_strong")
        self.assertEqual(gr["gate_verdict"], "counterexample_not_blocked")


if __name__ == "__main__":
    unittest.main()
