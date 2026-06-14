"""
Live LLM integration tests — call real DeepSeek API via the sidecar.

These tests require DEEPSEEK_API_KEY to be set (in .env or environment).
They are skipped automatically if no key is configured.

What is tested:
  1. Stage 0 round-trip: pono writes request → sidecar calls DeepSeek → pono
     reads response → pono logs "Stage 0 injected X/Y candidates".
  2. Effectiveness: if DeepSeek correctly suggests eq(state7,state8), IC3IA
     proves ab_sync.btor2 without CEGAR refinements.
  3. Stage 2 round-trip: when Stage 0 injection doesn't help, Stage 2 fires
     and the sidecar handles it too.

Requires: pono binary at ../../build/pono, sidecar at ../../llm_worker/sidecar.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
ROOT = (HERE / "../..").resolve()
PONO_BIN = ROOT / "build" / "pono"
LLM_WORKER = ROOT / "llm_worker"
SIDECAR_PY = LLM_WORKER / "sidecar.py"
AB_SYNC_BTOR2 = ROOT / "tests" / "benchmarks" / "ab_sync.btor2"
DOT_ENV = ROOT / ".env"


# ---------------------------------------------------------------------------
# Key availability check (no import of llm_worker — just env look-up)
# ---------------------------------------------------------------------------

def _load_dot_env() -> None:
    """Load .env if present, without requiring python-dotenv."""
    if not DOT_ENV.exists():
        return
    for line in DOT_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val


_load_dot_env()

_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

SKIP_NO_KEY = pytest.mark.skipif(
    not _DEEPSEEK_API_KEY,
    reason="DEEPSEEK_API_KEY not set — skipping live LLM tests",
)
SKIP_NO_PONO = pytest.mark.skipif(
    not PONO_BIN.exists(),
    reason=f"pono binary not found at {PONO_BIN}",
)
SKIP_NO_BENCH = pytest.mark.skipif(
    not AB_SYNC_BTOR2.exists(),
    reason=f"ab_sync.btor2 not found at {AB_SYNC_BTOR2}",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _cegar_count(stderr: str) -> int:
    return stderr.count("new predicates added by refinement")


def _start_sidecar(req: Path, resp: Path, log: Path,
                   max_requests: int = 1) -> subprocess.Popen:
    """Launch sidecar.py as a background process from llm_worker/."""
    env = os.environ.copy()
    env.setdefault("LLM_PROVIDER", "deepseek")
    return subprocess.Popen(
        [
            sys.executable, str(SIDECAR_PY),
            "--req-path", str(req),
            "--resp-path", str(resp),
            "--log-path", str(log),
            "--provider", "deepseek",
            "--model", "deepseek-v4-pro",
            "--max-requests", str(max_requests),
            "--poll-interval", "0.5",
        ],
        cwd=str(LLM_WORKER),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def _start_pono(req: Path, resp: Path, btor2: Path, k: int = 50) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(PONO_BIN), "-e", "ic3ia", "-v", "2",
            "--llm-gen-mode", "semantic",
            "--llm-req-path", str(req),
            "--llm-resp-path", str(resp),
            "-k", str(k),
            str(btor2),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_file_line(path: Path, keyword: str, timeout: float = 90.0) -> bool:
    """Poll until a line containing keyword appears in path."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                if keyword in path.read_text():
                    return True
            except OSError:
                pass
        time.sleep(0.2)
    return False


# ===========================================================================
# Live LLM tests
# ===========================================================================


@SKIP_NO_KEY
@SKIP_NO_PONO
@SKIP_NO_BENCH
class TestLiveLLMStage0:
    """Stage 0 round-trip with real DeepSeek API."""

    def test_sidecar_handles_stage0_request(self, tmp_path):
        """sidecar.py reads Stage 0 request, calls DeepSeek, writes response."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        log = tmp_path / "log.jsonl"

        sidecar = _start_sidecar(req, resp, log, max_requests=1)
        pono = _start_pono(req, resp, AB_SYNC_BTOR2, k=5)

        try:
            # Wait for response to appear (sidecar → API → write)
            resp_appeared = _wait_for_file_line(resp, "ic3_invariant_response", timeout=120)
            assert resp_appeared, "sidecar did not write response within 120s"

            pono.wait(timeout=90)
        finally:
            sidecar.kill()
            sidecar.wait(timeout=5)
            try:
                pono.kill()
            except Exception:
                pass

        pono_stderr = pono.stderr.read() if pono.stderr else ""
        assert "Stage 0 injected" in pono_stderr, (
            f"pono did not log 'Stage 0 injected'\n{pono_stderr[:600]}"
        )

    def test_stage0_response_is_valid_json(self, tmp_path):
        """Response file contains valid ic3_invariant_response JSON."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        log = tmp_path / "log.jsonl"

        sidecar = _start_sidecar(req, resp, log, max_requests=1)
        pono = _start_pono(req, resp, AB_SYNC_BTOR2, k=5)

        try:
            _wait_for_file_line(resp, "ic3_invariant_response", timeout=120)
            pono.wait(timeout=90)
        finally:
            sidecar.kill()
            sidecar.wait(timeout=5)
            try:
                pono.kill()
            except Exception:
                pass

        responses = _read_jsonl(resp)
        assert responses, "resp.jsonl is empty"
        r = responses[0]
        assert r.get("type") == "ic3_invariant_response", \
            f"Wrong type: {r.get('type')}"
        assert "request_id" in r, "response missing request_id"
        assert isinstance(r.get("candidates"), list), "candidates should be a list"

    def test_stage0_request_id_echoed_in_response(self, tmp_path):
        """Response request_id matches the request."""
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        log = tmp_path / "log.jsonl"

        sidecar = _start_sidecar(req, resp, log, max_requests=1)
        pono = _start_pono(req, resp, AB_SYNC_BTOR2, k=5)

        try:
            _wait_for_file_line(resp, "ic3_invariant_response", timeout=120)
            pono.wait(timeout=90)
        finally:
            sidecar.kill()
            sidecar.wait(timeout=5)
            try:
                pono.kill()
            except Exception:
                pass

        requests = _read_jsonl(req)
        responses = _read_jsonl(resp)
        assert requests and responses, "req or resp JSONL is empty"
        req_id = requests[0]["request_id"]
        resp_id = responses[0]["request_id"]
        assert req_id == resp_id, \
            f"request_id mismatch: req={req_id!r} resp={resp_id!r}"


@SKIP_NO_KEY
@SKIP_NO_PONO
@SKIP_NO_BENCH
class TestLiveLLMEffectiveness:
    """DeepSeek should suggest eq(state7,state8) and reduce CEGAR rounds."""

    def test_deepseek_stage0_reduces_cegar_or_proves(self, tmp_path):
        """
        With real DeepSeek on ab_sync.btor2:
        - If LLM suggests eq(state7,state8): IC3IA proves immediately (0 CEGAR rounds).
        - At minimum: Stage 0 round-trip completed and pono logged 'Stage 0 injected'.

        Strategy: wait for Stage 0 response to appear, then give pono 30 extra seconds
        to prove if the injection was good.  Kill pono after that so the test is bounded.
        Collect pono stderr from the pipe in a background thread to avoid blocking.
        """
        req = tmp_path / "req.jsonl"
        resp = tmp_path / "resp.jsonl"
        log = tmp_path / "log.jsonl"

        # Collect pono stderr asynchronously
        import threading, io
        stderr_buf = io.StringIO()
        stderr_lock = threading.Lock()

        sidecar = _start_sidecar(req, resp, log, max_requests=1)
        pono = _start_pono(req, resp, AB_SYNC_BTOR2, k=200)

        def _drain_stderr():
            for line in pono.stderr:
                with stderr_lock:
                    stderr_buf.write(line)

        drain_t = threading.Thread(target=_drain_stderr, daemon=True)
        drain_t.start()

        try:
            # Wait for Stage 0 response from DeepSeek
            resp_appeared = _wait_for_file_line(resp, "ic3_invariant_response", timeout=120)
            assert resp_appeared, "sidecar did not write Stage 0 response within 120s"

            # Give pono up to 30s more to complete if predicate was injected correctly
            try:
                pono.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass  # pono still running — that's ok, we'll kill it
        finally:
            sidecar.kill()
            sidecar.wait(timeout=5)
            pono.kill()
            pono.wait(timeout=5)

        drain_t.join(timeout=3)
        with stderr_lock:
            pono_stderr = stderr_buf.getvalue()

        assert "Stage 0 injected" in pono_stderr, (
            f"pono did not log 'Stage 0 injected'\n{pono_stderr[:600]}"
        )

        # Check what happened: either proved OR at least attempted with >= 0 injections
        proved = (pono.returncode == 1)
        cegar_count = _cegar_count(pono_stderr)

        if proved:
            # Best outcome: DeepSeek suggested the correct predicate; no CEGAR needed
            assert cegar_count == 0, \
                f"Proved but with {cegar_count} CEGAR rounds — unexpected"
        # If not proved within 30s after response, that's ok — Stage 0 round-trip
        # still validated.  The fake-responder effectiveness tests verify the
        # actual speedup guarantee; live tests just verify the pipeline works.


@SKIP_NO_KEY
@SKIP_NO_BENCH
class TestLiveLLMStage2:
    """Stage 2 API integration with real DeepSeek.

    We test handle_stage2_request directly (bypassing pono timing constraints)
    so API latency doesn't interact with pono's 30-second Stage 2 timeout.
    """

    def _make_client(self):
        sys.path.insert(0, str(LLM_WORKER))
        from llm_client import create_llm_client
        return create_llm_client(
            provider="deepseek",
            api_key=_DEEPSEEK_API_KEY,
            model_name="deepseek-v4-pro",
        )

    def _stage2_request(self) -> dict:
        return {
            "type": "ic3_stage2_request",
            "request_id": "live_s2_test_001",
            "benchmark": "ab_sync",
            "property_desc": "c never becomes 1 (top bit of a XOR b)",
            "btor2_path": str(AB_SYNC_BTOR2),
            "trigger": "T2_plateau",
            "proof_state": {
                "frame_idx": 3,
                "total_cti_count": 4,
                "frame_clause_count": 2,
            },
            "cti_cluster": [
                {"state7": "5", "state8": "3", "state9": "0"},
                {"state7": "200", "state8": "198", "state9": "0"},
            ],
        }

    def test_stage2_direct_api_returns_response(self):
        """handle_stage2_request calls DeepSeek and returns ic3_invariant_response."""
        sys.path.insert(0, str(LLM_WORKER))
        from invariant_sidecar import handle_stage2_request

        client = self._make_client()
        result = handle_stage2_request(client, self._stage2_request())

        assert result["type"] == "ic3_invariant_response"
        assert result["request_id"] == "live_s2_test_001"
        assert isinstance(result["candidates"], list)

    def test_stage2_direct_api_response_is_parseable(self):
        """Stage 2 candidates each have predicate_ast and kind fields."""
        sys.path.insert(0, str(LLM_WORKER))
        from invariant_sidecar import handle_stage2_request

        client = self._make_client()
        result = handle_stage2_request(client, self._stage2_request())

        for cand in result["candidates"]:
            assert "predicate_ast" in cand, f"candidate missing predicate_ast: {cand}"
            assert "kind" in cand, f"candidate missing kind: {cand}"
            ast = cand["predicate_ast"]
            assert isinstance(ast, dict), "predicate_ast should be a dict"
            assert "form" in ast, "predicate_ast missing 'form'"

    def test_stage2_btor2_enrichment_reaches_prompt(self):
        """Stage 2 request enrichment adds hot_variables from ab_sync.btor2."""
        sys.path.insert(0, str(LLM_WORKER))
        from invariant_sidecar import _enrich_request_with_btor2

        req = self._stage2_request()
        enriched = _enrich_request_with_btor2(req)

        assert "hot_variables" in enriched, "BTOR2 enrichment failed"
        refs = {hv["ref"] for hv in enriched["hot_variables"]}
        # ab_sync.btor2 has state7, state8, state9 near the bad node
        assert refs & {"state7", "state8", "state9"}, \
            f"Expected state7/8/9 in hot_variables; got {refs}"
