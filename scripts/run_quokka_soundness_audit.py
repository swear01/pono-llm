#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

from quokka_expression_purity import is_pure_expression

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_quokka_module(path: Path):
    inference = types.ModuleType("inference")
    inference.get_client = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("LLM disabled"))
    sglang = types.ModuleType("sglang")
    utils = types.ModuleType("sglang.utils")
    utils.terminate_process = lambda *args, **kwargs: None
    utils.wait_for_server = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("LLM disabled"))
    utils.launch_server_cmd = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("LLM disabled"))
    sys.modules["inference"] = inference
    sys.modules["sglang"] = sglang
    sys.modules["sglang.utils"] = utils
    spec = importlib.util.spec_from_file_location("pinned_quokka_batch", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned Quokka module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_verdict(stdout: bytes, returncode: int) -> str:
    if returncode == 124:
        return "TIMEOUT"
    for line in reversed(stdout.decode(errors="replace").splitlines()):
        if line.strip() in {"TRUE", "FALSE", "UNKNOWN"}:
            return line.strip()
    return "ERROR"


def run_verifier(upstream: Path, java: Path, source: Path, output: Path, timeout: int) -> dict[str, object]:
    tool = upstream / "tools/uautomizer"
    stdout_path = output.with_suffix(".stdout")
    stderr_path = output.with_suffix(".stderr")
    command = ["taskset", "-c", "0", "timeout", "--signal=TERM", "--kill-after=5s", f"{timeout}s",
               "python3", "-u", "Ultimate.py", "--spec", str(upstream / "Dataset/properties/unreach-call.prp"),
               "--file", str(source), "--architecture", "64bit", "--full-output"]
    environment = dict(os.environ)
    environment["PATH"] = f"{tool}:{java.parent}:{environment['PATH']}"
    start = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.run(command, cwd=tool, env=environment, stdout=stdout, stderr=stderr)
    wall = time.monotonic() - start
    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    parsed = parse_verdict(stdout, process.returncode)
    return {"command": command, "exit_code": process.returncode, "verdict": parsed, "result": parsed,
            "wall_time_sec": wall, "source_sha256": sha256(source), "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest()}


def validate_identities(inputs: dict[str, object], upstream: Path) -> None:
    target = inputs["external_target"]
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip() != target["commit"]:
        raise ValueError("upstream commit mismatch")
    if subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=upstream, text=True).strip() != target["repository"] + ".git":
        raise ValueError("upstream origin mismatch")
    for path_key, hash_key in (("batch_driver_path", "batch_driver_sha256"),
                               ("uautomizer_archive_path", "uautomizer_archive_sha256"),
                               ("uautomizer_wrapper_path", "uautomizer_wrapper_sha256")):
        if sha256(upstream / target[path_key]) != target[hash_key]:
            raise ValueError(f"identity mismatch: {target[path_key]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=ROOT / "scripts/quokka_soundness_inputs_v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/quokka_soundness_v1")
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text())
    validate_identities(inputs, args.upstream)
    module = load_quokka_module(args.upstream / inputs["external_target"]["batch_driver_path"])
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    original_results = {}
    for program in inputs["programs"]:
        directory = args.output / program["id"]
        directory.mkdir(parents=True, exist_ok=True)
        original = directory / "original.c"
        original.write_text(program["source"])
        original_result = run_verifier(args.upstream, args.java, original, directory / "original", inputs["timeouts"]["per_verifier_query_seconds"])
        if original_result["verdict"] != program["expected_original_verdict"]:
            raise RuntimeError(f"original control failed: {program['id']} {original_result['verdict']}")
        original_results[program["id"]] = original_result
        numbered = module.read_c_file_with_line_numbers(str(original))
        points = module.find_loop_invariant_insertion_points(numbered)
        for candidate in inputs["candidates"]:
            response = inputs["model_response_template"].format(loop_line=program["loop_line"], condition=candidate["condition"])
            extracted = module.extract_invariants_from_response(response)
            selected = module.validate_invariant_insertions(extracted, points)
            legacy_accept = selected is not None
            row = {"program_id": program["id"], "candidate_id": candidate["id"], "candidate_class": candidate["class"],
                   "condition": candidate["condition"], "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                   "insertion_points": points, "extracted": extracted, "legacy_accept": legacy_accept,
                   "strict_purity_accept": is_pure_expression(candidate["condition"], {"x"}),
                   "original": original_result, "llm_calls": 0, "fallback": False}
            if legacy_accept:
                row_dir = directory / candidate["id"]
                row_dir.mkdir(exist_ok=True)
                assume_temp = Path(module.insert_invariant_into_program(str(original), selected))
                assert_temp = Path(module.insert_invariant_as_assertion_and_remove_final_assert(str(original), selected))
                assume_source = row_dir / "assume.c"
                assert_source = row_dir / "assert.c"
                shutil.copyfile(assume_temp, assume_source)
                shutil.copyfile(assert_temp, assert_source)
                assume_temp.unlink()
                assert_temp.unlink()
                assume = run_verifier(args.upstream, args.java, assume_source, row_dir / "assume", inputs["timeouts"]["per_verifier_query_seconds"])
                assertion = run_verifier(args.upstream, args.java, assert_source, row_dir / "assert", inputs["timeouts"]["per_verifier_query_seconds"])
                aggregate = module.aggregate_verification_results(assume, assertion)
                row.update({"assume": assume, "assert": assertion, "aggregate": aggregate,
                            "false_safe": original_result["verdict"] == "FALSE" and aggregate == "TRUE"})
            else:
                row.update({"assume": None, "assert": None, "aggregate": "REJECTED", "false_safe": False})
            (directory / f"{candidate['id']}.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
            results.append(row)
            print(program["id"], candidate["id"], row["aggregate"], flush=True)
    attacks = [row for row in results if row["candidate_class"] == "side_effect_attack" and row["false_safe"]]
    mechanisms = {next(candidate["mechanism"] for candidate in inputs["candidates"] if candidate["id"] == row["candidate_id"])
                  for row in attacks}
    program_counts = {mechanism: len({row["program_id"] for row in attacks if next(
        candidate["mechanism"] for candidate in inputs["candidates"] if candidate["id"] == row["candidate_id"]) == mechanism})
                      for mechanism in mechanisms}
    mitigation = (all(row["strict_purity_accept"] for row in results if row["candidate_class"] == "pure_control") and
                  all(not row["strict_purity_accept"] for row in results if row["candidate_class"] != "pure_control") and
                  not any(row["false_safe"] and row["strict_purity_accept"] for row in results))
    summary = {"schema": "quokka-soundness-summary-v1", "row_count": len(results),
               "violation_count": len(attacks), "violation_confirmed": bool(attacks),
               "systematic_reproduction": sum(count >= 2 for count in program_counts.values()) >= 2,
               "mechanism_program_counts": program_counts, "mitigation_control_pass": mitigation,
               "environment_failure": False, "llm_calls": 0, "fallback_count": 0,
               "decisions": {
                   "Q_H1": "VIOLATION_CONFIRMED" if attacks else "NOT_CONFIRMED",
                   "Q_H2": "SYSTEMATIC_REPRODUCTION" if sum(count >= 2 for count in program_counts.values()) >= 2 else "NOT_SYSTEMATIC",
                   "Q_H3": "MITIGATION_CONTROL_PASS" if mitigation else "MITIGATION_CONTROL_FAIL",
               }}
    (args.output / "raw_results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    files = {str(path.relative_to(args.output)): sha256(path) for path in sorted(args.output.rglob("*")) if path.is_file() and path.name != "integrity.json"}
    (args.output / "integrity.json").write_text(json.dumps({"schema": "quokka-soundness-integrity-v1", "files": files}, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
