#!/usr/bin/env python3
"""Regression tests for BTOR2 transition translator fixes.

Run: python3 -m pytest llm_worker/tests/test_smt_checker.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    import bitwuzla as bz
    HAS_BITWUZLA = True
except ImportError:
    HAS_BITWUZLA = False


@unittest.skipIf(not HAS_BITWUZLA, "Bitwuzla not available")
class TestBTOR2Translate(unittest.TestCase):

    def setUp(self):
        from smt_checker import BTOR2SMT

        # Minimal BTOR2 for testing. Yosys BTOR2 uses inline widths for
        # state/input/const, NOT sort IDs. Sort IDs are used by uext only.
        self.btor = {
            # Sorts (used by uext)
            "1": ["sort", "bitvec", "1"],
            "2": ["sort", "bitvec", "6"],
            # State: <id> state <wid> <symbol>  (inline width)
            "10": ["state", "4", "test_state"],
            # Input: <id> input <wid> <symbol>  (inline width)
            "11": ["input", "10", "test_input"],
            # Const: <id> const <wid> <value>  (inline width)
            "12": ["const", "4", "0000"],
            "13": ["const", "1", "1"],
            "14": ["const", "1", "0"],
            "15": ["const", "4", "0101"],
            # Init
            "20": ["init", "4", "10", "12"],
            # Next
            "30": ["next", "4", "10", "40"],
            # ITE chain: ite 4 (cond=13 1-bit) (true=12 4-bit) (false=15 4-bit)
            "40": ["ite", "4", "13", "12", "15"],
            # Slice OOB test: extract bit 12 from 10-bit input → 1-bit zero
            "60": ["slice", "1", "11", "12", "12"],
            # uext test: p[1]=result_width=6, p[2]=source=13(1-bit), ext=6-1=5
            "70": ["uext", "6", "13", "5"],
            # eq test: should produce 1-bit BV, not Boolean
            "80": ["eq", "1", "10", "12"],
            # and with eq child: both operands must be 1-bit BV
            "81": ["and", "1", "80", "13"],
        }
        self.btor_smt = BTOR2SMT(self.btor)

    def test_const_translate(self):
        t = self.btor_smt._translate("12", "")
        self.assertIsNotNone(t)
        self.assertEqual(t.sort().bv_size(), 4)

    def test_state_translate(self):
        t = self.btor_smt._translate("10", "")
        self.assertIsNotNone(t)

    def test_ite_translate(self):
        t = self.btor_smt._translate("40", "")
        self.assertIsNotNone(t)
        self.assertEqual(t.sort().bv_size(), 4)

    def test_slice_oob_handles_gracefully(self):
        """Slice [12:12] on 10-bit input should return 1-bit zero (not None)."""
        t = self.btor_smt._translate("60", "")
        self.assertIsNotNone(t, "slice OOB should return zero, not None")
        self.assertEqual(t.sort().bv_size(), 1)

    def test_slice_oob_fully_out_of_range(self):
        """Slice [15:12] entirely out of range should return 4-bit zero."""
        btor2 = dict(self.btor)
        btor2["61"] = ["slice", "1", "11", "15", "12"]
        from smt_checker import BTOR2SMT
        btor_smt = BTOR2SMT(btor2)
        t = btor_smt._translate("61", "")
        self.assertIsNotNone(t, "fully OOB slice should return zero")
        self.assertEqual(t.sort().bv_size(), 4)

    def test_uext_source_index(self):
        """uext should translate p[2] as source, not p[3]."""
        t = self.btor_smt._translate("70", "")
        self.assertIsNotNone(t, "uext with fixed indices should return a term")
        self.assertEqual(t.sort().bv_size(), 6)

    def test_eq_produces_bv1(self):
        """eq should produce 1-bit BV, not Boolean."""
        t = self.btor_smt._translate("80", "")
        self.assertIsNotNone(t)
        self.assertTrue(t.sort().is_bv(), "eq result should be BV")
        self.assertEqual(t.sort().bv_size(), 1)

    def test_and_with_eq_child(self):
        """and with eq child should work (both operands are 1-bit BV)."""
        t = self.btor_smt._translate("81", "")
        self.assertIsNotNone(t, "and with eq child should succeed")
        self.assertEqual(t.sort().bv_size(), 1)

    def test_init_values_parsed(self):
        self.assertIn("state10", self.btor_smt.init_values)
        self.assertEqual(self.btor_smt.init_values["state10"], 0)

    def test_transition_constraints(self):
        constraints = self.btor_smt.get_transition_constraints()
        self.assertGreater(len(constraints), 0)

    def test_lemma_to_smt_guarded_implication(self):
        from smt_checker import lemma_to_smt
        l = "(=> (= state10 0) (= state10 0))"
        t = lemma_to_smt(l, self.btor_smt.state_vars, self.btor_smt.tm)
        self.assertIsNotNone(t)


class TestLemmaToSMT(unittest.TestCase):

    def setUp(self):
        from smt_checker import BTOR2SMT
        btor = {
            "1": ["sort", "bitvec", "1"],
            "5": ["sort", "bitvec", "4"],
            "10": ["state", "4", "s10"],
            "11": ["state", "1", "s11"],
        }
        self.btor_smt = BTOR2SMT(btor)

    def test_guarded_implication(self):
        from smt_checker import lemma_to_smt
        l = "(=> (= state10 10) (= state11 0))"
        t = lemma_to_smt(l, self.btor_smt.state_vars, self.btor_smt.tm)
        self.assertIsNotNone(t)

    def test_mutual_exclusion(self):
        from smt_checker import lemma_to_smt
        l = "(! (and (= state10 10) (= state11 1)))"
        t = lemma_to_smt(l, self.btor_smt.state_vars, self.btor_smt.tm)
        self.assertIsNotNone(t)

    def test_empty_lemma(self):
        from smt_checker import lemma_to_smt
        t = lemma_to_smt("", self.btor_smt.state_vars, self.btor_smt.tm)
        self.assertIsNone(t)


if __name__ == "__main__":
    unittest.main()
