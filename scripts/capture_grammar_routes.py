#!/usr/bin/env python3
"""Capture one frozen grammar-routing response for every paired view."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

import build_paired_corpus  # noqa: E402
from env_config import load_env  # noqa: E402
from experiment_manifest import file_sha256, stable_slug  # noqa: E402
import grammar_routes  # noqa: E402
import representation_views  # noqa: E402


CAPTURE_SCHEMA = "pono-llm-grammar-route-capture-v1"
INTEGRITY_SCHEMA = "pono-llm-grammar-route-integrity-v1"
SYSTEM_PROMPT = (
    "You route a formally checked invariant-synthesis grammar. Follow the user "
    "JSON contract exactly. Output one JSON object and no prose. Never claim "
    "that a route, predicate, invariant, or model is proved."
)
MAX_ROUTES = 8
FORMAL_CANDIDATE_CAP = 20000
PROVENANCE_FILES = (
    "scripts/capture_grammar_routes.py",
    "scripts/representation_views.py",
    "scripts/grammar_routes.py",
    "llm_worker/llm_client.py",
    "llm_worker/env_config.py",
    "llm_worker/openrouter_routing.py",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def verify_view_bundle(directory: Path) -> dict:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != representation_views.VIEW_SCHEMA:
        raise ValueError("representation bundle has the wrong schema")
    declared = manifest.get("bundle_sha256")
    computed = build_paired_corpus.canonical_sha256({
        key: value for key, value in manifest.items() if key != "bundle_sha256"
    })
    if declared != computed:
        raise ValueError(
            f"representation bundle hash mismatch: declared {declared}, got {computed}"
        )
    seen = set()
    for record in manifest["records"]:
        identity = (record["benchmark_id"], record["arm"])
        if identity in seen:
            raise ValueError(f"duplicate representation record: {identity}")
        seen.add(identity)
        path = directory / record["prompt_path"]
        if file_sha256(path) != record["prompt_sha256"]:
            raise ValueError(f"representation prompt hash mismatch: {path}")
    return manifest


def write_provenance(output: Path, view_manifest: dict, client) -> dict:
    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, text=True
    ).strip()
    git_status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=ROOT_DIR,
        text=True,
    )
    provenance = {
        "schema": "pono-llm-grammar-route-provenance-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "git_tracked_worktree_dirty": bool(git_status.strip()),
        "source_sha256": {
            path: file_sha256(ROOT_DIR / path) for path in PROVENANCE_FILES
        },
        "view_bundle_sha256": view_manifest["bundle_sha256"],
        "pilot_sha256": view_manifest["pilot_sha256"],
        "provider": client.provider,
        "model": client.model_name,
        "reasoning_effort": "none",
        "temperature": 0.0,
        "max_response_tokens": 2048,
        "response_normalization": "llm_client.extract_json",
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
    }
    (output / "system_prompt.txt").write_text(SYSTEM_PROMPT)
    (output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    return provenance


def parse_and_validate_route(
    response: str,
    btor2: Path,
    phase_count: int,
) -> tuple[dict | None, str, int, int]:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}", 0, 0
    if not isinstance(payload, dict):
        return None, "route response must be a JSON object", 0, 0
    routes_value = payload.get("routes")
    if not isinstance(routes_value, list) or not 1 <= len(routes_value) <= MAX_ROUTES:
        return None, f"route response must contain 1 to {MAX_ROUTES} routes", 0, 0
    try:
        routes = grammar_routes.compile_route_document(str(btor2), payload)
        global_entries = grammar_routes.expand_routes(
            str(btor2), routes, cap=FORMAL_CANDIDATE_CAP + 1
        )
    except (ValueError, KeyError, TypeError) as exc:
        return None, str(exc), 0, 0
    global_count = len(global_entries)
    all_phase_count = global_count * phase_count
    if global_count > FORMAL_CANDIDATE_CAP:
        return None, (
            f"route expands to {global_count} global candidates, above cap "
            f"{FORMAL_CANDIDATE_CAP}"
        ), global_count, all_phase_count
    if all_phase_count > FORMAL_CANDIDATE_CAP:
        return None, (
            f"route expands to {all_phase_count} all-phase candidates, above cap "
            f"{FORMAL_CANDIDATE_CAP}"
        ), global_count, all_phase_count
    return (
        json.loads(grammar_routes.canonical_route_document(routes)),
        "",
        global_count,
        all_phase_count,
    )


def write_integrity(output: Path, manifest_path: Path) -> dict:
    files = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "integrity.json":
            continue
        files.append({
            "path": path.relative_to(output).as_posix(),
            "sha256": file_sha256(path),
        })
    integrity = {
        "schema": INTEGRITY_SCHEMA,
        "status": "completed",
        "manifest_sha256": file_sha256(manifest_path),
        "files": files,
    }
    integrity["integrity_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in integrity.items() if key != "integrity_sha256"
    })
    (output / "integrity.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True) + "\n"
    )
    return integrity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view_bundle")
    parser.add_argument("translation_repo")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    view_dir = Path(args.view_bundle).resolve()
    view_manifest = verify_view_bundle(view_dir)
    translation_repo = Path(args.translation_repo).expanduser().resolve()
    build_paired_corpus.verify_repository(
        translation_repo,
        build_paired_corpus.TRANSLATION_REVISION,
        "translation",
    )
    output = Path(args.out)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite grammar-route capture: {output}")
    output.mkdir(parents=True)
    (output / "prompts").mkdir()
    (output / "responses").mkdir()
    (output / "routes").mkdir()
    (output / "metadata").mkdir()

    load_env()
    from llm_client import create_llm_client

    client = create_llm_client()
    provenance = write_provenance(output, view_manifest, client)
    records = []
    totals = {"tokens": 0, "latency_sec": 0.0, "valid": 0, "invalid": 0}
    for index, view in enumerate(view_manifest["records"], start=1):
        benchmark_id = view["benchmark_id"]
        arm = view["arm"]
        source_prompt = view_dir / view["prompt_path"]
        slug = stable_slug(benchmark_id)
        stem = f"{slug}.{arm}"
        prompt_relative = Path("prompts") / f"{stem}.txt"
        response_relative = Path("responses") / f"{stem}.txt"
        route_relative = Path("routes") / f"{stem}.json"
        meta_relative = Path("metadata") / f"{stem}.json"
        prompt_path = output / prompt_relative
        response_path = output / response_relative
        route_path = output / route_relative
        meta_path = output / meta_relative
        shutil.copyfile(source_prompt, prompt_path)
        prompt = prompt_path.read_text()
        if file_sha256(prompt_path) != view["prompt_sha256"]:
            raise ValueError(f"copied prompt hash mismatch: {benchmark_id}/{arm}")

        started = time.monotonic()
        response, tokens, api_latency_ms = client.call(
            prompt,
            system_prompt=SYSTEM_PROMPT,
            reasoning_effort="none",
            temperature=0.0,
            max_tokens=2048,
        )
        wall_latency = time.monotonic() - started
        response_path.write_text(response + "\n")
        btor2 = translation_repo / "translated/safety-func" / benchmark_id
        if file_sha256(btor2) != view["content_sha256"]:
            raise ValueError(f"BTOR2/view hash mismatch: {benchmark_id}")
        phase_count = parse_btor2_for_phase_count(btor2)
        canonical_route, error, global_count, all_phase_count = parse_and_validate_route(
            response, btor2, phase_count
        )
        valid = canonical_route is not None
        if valid:
            route_path.write_text(
                json.dumps(canonical_route, indent=2, sort_keys=True) + "\n"
            )
        stats = dict(getattr(client, "last_call_stats", {}))
        metadata = {
            "schema": "pono-llm-grammar-route-meta-v1",
            "benchmark_id": benchmark_id,
            "content_sha256": view["content_sha256"],
            "source_family_id": view["source_family_id"],
            "selection_role": view["selection_role"],
            "arm": arm,
            "provider": client.provider,
            "model": client.model_name,
            "prompt_path": prompt_relative.as_posix(),
            "prompt_sha256": file_sha256(prompt_path),
            "prompt_lexical_tokens": view["prompt_lexical_tokens"],
            "response_path": response_relative.as_posix(),
            "response_sha256": file_sha256(response_path),
            "route_path": route_relative.as_posix() if valid else None,
            "route_sha256": file_sha256(route_path) if valid else None,
            "route_valid": valid,
            "route_error": error,
            "route_count": len(canonical_route["routes"]) if valid else 0,
            "global_candidate_count": global_count,
            "all_phase_candidate_count": all_phase_count,
            "phase_count": phase_count,
            "wall_latency_sec": wall_latency,
            "api_latency_ms": float(api_latency_ms),
            "tokens": int(tokens or 0),
            "client_stats": stats,
        }
        meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        records.append({
            "benchmark_id": benchmark_id,
            "arm": arm,
            "metadata_path": meta_relative.as_posix(),
            "metadata_sha256": file_sha256(meta_path),
            "prompt_path": prompt_relative.as_posix(),
            "prompt_sha256": file_sha256(prompt_path),
            "response_path": response_relative.as_posix(),
            "response_sha256": file_sha256(response_path),
            "route_path": route_relative.as_posix() if valid else None,
            "route_sha256": file_sha256(route_path) if valid else None,
            "route_valid": valid,
        })
        totals["tokens"] += int(tokens or 0)
        totals["latency_sec"] += wall_latency
        totals["valid" if valid else "invalid"] += 1
        print(json.dumps({
            "completed": index,
            "total": len(view_manifest["records"]),
            "benchmark_id": benchmark_id,
            "arm": arm,
            "route_valid": valid,
            "route_error": error,
            "global_candidates": global_count,
            "all_phase_candidates": all_phase_count,
        }), flush=True)

    manifest = {
        "schema": CAPTURE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "view_bundle_sha256": view_manifest["bundle_sha256"],
        "pilot_sha256": view_manifest["pilot_sha256"],
        "provenance_sha256": file_sha256(output / "provenance.json"),
        "system_prompt_sha256": provenance["system_prompt_sha256"],
        "record_count": len(records),
        "valid_route_count": totals["valid"],
        "invalid_route_count": totals["invalid"],
        "total_tokens": totals["tokens"],
        "total_wall_latency_sec": totals["latency_sec"],
        "records": records,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    integrity = write_integrity(output, manifest_path)
    print(json.dumps({
        "record_count": manifest["record_count"],
        "valid_route_count": manifest["valid_route_count"],
        "invalid_route_count": manifest["invalid_route_count"],
        "total_tokens": manifest["total_tokens"],
        "total_wall_latency_sec": manifest["total_wall_latency_sec"],
        "manifest_sha256": file_sha256(manifest_path),
        "integrity_sha256": integrity["integrity_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


def parse_btor2_for_phase_count(path: Path) -> int:
    return len(grammar_routes.extract_functional_phases(str(path)))


if __name__ == "__main__":
    raise SystemExit(main())
