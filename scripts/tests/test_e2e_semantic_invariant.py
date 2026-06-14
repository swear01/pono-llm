"""
End-to-end integration tests for LLM_GEN_SEMANTIC mode.

Phase 1: Functional — verify Stage 0/2 JSONL plumbing works correctly.
Phase 2: Effectiveness — verify that injecting the correct predicate reduces
         IC3IA's CEGAR refinement iterations.
Phase 3: Stage 2 trigger — verify that Stage 2 fires automatically when IC3 gets stuck.

Requires: pono binary built at ../../build/pono
Tests are skipped if binary not found.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
ROOT = (HERE / "../..").resolve()
PONO_BIN = ROOT / "build" / "pono"

# Simple benchmark: always-true property (s stays 0); fast to prove.
TRIVIAL_BTOR2 = HERE / "../../tests/benchmarks/reset_sync.btor2"
# Effectiveness benchmark: ab_sync needs CEGAR without predicate injection.
AB_SYNC_BTOR2 = HERE / "../../tests/benchmarks/ab_sync.btor2"

SKIP_NO_PONO = pytest.mark.skipif(
    not PONO_BIN.exists(),
    reason=f"pono binary not found at {PONO_BIN}"
)
SKIP_NO_BENCH = pytest.mark.skipif(
    not AB_SYNC_BTOR2.exists(),
    reason=f"ab_sync.btor2 not found at {AB_SYNC_BTOR2}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_pono_semantic(btor2: Path, tmp_path: Path,
                       extra_args: List[str] = (),
                       timeout: int = 30) -> subprocess.CompletedProcess:
    req = tmp_path / "req.jsonl"
    resp = tmp_path / "resp.jsonl"
    cmd = [
        str(PONO_BIN), "-e", "ic3ia", "-v", "2",
        "--llm-gen-mode", "semantic",
        "--llm-req-path", str(req),
        "--llm-resp-path", str(resp),
        "-k", "20",
        *extra_args,
        str(btor2),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _watch_and_respond(req_path: Path, resp_path: Path,
                       candidates: list = None,
                       timeout: float = 25.0) -> Optional[dict]:
    """
    Background thread: wait for first Stage 0/2 request in req_path,
    then write a response to resp_path.  Returns the parsed request or None.
    """
    if candidates is None:
        candidates = []
    deadline = time.monotonic() + timeout
    seen_pos = 0
    while time.monotonic() < deadline:
        if req_path.exists():
            with open(req_path) as fh:
                fh.seek(seen_pos)
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    req_type = obj.get("type", "")
                    req_id = obj.get("request_id", "")
                    if req_type in ("ic3_stage0_request", "ic3_stage2_request") and req_id:
                        resp = {
                            "type": "ic3_invariant_response",
                            "request_id": req_id,
                            "candidates": candidates,
                        }
                        resp_path.write_text(json.dumps(resp) + "\n")
                        return obj
                seen_pos = req_path.stat().st_size if req_path.exists() else 0
        time.sleep(0.05)
    return None  # timeout


def _spawn_responder(req_path: Path, resp_path: Path,
                     candidates: list = None) -> threading.Thread:
    results: dict = {}

    def _worker():
        results["request"] = _watch_and_respond(req_path, resp_path, candidates)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.results = results
    return t


def _watch_all_requests(req_path: Path, resp_path: Path,
                        candidates_by_type: Dict[str, list],
                        max_requests: int = 2,
                        timeout: float = 90.0) -> List[dict]:
    """
    Background worker: respond to multiple requests by type.
    candidates_by_type: {"ic3_stage0_request": [...], "ic3_stage2_request": [...]}
    Returns list of all request objects handled.
    """
    seen_ids: set = set()
    handled: list = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and len(handled) < max_requests:
        if req_path.exists():
            with open(req_path) as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    req_type = obj.get("type", "")
                    req_id = obj.get("request_id", "")
                    if not req_id or req_id in seen_ids:
                        continue
                    if req_type not in candidates_by_type:
                        continue
                    seen_ids.add(req_id)
                    cands = candidates_by_type[req_type]
                    resp = {
                        "type": "ic3_invariant_response",
                        "request_id": req_id,
                        "candidates": cands,
                    }
                    # Append (multiple responses may coexist in same file)
                    with open(resp_path, "a") as rf:
                        rf.write(json.dumps(resp) + "\n")
                    handled.append(obj)
        time.sleep(0.05)
    return handled


def _spawn_multi_responder(req_path: Path, resp_path: Path,
                           candidates_by_type: Dict[str, list],
                           max_requests: int = 2) -> threading.Thread:
    results: dict = {"handled": []}

    def _worker():
        results["handled"] = _watch_all_requests(
            req_path, resp_path, candidates_by_type, max_requests)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.results = results
    return t


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if raw:
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines


def _cegar_predicate_count(stderr: str) -> int:
    """Count predicates added via CEGAR refinement in pono stderr."""
    return stderr.count("new predicates added by refinement")


# ===========================================================================
# Phase 1 — Functional / plumbing tests
# ===========================================================================


@SKIP_NO_PONO
class TestStage0Functional:
    def test_request_is_written(self, tmp_path):
        """pono writes a Stage 0 request to JSONL when run in semantic mode."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        # Respond immediately so pono doesn't block for 60 s
        t = _spawn_responder(req, resp, candidates=[])
        _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        assert req.exists(), "req.jsonl not created"
        objects = _read_jsonl(req)
        assert len(objects) >= 1, "no request line found"
        req0 = objects[0]
        assert req0["type"] == "ic3_stage0_request"

    def test_request_has_required_fields(self, tmp_path):
        """Stage 0 request contains all required fields."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[])
        _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        obj = _read_jsonl(req)[0]
        for field in ("type", "request_id", "btor2_path", "property_desc", "symbol_registry"):
            assert field in obj, f"missing field: {field}"
        assert obj["type"] == "ic3_stage0_request"
        assert obj["btor2_path"].endswith(".btor2")
        assert isinstance(obj["symbol_registry"], dict)

    def test_request_id_is_unique(self, tmp_path):
        """Each Stage 0 call gets a unique request_id."""
        req1 = tmp_path / "req1.jsonl"
        resp1 = tmp_path / "resp1.jsonl"
        req2 = tmp_path / "req2.jsonl"
        resp2 = tmp_path / "resp2.jsonl"

        def run(req, resp):
            t = _spawn_responder(req, resp, candidates=[])
            _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, extra_args=[
                "--llm-req-path", str(req),
                "--llm-resp-path", str(resp),
            ], timeout=30)
            t.join(timeout=5)
            return _read_jsonl(req)[0]["request_id"]

        id1 = run(req1, resp1)
        id2 = run(req2, resp2)
        assert id1 != id2, "request_ids should be unique"

    def test_empty_response_doesnt_crash(self, tmp_path):
        """pono handles an empty candidates list without crashing."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[])
        result = _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        assert result.returncode in (0, 1, 10, 20), \
            f"unexpected return code {result.returncode}"
        assert "Stage 0 injected 0/0 candidates" in result.stderr

    def test_response_polled_within_timeout(self, tmp_path):
        """Stage 0 response is consumed: pono logs 'Stage 0 injected'."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[])
        result = _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        assert "Stage 0" in result.stderr, \
            f"Stage 0 log not found in stderr:\n{result.stderr[:500]}"

    def test_stage0_responder_sees_btor2_path(self, tmp_path):
        """Stage 0 request's btor2_path points to the benchmark file."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[])
        _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        obj = _read_jsonl(req)[0]
        btor2_path = Path(obj["btor2_path"])
        assert btor2_path.exists(), f"btor2_path does not exist: {btor2_path}"
        assert btor2_path.suffix == ".btor2"


# ===========================================================================
# Phase 2 — Effectiveness tests
# ===========================================================================

# Predicate: state7 == state8  (a == b in ab_sync.btor2)
# This is the key invariant that eliminates all CEGAR refinement.
EQ_A_B_CANDIDATE = {
    "kind": "Type3_predicate",
    "predicate_ast": {
        "form": "eq",
        "args": [
            {"form": "ref", "ref": "state7"},
            {"form": "ref", "ref": "state8"},
        ],
    },
    "rationale": "a and b are always in sync",
}


@SKIP_NO_PONO
@SKIP_NO_BENCH
class TestStage0Effectiveness:
    def _baseline_cegar_count(self, tmp_path) -> tuple[int, str]:
        """Run WITHOUT semantic guidance; count CEGAR refinements."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        result = subprocess.run(
            [str(PONO_BIN), "-e", "ic3ia", "-v", "2", "-k", "30", str(AB_SYNC_BTOR2)],
            capture_output=True, text=True, timeout=60,
        )
        return _cegar_predicate_count(result.stderr), result.stderr

    def _guided_cegar_count(self, tmp_path, candidates: list) -> tuple[int, str]:
        """Run WITH semantic guidance + injected candidates; count CEGAR refinements."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=candidates)
        result = _run_pono_semantic(AB_SYNC_BTOR2, tmp_path, extra_args=["-k", "30"], timeout=60)
        t.join(timeout=5)
        return _cegar_predicate_count(result.stderr), result.stderr

    def test_baseline_needs_cegar(self, tmp_path):
        """Without guidance, IC3IA needs CEGAR refinements on ab_sync."""
        count, stderr = self._baseline_cegar_count(tmp_path)
        assert count > 0, \
            f"Expected CEGAR refinements on ab_sync.btor2 baseline, got 0.\n{stderr[:600]}"

    def test_correct_predicate_injected_and_accepted(self, tmp_path):
        """Injecting eq(state7,state8) is accepted by IC3IA (num_stage0_injected >= 1)."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[EQ_A_B_CANDIDATE])
        result = _run_pono_semantic(AB_SYNC_BTOR2, tmp_path, extra_args=["-k", "30"], timeout=60)
        t.join(timeout=5)

        # The Stage 0 log should show at least 1 injected candidate
        assert "Stage 0 injected" in result.stderr, \
            f"Stage 0 injection not logged:\n{result.stderr[:600]}"
        # Extract the injected count from "Stage 0 injected X/Y candidates"
        for line in result.stderr.splitlines():
            if "Stage 0 injected" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "injected":
                        frac = parts[i + 1]  # e.g. "1/1"
                        injected = int(frac.split("/")[0])
                        assert injected >= 1, \
                            f"Expected >= 1 injected candidate, got {injected}"
                        return
        pytest.fail("Could not parse 'Stage 0 injected' line")

    def test_correct_predicate_reduces_cegar(self, tmp_path):
        """Injecting eq(state7,state8) reduces IC3IA CEGAR refinement rounds."""
        tmp_base = tmp_path / "base"
        tmp_base.mkdir()
        tmp_guide = tmp_path / "guide"
        tmp_guide.mkdir()

        baseline_count, baseline_stderr = self._baseline_cegar_count(tmp_base)
        guided_count, guided_stderr = self._guided_cegar_count(tmp_guide, [EQ_A_B_CANDIDATE])

        assert baseline_count > 0, \
            f"Baseline should need CEGAR.\n{baseline_stderr[:300]}"
        assert guided_count < baseline_count, (
            f"Expected fewer CEGAR rounds with injection.\n"
            f"Baseline: {baseline_count} rounds\n"
            f"Guided:   {guided_count} rounds\n"
            f"--- Baseline stderr ---\n{baseline_stderr[:400]}\n"
            f"--- Guided stderr ---\n{guided_stderr[:400]}"
        )

    def test_wrong_predicate_rejected(self, tmp_path):
        """Injecting a predicate that violates init is rejected (injected == 0).

        Uses the fast reset_sync benchmark so the proof completes quickly;
        we're only testing the Stage 0 rejection logic, not proof speed.
        """
        # state7 (=b counter) > 200 is FALSE at init (b starts at 0) → init-unsafe.
        wrong_candidate = {
            "kind": "Type3_predicate",
            "predicate_ast": {
                "form": "ugt",
                "args": [
                    {"form": "ref", "ref": "state7"},
                    {"form": "const", "const": "200", "width": 8},
                ],
            },
            "rationale": "This is init-unsafe and should be rejected",
        }
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_responder(req, resp, candidates=[wrong_candidate])
        result = _run_pono_semantic(TRIVIAL_BTOR2, tmp_path, timeout=30)
        t.join(timeout=5)

        for line in result.stderr.splitlines():
            if "Stage 0 injected" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "injected":
                        injected = int(parts[i + 1].split("/")[0])
                        assert injected == 0, \
                            f"Expected 0 injected for init-unsafe predicate, got {injected}"
                        return
        pytest.fail("Stage 0 injection log line not found")


# ===========================================================================
# Phase 3 — Stage 2 trigger tests
# ===========================================================================


@SKIP_NO_PONO
@SKIP_NO_BENCH
class TestStage2Trigger:
    """Verify Stage 2 fires automatically when IC3 is stuck for >= 3 rounds.

    Uses ab_sync.btor2 (hard without the hint) with Stage 0 responding empty,
    so the stuck counter increments each IC3 step and T2_plateau fires after 3.
    A fake multi-responder handles both Stage 0 and the subsequent Stage 2 call.
    """

    def _run_with_multi_responder(self, tmp_path: Path, *,
                                  stage0_cands: list = None,
                                  stage2_cands: list = None,
                                  k: int = 8,
                                  timeout: int = 120) -> tuple:
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        t = _spawn_multi_responder(req, resp, {
            "ic3_stage0_request": stage0_cands or [],
            "ic3_stage2_request": stage2_cands or [],
        }, max_requests=2)
        result = subprocess.run(
            [str(PONO_BIN), "-e", "ic3ia", "-v", "2",
             "--llm-gen-mode", "semantic",
             "--llm-req-path", str(req),
             "--llm-resp-path", str(resp),
             "-k", str(k),
             str(AB_SYNC_BTOR2)],
            capture_output=True, text=True, timeout=timeout,
        )
        t.join(timeout=10)
        return result, t.results["handled"]

    def test_stage2_fires_within_3_steps(self, tmp_path):
        """Stage 2 request appears in JSONL after Stage 0 returns empty candidates."""
        result, handled = self._run_with_multi_responder(tmp_path)

        types_seen = [h["type"] for h in handled]
        assert "ic3_stage2_request" in types_seen, (
            f"Expected Stage 2 request; handled types: {types_seen}\n"
            f"--- stderr ---\n{result.stderr[:600]}"
        )

    def test_stage2_request_has_correct_fields(self, tmp_path):
        """Stage 2 request contains type, trigger, proof_state, cti_cluster."""
        result, handled = self._run_with_multi_responder(tmp_path)

        s2_reqs = [h for h in handled if h["type"] == "ic3_stage2_request"]
        assert s2_reqs, "No Stage 2 request found"
        req = s2_reqs[0]

        assert req["type"] == "ic3_stage2_request"
        assert req.get("trigger") in ("T1_cluster", "T2_plateau", "T3_budget"), \
            f"Unexpected trigger: {req.get('trigger')}"
        ps = req.get("proof_state", {})
        assert "frame_idx" in ps, "proof_state missing frame_idx"
        assert "total_cti_count" in ps, "proof_state missing total_cti_count"
        assert isinstance(req.get("cti_cluster"), list), "cti_cluster should be a list"

    def test_stage2_trigger_is_t2_plateau(self, tmp_path):
        """The trigger after 3 stuck rounds should be T2_plateau."""
        result, handled = self._run_with_multi_responder(tmp_path)

        s2_reqs = [h for h in handled if h["type"] == "ic3_stage2_request"]
        assert s2_reqs, "No Stage 2 request found"
        assert s2_reqs[0]["trigger"] == "T2_plateau", \
            f"Expected T2_plateau, got {s2_reqs[0].get('trigger')}"

    def test_stage2_pono_logs_trigger(self, tmp_path):
        """pono logs 'IC3: Stage 2 trigger=T2_plateau' in stderr."""
        result, handled = self._run_with_multi_responder(tmp_path)

        stage2_lines = [l for l in result.stderr.splitlines()
                        if "Stage 2 trigger" in l]
        assert stage2_lines, (
            f"Expected 'Stage 2 trigger' in stderr\n{result.stderr[:600]}"
        )

    def test_stage2_empty_response_no_crash(self, tmp_path):
        """Stage 2 empty response is handled gracefully (no crash)."""
        result, handled = self._run_with_multi_responder(
            tmp_path, stage2_cands=[])

        assert result.returncode in (0, 1, 255), \
            f"Unexpected return code {result.returncode}"
        assert "Stage 2" in result.stderr, \
            f"Stage 2 log not found in stderr\n{result.stderr[:600]}"
