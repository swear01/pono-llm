#!/usr/bin/env python3
"""Offline LLM proposal/repair driver for Pono replay experiments."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

from deepseek_client import DeepSeekClient


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_template(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / name
    return path.read_text(encoding="utf-8")


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response does not contain a JSON object")
    return json.loads(text[start : end + 1])


def literal_ids(cti: Dict[str, Any]) -> set[int]:
    return {int(lit["id"]) for lit in cti.get("literals", [])}


def normalize_proposal(row: Dict[str, Any], cti: Dict[str, Any]) -> Dict[str, Any]:
    valid = literal_ids(cti)
    keep = [int(x) for x in row.get("keep_ids", []) if int(x) in valid]
    drop = [int(x) for x in row.get("drop_ids", []) if int(x) in valid and int(x) not in keep]
    if not drop:
        drop = sorted(valid - set(keep))
    return {
        "schema_version": 1,
        "cti_id": cti["cti_id"],
        "mode": "proposal",
        "keep_ids": keep,
        "drop_ids": drop,
        "confidence": str(row.get("confidence", "low")),
        "short_reason": str(row.get("short_reason", ""))[:500],
    }


def normalize_repair(row: Dict[str, Any], req: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {int(d["literal_id"]) for d in req.get("sat_witness_diff", [])}
    add_back = [int(x) for x in row.get("add_back_ids", []) if int(x) in allowed]
    return {
        "schema_version": 1,
        "cti_id": req["cti_id"],
        "mode": "repair",
        "base_keep_ids": [int(x) for x in req.get("failed_keep_ids", [])],
        "add_back_ids": add_back,
        "confidence": str(row.get("confidence", "low")),
        "short_reason": str(row.get("short_reason", ""))[:500],
    }


def cmd_propose(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    static_context = read_json(replay_dir / "static_context.json")
    ctis = read_jsonl(replay_dir / "cti_contexts.jsonl")[: args.max_ctis]
    existing = {r.get("cti_id") for r in read_jsonl(replay_dir / "proposals.jsonl")}
    template = load_template("offline_proposal.txt")
    client = DeepSeekClient(model_name=args.model or None)

    for cti in ctis:
        if cti.get("cti_id") in existing:
            continue
        prompt = template.format(
            static_context=json.dumps(static_context, ensure_ascii=False, sort_keys=True),
            cti_context=json.dumps(cti, ensure_ascii=False, sort_keys=True),
        )
        text, tokens, latency = client.call(prompt, model_name=args.model or None)
        try:
            raw = extract_json_object(text)
            row = normalize_proposal(raw, cti)
        except Exception as exc:  # noqa: BLE001 - preserve invalid response in JSONL
            row = {
                "schema_version": 1,
                "cti_id": cti["cti_id"],
                "mode": "proposal",
                "keep_ids": [],
                "drop_ids": [],
                "confidence": "low",
                "short_reason": f"invalid_json: {exc}",
            }
        row["token_count"] = tokens
        row["latency_ms"] = latency
        append_jsonl(replay_dir / "proposals.jsonl", row)
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    static_context = read_json(replay_dir / "static_context.json")
    cti_by_id = {r["cti_id"]: r for r in read_jsonl(replay_dir / "cti_contexts.jsonl")}
    requests = read_jsonl(replay_dir / "repair_requests.jsonl")[: args.max_ctis]
    existing = {r.get("cti_id") for r in read_jsonl(replay_dir / "repairs.jsonl")}
    template = load_template("offline_repair.txt")
    client = DeepSeekClient(model_name=args.model or None)

    for req in requests:
        cti_id = req.get("cti_id")
        if cti_id in existing or cti_id not in cti_by_id:
            continue
        prompt = template.format(
            static_context=json.dumps(static_context, ensure_ascii=False, sort_keys=True),
            cti_context=json.dumps(cti_by_id[cti_id], ensure_ascii=False, sort_keys=True),
            repair_request=json.dumps(req, ensure_ascii=False, sort_keys=True),
        )
        text, tokens, latency = client.call(prompt, model_name=args.model or None)
        try:
            raw = extract_json_object(text)
            row = normalize_repair(raw, req)
        except Exception as exc:  # noqa: BLE001 - preserve invalid response in JSONL
            row = {
                "schema_version": 1,
                "cti_id": cti_id,
                "mode": "repair",
                "base_keep_ids": [int(x) for x in req.get("failed_keep_ids", [])],
                "add_back_ids": [],
                "confidence": "low",
                "short_reason": f"invalid_json: {exc}",
            }
        row["token_count"] = tokens
        row["latency_ms"] = latency
        append_jsonl(replay_dir / "repairs.jsonl", row)
    return 0


def count_status(rows: Iterable[Dict[str, Any]], status: str) -> int:
    return sum(1 for r in rows if r.get("status") == status)


def cmd_summarize(args: argparse.Namespace) -> int:
    replay_dir = Path(args.replay_dir)
    ctis = read_jsonl(replay_dir / "cti_contexts.jsonl")
    proposals = read_jsonl(replay_dir / "proposals.jsonl")
    repairs = read_jsonl(replay_dir / "repairs.jsonl")
    proposal_results = read_jsonl(replay_dir / "proposal_replay_results.jsonl")
    repair_results = read_jsonl(replay_dir / "repair_replay_results.jsonl")
    summary = {
        "num_ctis": len(ctis),
        "proposal_records": len(proposals),
        "proposal_accepts": count_status(proposal_results, "accepted_initial"),
        "proposal_sat_failures": count_status(proposal_results, "sat_failed_initial"),
        "repair_requests": len(read_jsonl(replay_dir / "repair_requests.jsonl")),
        "repair_records": len(repairs),
        "repair_accepts": count_status(repair_results, "repair_accepted"),
        "repair_sat_failures": count_status(repair_results, "repair_sat_failed"),
        "invalid_llm_json": sum(
            1 for r in proposals + repairs if "invalid_json" in r.get("short_reason", "")
        ),
    }
    (replay_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Pono LLM repair replay driver")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("propose", "repair", "summarize"):
        p = sub.add_parser(name)
        p.add_argument("--replay-dir", required=True)
        p.add_argument("--model", default=os.environ.get("PONO_LLM_MODEL", ""))
        p.add_argument("--max-ctis", type=int, default=50)
    args = parser.parse_args()
    if args.cmd == "propose":
        return cmd_propose(args)
    if args.cmd == "repair":
        return cmd_repair(args)
    if args.cmd == "summarize":
        return cmd_summarize(args)
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
