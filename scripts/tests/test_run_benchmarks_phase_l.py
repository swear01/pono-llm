"""Phase L harness tests: LLM_STATS parsing, archive, CSV, manifest (no pono binary)."""

from __future__ import annotations

import csv
import json
import pathlib
import subprocess
import sys
from dataclasses import fields
from unittest import mock

import pytest

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS_DIR))

import run_benchmarks as rb  # noqa: E402


SAMPLE_LLM_STATS = (
    "LLM_STATS accepted=2 rejected=8 errors=0 requests=10 candidates=20 "
    "schema_fail=1 parse_fail=0 vocab_fail=0 induction_fail=3 "
    "rejected_initial=2 missing_block=0 lookup_miss=1 attempt_mismatch=0 "
    "budget_skip=0 predicates_added=2 batch_timeouts=1 "
    "batch_waits=5 batch_wait_ms_total=12345 batch_wait_ms_max=4000"
)


def _make_entry(path: str = "/data/hwmcc/2024/bv/p040.btor2") -> rb.BenchEntry:
    return rb.BenchEntry(path=path, year=2024, track="bv", expected="unsat")


def _populate_tmpdir(tmpdir: str, *, with_requests: bool = True) -> None:
    (pathlib.Path(tmpdir) / "llm_log.jsonl").write_text("{}\n")
    (pathlib.Path(tmpdir) / "responses.jsonl").write_text("{}\n")
    (pathlib.Path(tmpdir) / "sidecar_stderr.log").write_text("sidecar ok\n")
    if with_requests:
        (pathlib.Path(tmpdir) / "requests.jsonl").write_text('{"x":1}\n')


class TestParseLlmStats:
    def test_parses_all_fields(self):
        stderr = f"noise line\n{SAMPLE_LLM_STATS}\n"
        stats = rb._parse_llm_stats(stderr)
        assert stats["llm_accepted"] == 2
        assert stats["llm_rejected"] == 8
        assert stats["llm_requests"] == 10
        assert stats["llm_candidates"] == 20
        assert stats["llm_schema_fail"] == 1
        assert stats["llm_induction_fail"] == 3
        assert stats["llm_rejected_initial"] == 2
        assert stats["llm_lookup_miss"] == 1
        assert stats["llm_predicates_added"] == 2
        assert stats["llm_batch_timeouts"] == 1
        assert stats["llm_batch_waits"] == 5
        assert stats["llm_batch_wait_ms_total"] == 12345
        assert stats["llm_batch_wait_ms_max"] == 4000

    def test_uses_last_llm_stats_line(self):
        stderr = (
            "LLM_STATS accepted=0 rejected=0 errors=0 requests=1\n"
            f"{SAMPLE_LLM_STATS}\n"
        )
        stats = rb._parse_llm_stats(stderr)
        assert stats["llm_accepted"] == 2
        assert stats["llm_requests"] == 10

    def test_empty_stderr_returns_zeros(self):
        stats = rb._parse_llm_stats("")
        assert stats["llm_accepted"] == 0
        assert stats["llm_batch_timeouts"] == 0

    def test_skips_non_integer_values(self):
        stderr = "LLM_STATS accepted=bad rejected=3 errors=0"
        stats = rb._parse_llm_stats(stderr)
        assert stats["llm_accepted"] == 0
        assert stats["llm_rejected"] == 3


class TestParseLlmBatchWaits:
    def test_sums_wait_lines(self):
        stderr = "\n".join([
            "LLM_BATCH_WAIT batch_id=batch_f1_a1 wait_ms=50000 ok=1 samples=1/1",
            "LLM_BATCH_WAIT batch_id=batch_f2_a1 wait_ms=30000 ok=1 samples=1/1",
            "LLM_BATCH_WAIT batch_id=batch_f3_a1 wait_ms=300032 ok=0 samples=0/1",
        ])
        batch = rb._parse_llm_batch_waits_from_stderr(stderr)
        assert batch["llm_batch_waits"] == 3
        assert batch["llm_batch_wait_ms_total"] == 380032
        assert batch["llm_batch_wait_ms_max"] == 300032
        assert batch["llm_batch_timeouts"] == 1


class TestFallbackLlmStats:
    def test_uses_jsonl_when_no_llm_stats(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        log_path.write_text("{}\n" * 49)
        stats = rb._fallback_llm_stats_from_artifacts("", log_path=str(log_path))
        assert stats["llm_requests"] == 49
        assert stats["llm_accepted"] == 0

    def test_uses_batch_waits_from_stderr(self):
        stderr = "LLM_BATCH_WAIT batch_id=batch_f1_a1 wait_ms=73052 ok=1 samples=1/1\n"
        stats = rb._fallback_llm_stats_from_artifacts(stderr, log_path="")
        assert stats["llm_batch_waits"] == 1
        assert stats["llm_batch_wait_ms_total"] == 73052
        assert stats["llm_requests"] == 0

    def test_combined_jsonl_and_batch_waits(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        req_path = tmp_path / "requests.jsonl"
        log_path.write_text("{}\n" * 5)
        req_path.write_text('{"type":"ic3_frame_batch_request"}\n' * 7)
        stderr = "\n".join([
            "LLM_BATCH_WAIT batch_id=batch_f1_a1 wait_ms=50000 ok=1 samples=1/1",
            "LLM_BATCH_WAIT batch_id=batch_f2_a1 wait_ms=40000 ok=1 samples=1/1",
        ])
        stats = rb._fallback_llm_stats_from_artifacts(
            stderr, log_path=str(log_path), req_path=str(req_path)
        )
        assert stats["llm_requests"] == 7
        assert stats["llm_batch_waits"] == 2
        assert stats["llm_batch_wait_ms_total"] == 90000

    def test_prefers_requests_jsonl_over_llm_log(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        req_path = tmp_path / "requests.jsonl"
        log_path.write_text("{}\n" * 3)
        req_path.write_text('{"x":1}\n' * 9)
        stats = rb._fallback_llm_stats_from_artifacts(
            "", log_path=str(log_path), req_path=str(req_path)
        )
        assert stats["llm_requests"] == 9

    def test_llm_stats_takes_precedence(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        log_path.write_text("{}\n" * 10)
        stderr = f"{SAMPLE_LLM_STATS}\n"
        stats = rb._fallback_llm_stats_from_artifacts(stderr, log_path=str(log_path))
        assert stats["llm_requests"] == 10
        assert stats["llm_accepted"] == 2

    def test_run_pono_timeout_uses_fallback(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        log_path.write_text("{}\n" * 3)
        entry = _make_entry()
        fake_proc = mock.MagicMock()
        fake_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="pono", timeout=60),
            ("", ""),
        ]
        fake_proc.pid = 99

        with mock.patch("run_benchmarks.subprocess.Popen", return_value=fake_proc):
            with mock.patch("run_benchmarks.threading.Thread"):
                result, _ = rb.run_pono(
                    entry,
                    pathlib.Path("/fake/pono"),
                    "ic3ia",
                    10,
                    60,
                    "llm",
                    req_path="/tmp/r.jsonl",
                    resp_path="/tmp/s.jsonl",
                    log_path=str(log_path),
                )

        assert result.result == "timeout"
        assert result.llm_requests == 3

    def test_run_pono_timeout_populates_batch_waits(self, tmp_path):
        log_path = tmp_path / "llm_log.jsonl"
        req_path = tmp_path / "requests.jsonl"
        req_path.write_text('{"type":"ic3_frame_batch_request"}\n' * 4)
        entry = _make_entry()
        fake_proc = mock.MagicMock()
        stderr_on_kill = (
            "LLM_BATCH_WAIT batch_id=batch_f1_a1 wait_ms=50000 ok=1 samples=1/1\n"
        )
        fake_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="pono", timeout=60),
            ("", stderr_on_kill),
        ]
        fake_proc.pid = 99

        with mock.patch("run_benchmarks.subprocess.Popen", return_value=fake_proc):
            with mock.patch("run_benchmarks.threading.Thread"):
                result, _ = rb.run_pono(
                    entry,
                    pathlib.Path("/fake/pono"),
                    "ic3ia",
                    10,
                    60,
                    "llm",
                    req_path=str(req_path),
                    resp_path="/tmp/s.jsonl",
                    log_path=str(log_path),
                )

        assert result.result == "timeout"
        assert result.llm_requests == 4
        assert result.llm_batch_waits == 1
        assert result.llm_batch_wait_ms_total == 50000


class TestBenchSlug:
    def test_stable_slug(self):
        assert rb._bench_slug(_make_entry()) == "2024_bv_p040"

    def test_sanitizes_special_chars(self):
        entry = rb.BenchEntry(
            path="/x/2025/array/foo bar.btor2",
            year=2025,
            track="array",
            expected="sat",
        )
        assert rb._bench_slug(entry) == "2025_array_foo_bar"


class TestCountJsonlLines:
    def test_missing_file(self):
        assert rb._count_jsonl_lines("/nonexistent/file.jsonl") == 0

    def test_counts_lines(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text("a\nb\nc\n")
        assert rb._count_jsonl_lines(str(p)) == 3


class TestArchiveLlmArtifacts:
    def test_skips_requests_when_req_n_zero(self, tmp_path):
        td = tmp_path / "tmpdir"
        td.mkdir()
        _populate_tmpdir(str(td))
        dest = tmp_path / "archive"
        rb._archive_llm_artifacts(
            str(td), dest,
            pono_stderr="LLM_STATS accepted=1",
            req_n=0,
            archive_full_requests=False,
        )
        assert (dest / "llm_log.jsonl").is_file()
        assert (dest / "responses.jsonl").is_file()
        assert (dest / "sidecar_stderr.log").is_file()
        assert (dest / "pono_stderr.log").read_text().startswith("LLM_STATS")
        assert not (dest / "requests.jsonl").exists()

    def test_copies_requests_when_req_n_positive(self, tmp_path):
        td = tmp_path / "tmpdir"
        td.mkdir()
        _populate_tmpdir(str(td))
        dest = tmp_path / "archive"
        rb._archive_llm_artifacts(
            str(td), dest,
            pono_stderr="err",
            req_n=3,
            archive_full_requests=False,
        )
        assert (dest / "requests.jsonl").is_file()

    def test_archive_full_requests_forces_copy(self, tmp_path):
        td = tmp_path / "tmpdir"
        td.mkdir()
        _populate_tmpdir(str(td), with_requests=False)
        dest = tmp_path / "archive"
        rb._archive_llm_artifacts(
            str(td), dest,
            pono_stderr="",
            req_n=0,
            archive_full_requests=True,
        )
        assert not (dest / "requests.jsonl").exists()  # file absent in tmpdir


class TestCsvRoundtrip:
    def test_old_csv_backward_compatible(self, tmp_path):
        path = tmp_path / "old.csv"
        row = {
            "benchmark": "/a.btor2",
            "year": "2024",
            "track": "bv",
            "expected": "unsat",
            "mode": "llm",
            "result": "timeout",
            "wall_time": "1.5",
            "category": "timeout",
            "match": "false",
            "llm_accepted": "1",
            "llm_rejected": "2",
            "llm_errors": "0",
        }
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            w.writeheader()
            w.writerow(row)
        loaded = rb.load_results(path)
        assert len(loaded) == 1
        assert loaded[0].llm_accepted == 1
        assert loaded[0].llm_batch_timeouts == 0
        assert loaded[0].llm_requests == 0

    def test_full_csv_roundtrip(self, tmp_path):
        result = rb.RunResult(
            benchmark="/a.btor2",
            year=2024,
            track="bv",
            expected="unsat",
            mode="llm",
            result="timeout",
            wall_time=12.5,
            category="timeout",
            match=False,
            llm_accepted=1,
            llm_rejected=4,
            llm_errors=0,
            llm_requests=5,
            llm_candidates=15,
            llm_rejected_initial=2,
            llm_batch_timeouts=1,
        )
        path = tmp_path / "full.csv"
        rb.save_results([result], path)
        with path.open() as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            row = next(reader)
        assert "llm_batch_timeouts" in header
        assert row["llm_requests"] == "5"
        loaded = rb.load_results(path)
        assert loaded[0].llm_requests == 5
        assert loaded[0].llm_batch_timeouts == 1

    def test_result_fields_cover_dataclass(self):
        names = {f.name for f in fields(rb.RunResult)}
        assert set(rb.RESULT_FIELDS) == names


class TestRunManifest:
    def test_write_and_read_manifest(self, tmp_path):
        path = tmp_path / "runs" / "test_run" / "run_manifest.json"
        data = {
            "run_id": "test_run",
            "phase": "llm",
            "status": "running",
            "parallel": 8,
        }
        rb._write_run_manifest(path, data)
        loaded = json.loads(path.read_text())
        assert loaded["run_id"] == "test_run"
        assert loaded["parallel"] == 8

    def test_run_result_llm_summary(self):
        r = rb.RunResult(
            benchmark="/data/hwmcc/2024/bv/p040.btor2",
            year=2024,
            track="bv",
            expected="unsat",
            mode="llm",
            result="timeout",
            wall_time=100.2,
            category="timeout",
            match=False,
            llm_accepted=1,
            llm_rejected=3,
            llm_requests=5,
            llm_rejected_initial=2,
            llm_induction_fail=1,
            llm_batch_timeouts=0,
        )
        summary = rb._run_result_llm_summary(r)
        assert summary["slug"] == "2024_bv_p040"
        assert summary["llm_accepted"] == 1
        assert summary["llm_requests"] == 5


class TestParsePonoStdout:
    @pytest.mark.parametrize(
        "stdout,returncode,expected",
        [
            ("sat\nb0\n", 0, "sat"),
            ("unsat\nb0\n", 1, "unsat"),
            ("unknown\nb0\n", 2, "unknown"),
            ("error\nb0\n", 1, "error"),
            ("unsat\n", 0, "unsat"),
            ("", 0, "unknown"),
            ("", 1, "error"),
        ],
    )
    def test_parse_pono_stdout(self, stdout, returncode, expected):
        assert rb._parse_pono_stdout(stdout, returncode) == expected


class TestMergeBaselineResults:
    def _result(self, path: str, result: str = "sat") -> rb.RunResult:
        return rb.RunResult(
            benchmark=path,
            year=2024,
            track="bv",
            expected="sat",
            mode="baseline",
            result=result,
            wall_time=1.0,
            category="fast",
            match=True,
        )

    def test_merge_preserves_entry_order(self):
        entries = [
            rb.BenchEntry(path="/a/foo.btor2", year=2024, track="bv", expected="sat"),
            rb.BenchEntry(path="/a/bar.btor2", year=2024, track="bv", expected="unsat"),
            rb.BenchEntry(path="/a/baz.btor2", year=2024, track="bv", expected="sat"),
        ]
        partial = [self._result("/a/foo.btor2", "unsat")]
        new = [
            self._result("/a/bar.btor2", "sat"),
            self._result("/a/baz.btor2", "timeout"),
        ]
        merged = rb.merge_baseline_results(entries, partial, new)
        assert [r.benchmark for r in merged] == [e.path for e in entries]
        assert [r.result for r in merged] == ["unsat", "sat", "timeout"]


class TestParseBaselineNohupLog:
    def test_parse_start_done_pairs(self, tmp_path):
        log = tmp_path / "nohup.log"
        log.write_text(
            "[16:16:36]   [worker 0] starting: foo.btor2\n"
            "[16:16:37]   [worker 0] done: unknown 0.5s\n"
            "[16:16:37]   [worker 0] starting: bar.btor2\n"
            "[16:33:16]   [worker 3] done: timeout 1000.1s\n"
        )
        parsed = rb.parse_baseline_nohup_log(log)
        assert parsed == {
            "foo.btor2": ("unknown", 0.5),
            "bar.btor2": ("timeout", 1000.1),
        }


class TestRunPonoLlmStats:
    def test_run_pono_parses_llm_stats_from_stderr(self):
        entry = _make_entry()
        fake_proc = mock.MagicMock()
        fake_proc.communicate.return_value = ("unsat\n", f"info\n{SAMPLE_LLM_STATS}\n")
        fake_proc.returncode = 0
        fake_proc.poll.return_value = 0
        fake_proc.pid = 12345

        with mock.patch("run_benchmarks.subprocess.Popen", return_value=fake_proc):
            with mock.patch("run_benchmarks.threading.Thread"):
                result, stderr = rb.run_pono(
                    entry,
                    pathlib.Path("/fake/pono"),
                    "ic3ia",
                    10,
                    60,
                    "llm",
                    req_path="/tmp/r.jsonl",
                    resp_path="/tmp/s.jsonl",
                    log_path="/tmp/l.jsonl",
                )

        assert result.result == "unsat"
        assert result.llm_accepted == 2
        assert result.llm_requests == 10
        assert result.llm_batch_timeouts == 1
        assert "LLM_STATS" in stderr


class TestRunOneLlmArchive:
    def test_archives_after_run(self, tmp_path):
        entry = _make_entry()
        td = tmp_path / "job_tmp"
        td.mkdir()
        _populate_tmpdir(str(td))
        archive_dir = tmp_path / "runs" / "run1" / "2024_bv_p040"

        fake_result = rb.RunResult(
            benchmark=entry.path,
            year=entry.year,
            track=entry.track,
            expected=entry.expected,
            mode="llm",
            result="timeout",
            wall_time=1.0,
            category="timeout",
            match=False,
            llm_accepted=1,
            llm_requests=2,
        )
        fake_sidecar = mock.MagicMock()
        fake_sidecar.wait.return_value = 0

        job = {
            "entry": entry,
            "pono_bin": pathlib.Path("/fake/pono"),
            "engine": "ic3ia",
            "bound": 10,
            "timeout": 60,
            "accepted_budget": 50,
            "tmpdir": str(td),
            "sidecar_path": "/fake/sidecar.py",
            "prompt_dir": "/fake/prompts",
            "drain_sec": 0,
            "archive_dir": str(archive_dir),
            "archive_full_requests": False,
        }

        with mock.patch("run_benchmarks.subprocess.Popen", return_value=fake_sidecar):
            with mock.patch(
                "run_benchmarks.run_pono",
                return_value=(fake_result, "LLM_STATS accepted=1 rejected=0 errors=0 requests=2"),
            ):
                with mock.patch("run_benchmarks.time.sleep"):
                    out = rb._run_one_llm(job)

        assert out.llm_accepted == 1
        assert (archive_dir / "pono_stderr.log").is_file()
        assert (archive_dir / "llm_log.jsonl").is_file()
        assert (archive_dir / "requests.jsonl").is_file()


class TestSelectLlmTargetsByPhase:
    def _row(self, path: str, result: str, wall: float) -> rb.RunResult:
        cat = "fast" if wall < 30 else "medium" if wall < 500 else "slow"
        if result in ("timeout", "memout", "error"):
            cat = result
        return rb.RunResult(
            benchmark=path,
            year=2024,
            track="bv",
            expected="unsat",
            mode="baseline",
            result=result,
            wall_time=wall,
            category=cat,
            match=result == "unsat",
        )

    def test_phase_a_non_fast_solved(self):
        rows = [
            self._row("/a/fast.btor2", "unsat", 5.0),
            self._row("/a/medium.btor2", "sat", 45.0),
            self._row("/a/timeout.btor2", "timeout", 1000.0),
            self._row(f"/a/{rb.P040_BASENAME}", "unsat", 10.0),
        ]
        targets = rb.select_llm_targets_by_phase(rows, "a", fast_threshold=30.0)
        names = {pathlib.Path(t.benchmark).name for t in targets}
        assert "medium.btor2" in names
        assert "fast.btor2" not in names
        assert rb.P040_BASENAME in names

    def test_phase_b_timeout_memout(self):
        rows = [
            self._row("/a/fast.btor2", "unsat", 5.0),
            self._row("/a/to.btor2", "timeout", 1000.0),
            self._row("/a/mo.btor2", "memout", 200.0),
        ]
        targets = rb.select_llm_targets_by_phase(rows, "b", include_p040=False)
        assert len(targets) == 2
        assert {t.result for t in targets} == {"timeout", "memout"}

    def test_llm_results_csv_path(self, tmp_path):
        args = mock.MagicMock()
        args.output_dir = tmp_path
        args.llm_phase = "a"
        assert rb.llm_results_csv_path(args).name == "results_llm_phase_a.csv"
        args.llm_phase = "b"
        assert rb.llm_results_csv_path(args).name == "results_llm_phase_b.csv"
        args.llm_phase = "competition"
        assert rb.llm_results_csv_path(args).name == "results_llm.csv"


class TestMainFindSolvableIntegration:
    def test_find_solvable_phase_writes_empty_candidates(self, tmp_path):
        argv = [
            "run_benchmarks.py",
            "--phase", "find-solvable",
            "--output-dir", str(tmp_path),
            "--hwmcc-dir", str(tmp_path / "hwmcc"),
            "--find-max", "5",
        ]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(rb, "run_phase_download", return_value=True):
                with mock.patch.object(rb, "run_find_solvable", return_value=[]):
                    rc = rb.main()
        assert rc == 0
        out = tmp_path / "candidates.json"
        assert out.is_file()
        data = json.loads(out.read_text())
        assert data["candidate_count"] == 0
        assert data["candidates"] == []
        assert data["find_max"] == 5

    def test_find_solvable_phase_writes_nonempty_candidates(self, tmp_path):
        candidates = [{
            "name": "p040.btor2",
            "path": "/x/p040.btor2",
            "expected": "unsat",
            "blocking_phases": 3,
            "wall_time": 45.2,
            "comp_category": "medium",
        }]
        argv = [
            "run_benchmarks.py",
            "--phase", "find-solvable",
            "--output-dir", str(tmp_path),
            "--hwmcc-dir", str(tmp_path / "hwmcc"),
        ]
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(rb, "run_phase_download", return_value=True):
                with mock.patch.object(rb, "run_find_solvable", return_value=candidates):
                    assert rb.main() == 0
        data = json.loads((tmp_path / "candidates.json").read_text())
        assert data["candidate_count"] == 1
        assert data["candidates"][0]["blocking_phases"] == 3


class TestRunPhaseLlmManifest:
    def test_writes_run_manifest_on_done(self, tmp_path):
        br = rb.RunResult(
            benchmark="/data/hwmcc/2024/bv/p040.btor2",
            year=2024,
            track="bv",
            expected="unsat",
            mode="baseline",
            result="timeout",
            wall_time=100.0,
            category="timeout",
            match=False,
        )
        args = mock.MagicMock()
        args.output_dir = tmp_path
        args.run_id = "test_run_001"
        args.parallel = 2
        args.snapshot_max_clauses = 0
        args.llm_model = "test-model"
        args.llm_drain_sec = 300
        args.memory_limit = 14.0
        args.engine = "ic3ia"
        args.bound = 10
        args.timeout = 60
        args.llm_accepted_budget = 50
        args.llm_max_requests = 0
        args.archive_full_requests = False
        args.llm_phase = "competition"

        fake_llm_result = rb.RunResult(
            benchmark=br.benchmark,
            year=br.year,
            track=br.track,
            expected=br.expected,
            mode="llm",
            result="timeout",
            wall_time=50.0,
            category="timeout",
            match=False,
            llm_accepted=1,
            llm_requests=2,
        )
        comp_entry = mock.MagicMock()
        comp_entry.category = "medium"
        comp_map = {"2024/bv/p040.btor2": comp_entry}

        with mock.patch.object(rb, "_resolve_pono", return_value=pathlib.Path("/fake/pono")):
            with mock.patch.object(rb, "_resolve_sidecar", return_value=pathlib.Path("/fake/sidecar.py")):
                with mock.patch.object(rb, "_resolve_prompt_dir", return_value=tmp_path / "prompts"):
                    (tmp_path / "prompts").mkdir()
                    with mock.patch.object(rb, "_run_one_llm", return_value=fake_llm_result):
                        with mock.patch.object(rb, "ThreadPoolExecutor") as ex_cls:
                            fut = mock.MagicMock()
                            fut.result.return_value = fake_llm_result
                            ex = mock.MagicMock()
                            ex.__enter__.return_value = ex
                            ex.submit.return_value = fut
                            ex_cls.return_value = ex
                            with mock.patch.object(rb, "as_completed", return_value=[fut]):
                                results = rb.run_phase_llm(args, [br], comp_map)

        assert len(results) == 1
        manifest_path = tmp_path / "runs" / "test_run_001" / "run_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "done"
        assert manifest["run_id"] == "test_run_001"
        assert manifest["completed_count"] == 1
        assert len(manifest["benchmarks"]) == 1
        assert manifest["benchmarks"][0]["slug"] == "2024_bv_p040"
