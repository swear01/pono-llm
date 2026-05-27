#!/usr/bin/env python3
"""Step 4 fixture tests: verify parser behavior without calling the LLM.

Run: python3 -m pytest llm_worker/tests/test_batch_parser.py -v
  or: python3 llm_worker/tests/test_batch_parser.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deepseek_client import extract_json


# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXTURE_A_VALID_ARRAY = json.dumps({
    "batch_id": "B01",
    "candidates": [
        {
            "candidate_id": "B01_C01_001",
            "cluster_id": "C01",
            "lemma": "!(a && b)",
            "schema": "mutual_exclusion",
            "variables_used": ["a", "b"],
            "intuition": "a and b cannot both be true",
            "risk_level": "low",
        },
        {
            "candidate_id": "B01_C01_002",
            "cluster_id": "C01",
            "lemma": "(=> (= a 1) (= b 0))",
            "schema": "guarded_implication",
            "variables_used": ["a", "b"],
            "intuition": "if a is set then b must be clear",
            "risk_level": "medium",
        },
    ],
})

FIXTURE_B_SINGLE_OBJECT = json.dumps({
    "candidate_id": "B01_C01_001",
    "cluster_id": "C01",
    "lemma": "!(a && b)",
    "schema": "mutual_exclusion",
})

FIXTURE_C_MARKDOWN_FENCED = (
    "```json\n"
    + json.dumps({
        "batch_id": "B01",
        "candidates": [
            {
                "candidate_id": "B01_C01_001",
                "cluster_id": "C01",
                "lemma": "!(a && b)",
                "schema": "mutual_exclusion",
            },
            {
                "candidate_id": "B01_C01_002",
                "cluster_id": "C01",
                "lemma": "(=> (= a 1) (= b 0))",
                "schema": "guarded_implication",
            },
        ],
    })
    + "\n```"
)

FIXTURE_D_MALFORMED_WITH_ARRAY = (
    '{"batch_id": "B01", "candidates": ['
    '{"candidate_id": "B01_C01_001", "lemma": "!(a && b)", "schema": "mutual_exclusion"},'
    '{"candidate_id": "B01_C01_002", "lemma": "(=> (= a 1) (= b 0))", "schema": "guarded_implication"}'
    ']}'
)

FIXTURE_E_PREAMBLE = (
    "Here is the JSON output as requested:\n\n"
    + json.dumps({
        "batch_id": "B01",
        "candidates": [
            {"candidate_id": "B01_C01_001", "lemma": "!(a && b)", "schema": "mutual_exclusion"},
            {"candidate_id": "B01_C01_002", "lemma": "(=> a b)", "schema": "guarded_implication"},
        ],
    })
)


def parse_candidates_from_text(text: str) -> list:
    """Replicate the sidecar's template-guided parsing logic."""
    extracted = extract_json(text)
    try:
        result = json.loads(extracted)
        candidates = result.get("candidates", [])
        if not candidates and "lemma" in result:
            candidates = [result]
        return candidates
    except (json.JSONDecodeError, AttributeError):
        return []


class TestExtractJson(unittest.TestCase):

    def test_fixture_a_valid_array_gives_two_candidates(self):
        """Fixture A: valid array must yield 2 candidates, not 1."""
        candidates = parse_candidates_from_text(FIXTURE_A_VALID_ARRAY)
        self.assertEqual(
            len(candidates), 2,
            f"Expected 2 candidates from valid array, got {len(candidates)}: {candidates}",
        )

    def test_fixture_b_single_object_fallback_gives_one(self):
        """Fixture B: single object → fallback wraps it into list of 1."""
        candidates = parse_candidates_from_text(FIXTURE_B_SINGLE_OBJECT)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].get("lemma"), "!(a && b)")

    def test_fixture_c_markdown_fenced_gives_two(self):
        """Fixture C: markdown-fenced JSON array → 2 candidates after fence strip."""
        candidates = parse_candidates_from_text(FIXTURE_C_MARKDOWN_FENCED)
        self.assertEqual(
            len(candidates), 2,
            f"Fence stripping failed. Got {len(candidates)}: {candidates}",
        )

    def test_fixture_d_malformed_recoverable_gives_two(self):
        """Fixture D: structurally valid (just hand-crafted) JSON → 2 candidates."""
        candidates = parse_candidates_from_text(FIXTURE_D_MALFORMED_WITH_ARRAY)
        self.assertEqual(
            len(candidates), 2,
            f"Expected 2 from recoverable JSON, got {len(candidates)}",
        )

    def test_fixture_e_preamble_extracted_via_marker(self):
        """Fixture E: response with leading prose → extract_json must find JSON via 'candidates' marker."""
        extracted = extract_json(FIXTURE_E_PREAMBLE)
        try:
            result = json.loads(extracted)
            candidates = result.get("candidates", [])
            self.assertEqual(
                len(candidates), 2,
                f"Preamble extraction failed. Got {len(candidates)}. "
                f"extracted={extracted[:200]}",
            )
        except json.JSONDecodeError as e:
            self.fail(f"extract_json returned non-parseable text: {e}\nextracted={extracted[:300]}")

    def test_empty_response_returns_empty(self):
        """Empty / whitespace response → 0 candidates."""
        self.assertEqual(parse_candidates_from_text(""), [])
        self.assertEqual(parse_candidates_from_text("   "), [])

    def test_array_not_dict_returns_empty(self):
        """Top-level JSON array (not object) → 0 candidates (no 'candidates' key)."""
        text = json.dumps([{"lemma": "!(a && b)"}])
        candidates = parse_candidates_from_text(text)
        self.assertEqual(candidates, [])


class TestSidecarResponseFile(unittest.TestCase):
    """Verify that write_response + read-all-lines yields the correct count."""

    def setUp(self):
        import importlib.util, os
        # Import write_response from jsonl_protocol
        spec = importlib.util.spec_from_file_location(
            "jsonl_protocol",
            os.path.join(os.path.dirname(__file__), "..", "jsonl_protocol.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.write_response = mod.write_response

    def test_multiple_writes_all_readable(self):
        """Writing N candidates one-per-line and reading all lines must yield N."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            # Simulate sidecar writing 3 candidates
            for i in range(3):
                self.write_response(path, {
                    "candidate_id": f"B01_C01_{i+1:03d}",
                    "lemma": f"lemma_{i}",
                    "schema": "mutual_exclusion",
                    "type": "template_lemma",
                })

            # Read all lines (the fixed consumer approach)
            candidates = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        candidates.append(json.loads(line))

            self.assertEqual(
                len(candidates), 3,
                f"Expected 3, got {len(candidates)}",
            )
        finally:
            os.unlink(path)

    def test_readline_only_gives_one(self):
        """Sanity check: the OLD f.readline() pattern only reads 1 of N candidates."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            for i in range(3):
                self.write_response(path, {"candidate_id": f"c{i}", "lemma": f"l{i}"})

            with open(path) as f:
                only_first = json.loads(f.readline())

            self.assertEqual(only_first["candidate_id"], "c0",
                             "readline reads first line — confirms original bug behavior")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
