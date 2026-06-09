#!/usr/bin/env python3
"""Phase Q0 accept-rate diagnosis from Phase A CSV + archived JSONL artifacts.

Reads harness CSV and per-benchmark archive (requests/responses/llm_log).
Writes JSON + markdown reports under --output (default: diagnosis/).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BENCH_SLUG_RE = re.compile(r"^(\d{4})_(\w+)_(.+)$")
BATCH_ID_RE = re.compile(r"^(batch_f\d+)_a(\d+)$")
LIT_RE = re.compile(r"^!?((?:state|input)\d+)=(.+)$")


def bench_slug(path: str, year: str, track: str) -> str:
    stem = re.sub(r"[^\w.-]+", "_", Path(path).stem)
    return f"{year}_{track}_{stem}"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_batch_id(batch_id: str) -> tuple[str, int]:
    m = BATCH_ID_RE.match(batch_id or "")
    if not m:
        return batch_id or "", 1
    return m.group(1), int(m.group(2))


def collect_clauses(resp: dict[str, Any]) -> list[list[dict[str, Any]]]:
    clauses = resp.get("block_clauses") or []
    if clauses:
        return [list(c) for c in clauses]
    disjuncts = resp.get("block_disjuncts") or []
    if disjuncts:
        return [list(disjuncts)]
    return []


def disjunct_count(clause: list[dict[str, Any]]) -> int:
    return len(clause)


def format_disjunct(dj: dict[str, Any]) -> str:
    ref = dj.get("ref", "")
    op = dj.get("op", "eq")
    rhs = dj.get("rhs", "")
    pol = dj.get("polarity", True)
    prefix = "" if pol else "!"
    return f"{prefix}{ref}{op}{rhs}"


def clause_disjunct_text(clause: list[dict[str, Any]]) -> list[str]:
    return [format_disjunct(d) for d in clause]


def top_digest_literals(req: dict[str, Any], n: int = 5) -> list[str]:
    digest = req.get("cti_digest") or {}
    stats = digest.get("literal_stats") or []
    out: list[str] = []
    for row in stats[:n]:
        lit = str(row.get("lit", "")).strip()
        if lit:
            out.append(lit)
    if out:
        return out
    # fallback: scrape literals from cti_entries
    for ent in req.get("cti_entries") or []:
        for lit in ent.get("literals") or []:
            if isinstance(lit, str):
                out.append(lit)
    return out[:n]


def negate_top1_mic_clause(top_lit: str) -> list[dict[str, Any]] | None:
    """Mechanical MIC-style single literal from digest top-1 (heuristic)."""
    m = LIT_RE.match(top_lit.strip())
    if not m:
        return None
    negated = top_lit.startswith("!")
    ref, rhs = m.group(1), m.group(2)
    # Block clause must be false on the CTI literal: negate digest polarity.
    return [{"ref": ref, "op": "eq", "rhs": rhs, "polarity": negated}]


def matches_single_disjunct(clause: list[dict[str, Any]], target: list[dict[str, Any]]) -> bool:
    if len(clause) != 1 or len(target) != 1:
        return False
    a, b = clause[0], target[0]
    keys = ("ref", "op", "rhs", "polarity")
    return all(a.get(k) == b.get(k) for k in keys)


def tier_from_path(path: str) -> str:
    p = path.lower()
    if "ila_rocket" in p or "/ila_" in p:
        return "ila"
    if "microban" in p:
        return "microban"
    if "zipcpu" in p:
        return "zipcpu"
    if "qspiflash" in p:
        return "qspiflash"
    if "riscv_formal" in p:
        return "riscv"
    return "other"


@dataclass
class CsvRow:
    benchmark: str
    year: str
    track: str
    slug: str
    accepted: int
    rejected: int
    requests: int
    candidates: int
    rejected_initial: int
    induction_fail: int
    vocab_fail: int
    parse_fail: int
    result: str
    match: bool
    tier: str


@dataclass
class BenchArtifacts:
    slug: str
    path: Path
    requests: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    llm_log: list[dict[str, Any]] = field(default_factory=list)
    parallel_samples: int = 1
    max_block_clauses: int = 3


def load_csv(csv_path: Path) -> list[CsvRow]:
    rows: list[CsvRow] = []
    with csv_path.open() as f:
        for r in csv.DictReader(f):
            year = r.get("year", "")
            track = r.get("track", "")
            bench = r["benchmark"]
            rows.append(
                CsvRow(
                    benchmark=bench,
                    year=year,
                    track=track,
                    slug=bench_slug(bench, year, track),
                    accepted=int(r.get("llm_accepted") or 0),
                    rejected=int(r.get("llm_rejected") or 0),
                    requests=int(r.get("llm_requests") or 0),
                    candidates=int(r.get("llm_candidates") or 0),
                    rejected_initial=int(r.get("llm_rejected_initial") or 0),
                    induction_fail=int(r.get("llm_induction_fail") or 0),
                    vocab_fail=int(r.get("llm_vocab_fail") or 0),
                    parse_fail=int(r.get("llm_parse_fail") or 0),
                    result=r.get("result", ""),
                    match=(r.get("match", "").lower() == "true"),
                    tier=tier_from_path(bench),
                )
            )
    return rows


def load_bench_artifacts(archive: Path, slug: str) -> BenchArtifacts:
    d = archive / slug
    art = BenchArtifacts(
        slug=slug,
        path=d,
        requests=load_jsonl(d / "requests.jsonl"),
        responses=load_jsonl(d / "responses.jsonl"),
        llm_log=load_jsonl(d / "llm_log.jsonl"),
    )
    if art.requests:
        art.parallel_samples = int(art.requests[0].get("parallel_samples") or 1)
        art.max_block_clauses = int(art.requests[0].get("max_block_clauses") or 3)
    return art


def phase_d0(csv_rows: list[CsvRow], archive: Path) -> dict[str, Any]:
    with_req = [r for r in csv_rows if r.requests > 0]
    inventory: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    for row in with_req:
        art = load_bench_artifacts(archive, row.slug)
        req_n = len(art.requests)
        resp_n = len(art.responses)
        expected_resp = req_n * art.parallel_samples
        entry = {
            "slug": row.slug,
            "tier": row.tier,
            "csv_requests": row.requests,
            "jsonl_requests": req_n,
            "jsonl_responses": resp_n,
            "parallel_samples": art.parallel_samples,
            "max_block_clauses": art.max_block_clauses,
            "has_requests": (art.path / "requests.jsonl").exists(),
            "has_responses": (art.path / "responses.jsonl").exists(),
            "has_llm_log": (art.path / "llm_log.jsonl").exists(),
        }
        inventory.append(entry)
        if req_n != row.requests:
            mismatches.append(
                {
                    "slug": row.slug,
                    "csv_requests": row.requests,
                    "jsonl_requests": req_n,
                }
            )
        if resp_n and expected_resp and abs(resp_n - expected_resp) > art.parallel_samples:
            entry["response_mismatch"] = {
                "expected_about": expected_resp,
                "actual": resp_n,
            }

    return {
        "archive": str(archive),
        "benchmarks_total": len(csv_rows),
        "benchmarks_with_requests": len(with_req),
        "artifacts_complete": sum(
            1
            for e in inventory
            if e["has_requests"] and e["has_responses"]
        ),
        "csv_jsonl_request_mismatches": mismatches,
        "inventory": inventory,
    }


def phase_d1(csv_rows: list[CsvRow]) -> dict[str, Any]:
    with_req = [r for r in csv_rows if r.requests > 0]
    total_req = sum(r.requests for r in with_req)
    total_cand = sum(r.candidates for r in with_req)
    total_acc = sum(r.accepted for r in with_req)
    total_ri = sum(r.rejected_initial for r in with_req)
    total_if = sum(r.induction_fail for r in with_req)

    def rate(num: int, den: int) -> float:
        return round(100.0 * num / den, 3) if den else 0.0

    by_tier: dict[str, dict[str, Any]] = {}
    for tier in sorted({r.tier for r in with_req}):
        subset = [r for r in with_req if r.tier == tier]
        den = sum(r.requests for r in subset)
        by_tier[tier] = {
            "cases": len(subset),
            "requests": den,
            "accepted": sum(r.accepted for r in subset),
            "accept_per_request_pct": rate(sum(r.accepted for r in subset), den),
            "rejected_initial": sum(r.rejected_initial for r in subset),
            "induction_fail": sum(r.induction_fail for r in subset),
        }

    accept_cases = [r for r in with_req if r.accepted > 0]
    zero_accept_high_ri = sorted(
        [r for r in with_req if r.accepted == 0 and r.requests >= 10],
        key=lambda r: (-r.rejected_initial, -r.requests),
    )[:10]

    return {
        "totals": {
            "requests": total_req,
            "candidates": total_cand,
            "accepted": total_acc,
            "accept_per_request_pct": rate(total_acc, total_req),
            "accept_per_candidate_pct": rate(total_acc, total_cand),
            "rejected_initial": total_ri,
            "rejected_initial_per_request": round(total_ri / total_req, 3) if total_req else 0,
            "induction_fail": total_if,
            "induction_fail_per_request": round(total_if / total_req, 3) if total_req else 0,
            "reject_reason_share": {
                "rejected_initial": rate(total_ri, total_ri + total_if),
                "induction_fail": rate(total_if, total_ri + total_if),
            },
        },
        "accept_cases": [
            {
                "slug": r.slug,
                "tier": r.tier,
                "accepted": r.accepted,
                "requests": r.requests,
                "accept_rate_pct": rate(r.accepted, r.requests),
                "rejected_initial": r.rejected_initial,
                "induction_fail": r.induction_fail,
            }
            for r in sorted(accept_cases, key=lambda x: -x.accepted)
        ],
        "zero_accept_high_reject_subset": [
            {
                "slug": r.slug,
                "tier": r.tier,
                "requests": r.requests,
                "rejected_initial": r.rejected_initial,
                "induction_fail": r.induction_fail,
            }
            for r in zero_accept_high_ri
        ],
        "by_tier": by_tier,
    }


def analyze_responses(art: BenchArtifacts) -> dict[str, Any]:
    clause_disjunct_hist: Counter[int] = Counter()
    response_clause_counts: Counter[int] = Counter()
    sample_ids: Counter[int] = Counter()
    mic_match = 0
    mic_total = 0
    single_disjunct_clauses = 0
    total_clauses = 0

    req_by_batch: dict[str, dict[str, Any]] = {}
    for req in art.requests:
        bid = req.get("batch_id") or req.get("cti_id") or ""
        req_by_batch[bid] = req

    for resp in art.responses:
        sample_ids[int(resp.get("sample_id") or 0)] += 1
        clauses = collect_clauses(resp)
        response_clause_counts[len(clauses)] += 1
        bid = resp.get("source_cti_id") or ""
        req = req_by_batch.get(bid) or {}
        top_lits = top_digest_literals(req)
        mic = negate_top1_mic_clause(top_lits[0]) if top_lits else None
        for clause in clauses:
            total_clauses += 1
            clause_disjunct_hist[disjunct_count(clause)] += 1
            if disjunct_count(clause) == 1:
                single_disjunct_clauses += 1
            if mic:
                mic_total += 1
                if matches_single_disjunct(clause, mic):
                    mic_match += 1

    return {
        "responses": len(art.responses),
        "requests": len(art.requests),
        "parallel_samples": art.parallel_samples,
        "clause_disjunct_hist": dict(sorted(clause_disjunct_hist.items())),
        "response_clause_counts": dict(sorted(response_clause_counts.items())),
        "sample_id_hist": dict(sorted(sample_ids.items())),
        "single_disjunct_clause_pct": round(
            100.0 * single_disjunct_clauses / total_clauses, 1
        )
        if total_clauses
        else 0.0,
        "mic_top1_shape_pct": round(100.0 * mic_match / mic_total, 1) if mic_total else None,
        "total_clauses": total_clauses,
    }


def parse_witness_value_tag(val: str) -> str:
    v = str(val)
    if v in ("#b0", "0", "false"):
        return "init0"
    if v in ("#b1", "1", "true"):
        return "init1"
    return "init_wide"


def disjunct_true_at_witness_ref(
    dj: dict[str, Any], witness_ref: str, witness_val: str
) -> bool | None:
    """Heuristic: is this disjunct true when witness_ref has witness_val at init?"""
    if dj.get("ref") != witness_ref:
        return None
    rv = parse_val(dj.get("rhs", ""))
    wv = parse_val(witness_val)
    if isinstance(rv, int) and isinstance(wv, int):
        eq = rv == wv
    else:
        eq = str(rv) == str(wv)
    pol = dj.get("polarity", True)
    return eq if pol else (not eq)


def cti_refs_from_request(req: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for ent in req.get("cti_entries") or []:
        cti = ent.get("cti") or {}
        for lit in (cti.get("cube") or {}).get("literals") or []:
            atom = lit.get("atom") or {}
            if atom.get("ref"):
                refs.add(str(atom["ref"]))
        for lit in ent.get("literals") or []:
            m = re.search(r"((?:state|input)\d+)", str(lit))
            if m:
                refs.add(m.group(1))
    for row in (req.get("cti_digest") or {}).get("literal_stats") or []:
        m = re.search(r"((?:state|input)\d+)", str(row.get("lit", "")))
        if m:
            refs.add(m.group(1))
    return refs


def parse_val(val: str) -> int | str:
    v = str(val)
    if v.startswith("#b"):
        return int(v[2:] or "0", 2)
    if v in ("true", "false"):
        return 1 if v == "true" else 0
    try:
        return int(v)
    except ValueError:
        return v


def classify_rejected_initial_entry(
    fb: dict[str, Any],
    resp: dict[str, Any] | None,
    cti_refs: set[str],
) -> dict[str, Any]:
    wit = fb.get("witness") or {}
    wref = str(wit.get("ref") or "")
    wval = str(wit.get("next_value") or "")
    if not wref:
        return {"category": "no_witness"}
    if not resp:
        return {"category": "no_response_match", "witness": wit}

    clauses = collect_clauses(resp)
    if not clauses:
        return {"category": "empty_response", "witness": wit}

    last_clause = clauses[-1]
    refs_in_last = {str(d.get("ref") or "") for d in last_clause}
    wit_in_cti = wref in cti_refs
    wit_disjuncts = [d for d in last_clause if d.get("ref") == wref]
    wit_lit_true = any(
        disjunct_true_at_witness_ref(d, wref, wval) is True for d in wit_disjuncts
    )

    if wref not in refs_in_last:
        cat = "A_witness_not_in_last_clause"
    elif len(last_clause) == 1:
        cat = (
            "B1_single_witness_lit_true_at_init"
            if wit_lit_true
            else "B2_single_witness_lit_false_at_witness"
        )
    elif wit_lit_true:
        cat = "C1_multi_witness_lit_true_at_init"
    else:
        cat = "C2_multi_or_other_disjunct_at_init"

    dj = last_clause[0] if len(last_clause) == 1 else None
    pattern = None
    if cat == "B1_single_witness_lit_true_at_init" and dj:
        pattern = (
            f"{parse_witness_value_tag(wval)}_clause_eq_{dj.get('rhs')}_pol_{dj.get('polarity', True)}"
        )
    elif cat == "B2_single_witness_lit_false_at_witness" and dj:
        pattern = (
            f"{parse_witness_value_tag(wval)}_clause_eq_{str(dj.get('rhs'))[:16]}"
            f"_pol_{dj.get('polarity', True)}"
        )

    return {
        "category": cat,
        "witness": wit,
        "witness_in_cti": wit_in_cti,
        "last_clause_disjuncts": len(last_clause),
        "response_clauses": len(clauses),
        "pattern": pattern,
        "last_clause": last_clause,
        "source_cti_id": resp.get("source_cti_id"),
        "attempt": resp.get("attempt"),
    }


def analyze_feedback(art: BenchArtifacts) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    witness_refs: Counter[str] = Counter()
    witness_by_reason: dict[str, Counter[str]] = defaultdict(Counter)
    feedback_entries = 0

    for req in art.requests:
        for fb in req.get("feedback") or []:
            feedback_entries += 1
            reason = str(fb.get("reason") or "unknown")
            reason_counts[reason] += 1
            wit = fb.get("witness") or {}
            ref = str(wit.get("ref") or "")
            if ref:
                witness_refs[ref] += 1
                witness_by_reason[reason][ref] += 1

    return {
        "feedback_entries": feedback_entries,
        "reason_counts": dict(reason_counts.most_common()),
        "top_witness_refs": witness_refs.most_common(10),
        "top_witness_by_reason": {
            k: v.most_common(5) for k, v in witness_by_reason.items()
        },
    }


def phase_d2(csv_rows: list[CsvRow], archive: Path) -> dict[str, Any]:
    accept_rows = [r for r in csv_rows if r.accepted > 0]
    compare_zero = [
        r
        for r in csv_rows
        if r.accepted == 0 and r.requests >= 10 and r.slug.endswith("p040")
        or (r.accepted == 0 and r.requests >= 10 and r.rejected_initial >= 10)
    ][:5]

    def summarize_subset(rows: list[CsvRow], label: str) -> dict[str, Any]:
        stats = []
        agg_disjunct = Counter()
        agg_single = []
        agg_mic = []
        for row in rows:
            art = load_bench_artifacts(archive, row.slug)
            s = analyze_responses(art)
            s["slug"] = row.slug
            s["accepted"] = row.accepted
            s["accept_rate_pct"] = round(100 * row.accepted / row.requests, 2) if row.requests else 0
            stats.append(s)
            for k, v in (s.get("clause_disjunct_hist") or {}).items():
                agg_disjunct[int(k)] += v
            if s.get("single_disjunct_clause_pct") is not None:
                agg_single.append(s["single_disjunct_clause_pct"])
            if s.get("mic_top1_shape_pct") is not None:
                agg_mic.append(s["mic_top1_shape_pct"])
        return {
            "label": label,
            "cases": len(rows),
            "per_case": stats,
            "aggregate_disjunct_hist": dict(sorted(agg_disjunct.items())),
            "mean_single_disjunct_clause_pct": round(statistics.mean(agg_single), 1)
            if agg_single
            else None,
            "mean_mic_top1_shape_pct": round(statistics.mean(agg_mic), 1) if agg_mic else None,
        }

    p040 = [r for r in csv_rows if r.slug.endswith("p040") and r.requests > 0]
    return {
        "accept_positive": summarize_subset(accept_rows, "S+ accept cases"),
        "zero_accept_contrast": summarize_subset(compare_zero, "S0 high-fail contrast"),
        "p040": summarize_subset(p040, "S* p040"),
    }


def phase_d3(csv_rows: list[CsvRow], archive: Path) -> dict[str, Any]:
    with_req = [r for r in csv_rows if r.requests > 0]
    global_reason: Counter[str] = Counter()
    global_witness: Counter[str] = Counter()
    per_tier_reason: dict[str, Counter[str]] = defaultdict(Counter)
    high_fail_details: list[dict[str, Any]] = []

    high_fail = sorted(
        [r for r in with_req if r.accepted == 0 and r.requests >= 10],
        key=lambda r: -r.rejected_initial,
    )[:10]

    for row in with_req:
        art = load_bench_artifacts(archive, row.slug)
        fb = analyze_feedback(art)
        for reason, count in (fb.get("reason_counts") or {}).items():
            global_reason[reason] += count
            per_tier_reason[row.tier][reason] += count
        for ref, count in fb.get("top_witness_refs") or []:
            global_witness[ref] += count

    for row in high_fail:
        art = load_bench_artifacts(archive, row.slug)
        high_fail_details.append(
            {
                "slug": row.slug,
                "tier": row.tier,
                "requests": row.requests,
                "rejected_initial": row.rejected_initial,
                "feedback": analyze_feedback(art),
            }
        )

    total_fb = sum(global_reason.values())
    return {
        "feedback_entries": total_fb,
        "reason_counts": dict(global_reason.most_common()),
        "reason_share_pct": {
            k: round(100.0 * v / total_fb, 1) for k, v in global_reason.most_common()
        }
        if total_fb
        else {},
        "top_witness_refs": global_witness.most_common(20),
        "by_tier_reason": {k: dict(v.most_common()) for k, v in per_tier_reason.items()},
        "high_fail_top10": high_fail_details,
    }


def phase_d3b(csv_rows: list[CsvRow], archive: Path) -> dict[str, Any]:
    """Fine-grained rejected_initial / init-semantics taxonomy from feedback+responses."""
    with_req = [r for r in csv_rows if r.requests > 0]
    categories: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    init_val_tags: Counter[str] = Counter()
    last_clause_sizes: Counter[int] = Counter()
    witness_in_cti: Counter[str] = Counter()
    by_tier: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    p040_rows: list[dict[str, Any]] = []

    total_ri = 0
    for row in with_req:
        art = load_bench_artifacts(archive, row.slug)
        if not art.requests:
            continue
        resps = {
            (
                r.get("source_cti_id"),
                int(r.get("attempt") or 1),
                int(r.get("sample_id") or 0),
            ): r
            for r in art.responses
        }
        for req in art.requests:
            cti = cti_refs_from_request(req)
            for fb in req.get("feedback") or []:
                if fb.get("reason") != "rejected_initial":
                    continue
                total_ri += 1
                try:
                    meta = json.loads(fb.get("rejected_json") or "{}")
                except json.JSONDecodeError:
                    meta = {}
                resp = resps.get(
                    (
                        meta.get("source_cti_id"),
                        int(meta.get("attempt") or 1),
                        int(meta.get("sample_id") or 0),
                    )
                )
                entry = classify_rejected_initial_entry(fb, resp, cti)
                cat = entry["category"]
                categories[cat] += 1
                by_tier[row.tier][cat] += 1
                wit = entry.get("witness") or {}
                init_val_tags[parse_witness_value_tag(str(wit.get("next_value", "")))] += 1
                if entry.get("pattern"):
                    patterns[entry["pattern"]] += 1
                if entry.get("last_clause_disjuncts"):
                    last_clause_sizes[int(entry["last_clause_disjuncts"])] += 1
                witness_in_cti["in_cti" if entry.get("witness_in_cti") else "not_in_cti"] += 1
                if len(examples[cat]) < 3:
                    examples[cat].append(
                        {
                            "slug": row.slug,
                            "tier": row.tier,
                            "batch_id": req.get("batch_id"),
                            "witness": wit,
                            "pattern": entry.get("pattern"),
                            "last_clause": entry.get("last_clause"),
                            "response_clauses": entry.get("response_clauses"),
                        }
                    )
                if row.slug.endswith("p040"):
                    p040_rows.append(
                        {
                            "batch_id": req.get("batch_id"),
                            "attempt": req.get("attempt"),
                            "category": cat,
                            "witness": wit,
                            "last_clause": entry.get("last_clause"),
                        }
                    )

    def share(cat: str) -> float:
        return round(100.0 * categories[cat] / total_ri, 1) if total_ri else 0.0

    return {
        "total_rejected_initial_feedback": total_ri,
        "note": (
            "Categories use the last block_clause in the rejected response (C++ witness "
            "source). B2 means witness ref is in that clause but its literal is false at "
            "the witness init value — often init is #b0 while clause uses eq 1 (CTI pattern "
            "copied without init check). C2 means multi-disjunct OR where another sibling "
            "likely satisfies init."
        ),
        "categories": dict(categories.most_common()),
        "category_share_pct": {k: share(k) for k in categories},
        "init_witness_value_tags": dict(init_val_tags.most_common()),
        "last_clause_disjunct_counts": dict(sorted(last_clause_sizes.items())),
        "witness_in_cti": dict(witness_in_cti),
        "top_b2_patterns": patterns.most_common(15),
        "by_tier": {tier: dict(cnt.most_common()) for tier, cnt in by_tier.items()},
        "examples": dict(examples),
        "p040_detail": p040_rows,
        "interpretation": {
            "C2_or_bloat": (
                f"{share('C2_multi_or_other_disjunct_at_init')}% — reduce OR width; "
                "max_block_clauses=1; single disjunct from digest top-1"
            ),
            "B1_direct_init_match": (
                f"{share('B1_single_witness_lit_true_at_init')}% — clause equals init "
                "(e.g. state=0 when init=0); add explicit anti-init examples"
            ),
            "B2_cti_on_init_mismatch": (
                f"{share('B2_single_witness_lit_false_at_witness')}% — single disjunct "
                "looks CTI-shaped but init witness differs (top: init0 + eq 1)"
            ),
            "witness_not_in_cti": (
                f"{witness_in_cti.get('not_in_cti', 0)} entries ({round(100*witness_in_cti.get('not_in_cti',0)/max(total_ri,1),1)}%)"
            ),
        },
        "recommended_instrumentation": [
            "C++ feedback: include clause_idx + full failed_clause disjuncts",
            "C++ feedback: include which disjunct satisfied init (SAT model)",
            "Prompt: init0 common — forbid pol=true,rhs=1 when witness shows state=0 at init",
        ],
    }


def phase_d4(csv_rows: list[CsvRow], archive: Path, d1: dict[str, Any]) -> dict[str, Any]:
    """Heuristic ceiling analysis (offline; does not re-run C++ verifier)."""
    with_req = [r for r in csv_rows if r.requests > 0]
    mic_shape_rates: list[float] = []
    single_disjunct_rates: list[float] = []
    multi_clause_response_pct: list[float] = []

    for row in with_req:
        art = load_bench_artifacts(archive, row.slug)
        s = analyze_responses(art)
        if s.get("mic_top1_shape_pct") is not None:
            mic_shape_rates.append(s["mic_top1_shape_pct"])
        if s.get("single_disjunct_clause_pct") is not None:
            single_disjunct_rates.append(s["single_disjunct_clause_pct"])
        rc = s.get("response_clause_counts") or {}
        responses = s.get("responses") or 0
        if responses:
            multi = sum(c for n, c in rc.items() if int(n) > 1)
            multi_clause_response_pct.append(100.0 * multi / responses)

    current = d1["totals"]["accept_per_request_pct"]
    # Heuristic: if many clauses already match MIC top-1 shape but accept is low,
    # prompt width may not be the only blocker (init/induction verifier).
    mean_mic = round(statistics.mean(mic_shape_rates), 1) if mic_shape_rates else 0.0
    mean_single = round(statistics.mean(single_disjunct_rates), 1) if single_disjunct_rates else 0.0

    target_pct = 40.0
    gap = round(target_pct - current, 1)

    if mean_mic >= 25 and mean_single >= 50:
        go_no_go = "prompt_feedback_likely"
        note = (
            "Many clauses already single-disjunct / MIC-shaped; closing gap to 40% "
            "likely needs narrower init-safe constraints + richer feedback, not X1 first."
        )
    elif mean_mic < 10 and mean_single < 30:
        go_no_go = "expressiveness_or_track_b"
        note = (
            "Low MIC-shape overlap suggests cube-only blocks misalign with CTI cores; "
            "Track B drop_literals or X1 may be required for 40% global target."
        )
    else:
        go_no_go = "mixed"
        note = (
            "Mixed clause shapes across tiers; pursue tier-split targets and Q2 prompt "
            "fixes on high rejected_initial subset before full expressiveness expansion."
        )

    return {
        "current_accept_per_request_pct": current,
        "target_accept_per_request_pct": target_pct,
        "gap_points": gap,
        "heuristic_ceiling": {
            "mean_mic_top1_shape_pct": mean_mic,
            "mean_single_disjunct_clause_pct": mean_single,
            "mean_multi_clause_response_pct": round(
                statistics.mean(multi_clause_response_pct), 1
            )
            if multi_clause_response_pct
            else 0.0,
        },
        "go_no_go": go_no_go,
        "note": note,
        "tier_split_recommendation": {
            "microban_zipcpu_qspiflash": "interim target 20–40% on subset after Q2",
            "ila": "interim target 5–15%; expressiveness gate before 40%",
            "global_40pct": "requires go_no_go=prompt_feedback_likely on D4 + Phase A′ rerun",
        },
    }


def phase_d5(
    d1: dict[str, Any],
    d3: dict[str, Any],
    d3b: dict[str, Any],
    d4: dict[str, Any],
) -> dict[str, Any]:
    ri_share = (d3.get("reason_share_pct") or {}).get("rejected_initial", 0)
    cat_share = d3b.get("category_share_pct") or {}
    interventions = []
    if ri_share >= 60:
        interventions.append(
            {
                "priority": 1,
                "action": "Q2.1/Q2.3: ban init-true literals; force single-disjunct / negate digest top-1",
                "expected_impact": "high on rejected_initial",
            }
        )
    if cat_share.get("C2_multi_or_other_disjunct_at_init", 0) >= 20:
        interventions.insert(
            0,
            {
                "priority": 1,
                "action": "Q2.4 + narrow OR: max_block_clauses=1; ban unrelated refs in same clause",
                "expected_impact": f"high — C2 OR-bloat {cat_share.get('C2_multi_or_other_disjunct_at_init')}%",
            },
        )
    if cat_share.get("B2_single_witness_lit_false_at_witness", 0) >= 30:
        interventions.append(
            {
                "priority": 1,
                "action": "Q2.1 init-aware: init0 forbid pol=true,rhs=1; require witness ref init check",
                "expected_impact": f"high — B2 CTI/init mismatch {cat_share.get('B2_single_witness_lit_false_at_witness')}%",
            },
        )
    if d4["heuristic_ceiling"]["mean_multi_clause_response_pct"] > 30:
        interventions.append(
            {
                "priority": 2,
                "action": "Q2.4: max_block_clauses=1 A/B",
                "expected_impact": "medium — reduce redundant wide clauses",
            }
        )
    interventions.append(
        {
            "priority": 3,
            "action": "Q2.2: full disjuncts in rejected_json feedback",
            "expected_impact": "medium — improve retry on attempt 2/3",
        }
    )
    if d4["go_no_go"] == "expressiveness_or_track_b":
        interventions.append(
            {
                "priority": 4,
                "action": "Track B drop_literals or X1 refine_predicate (tier-gated)",
                "expected_impact": "required for 40% global if Q2 plateaus",
            }
        )

    return {
        "success_criteria": {
            "p040_subset": "accept/request >= 40%",
            "diagnosis_subset_24": "accept/request >= 20% after Q2",
            "global_phase_a_prime": "accept/request >= 40% only if D4 go_no_go allows",
        },
        "interventions": interventions,
        "d3b_highlights": d3b.get("interpretation"),
        "d4_go_no_go": d4["go_no_go"],
    }


def write_markdown_summary(
    out_dir: Path,
    d0: dict[str, Any],
    d1: dict[str, Any],
    d2: dict[str, Any],
    d3: dict[str, Any],
    d3b: dict[str, Any],
    d4: dict[str, Any],
    d5: dict[str, Any],
) -> None:
    t = d1["totals"]
    lines = [
        "# Accept diagnosis summary",
        "",
        f"Archive: `{d0['archive']}`",
        "",
        "## D1 Funnel",
        "",
        f"- accept/request: **{t['accept_per_request_pct']}%** ({t['accepted']}/{t['requests']})",
        f"- accept/candidate: **{t['accept_per_candidate_pct']}%**",
        f"- rejected_initial/request: **{t['rejected_initial_per_request']}**",
        f"- induction_fail/request: **{t['induction_fail_per_request']}**",
        "",
        "### By tier",
        "",
        "| tier | cases | accept% | rejected_initial |",
        "|------|-------|---------|------------------|",
    ]
    for tier, info in sorted(d1["by_tier"].items()):
        lines.append(
            f"| {tier} | {info['cases']} | {info['accept_per_request_pct']}% | {info['rejected_initial']} |"
        )

    lines.extend(
        [
            "",
            "## D2 Positive vs contrast",
            "",
        ]
    )
    for key in ("accept_positive", "zero_accept_contrast", "p040"):
        block = d2[key]
        lines.append(
            f"- **{block['label']}**: mean single-disjunct {block['mean_single_disjunct_clause_pct']}%, "
            f"MIC top-1 shape {block['mean_mic_top1_shape_pct']}%"
        )

    lines.extend(
        [
            "",
            "## D3 Failure taxonomy (feedback)",
            "",
        ]
    )
    for reason, pct in sorted(
        (d3.get("reason_share_pct") or {}).items(), key=lambda x: -x[1]
    ):
        lines.append(f"- {reason}: **{pct}%**")

    lines.extend(["", "## D3b Init semantics (rejected_initial detail)", ""])
    for cat, pct in sorted(
        (d3b.get("category_share_pct") or {}).items(), key=lambda x: -x[1]
    ):
        lines.append(f"- {cat}: **{pct}%**")
    interp = d3b.get("interpretation") or {}
    for _key, text in interp.items():
        lines.append(f"- {text}")
    lines.append(
        f"- Init witness tags: `{d3b.get('init_witness_value_tags')}`"
    )

    lines.extend(
        [
            "",
            "## D4 40% go/no-go",
            "",
            f"- Current: **{d4['current_accept_per_request_pct']}%** → target **{d4['target_accept_per_request_pct']}%** (gap {d4['gap_points']} pts)",
            f"- Verdict: **{d4['go_no_go']}**",
            f"- Note: {d4['note']}",
            "",
            "## D5 Next interventions",
            "",
        ]
    )
    for item in d5["interventions"]:
        lines.append(f"- P{item['priority']}: {item['action']} ({item['expected_impact']})")

    (out_dir / "D_summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Q0 accept-rate diagnosis")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("bench_results/hwmcc_baseline_20260607/results_llm_phase_a.csv"),
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("bench_results/hwmcc_baseline_20260607/runs/20260609_032251_phase_a"),
    )
    parser.add_argument("--output", type=Path, default=Path("diagnosis"))
    parser.add_argument(
        "--phase",
        choices=["d0", "d1", "d2", "d3", "d3b", "d4", "d5", "all"],
        default="all",
    )
    args = parser.parse_args()

    csv_rows = load_csv(args.csv)
    args.output.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}
    if args.phase in ("d0", "all"):
        results["d0"] = phase_d0(csv_rows, args.archive)
        (args.output / "D0_inventory.json").write_text(
            json.dumps(results["d0"], indent=2) + "\n"
        )
    if args.phase in ("d1", "all"):
        results["d1"] = phase_d1(csv_rows)
        (args.output / "D1_funnel_summary.json").write_text(
            json.dumps(results["d1"], indent=2) + "\n"
        )
    if args.phase in ("d2", "all"):
        results["d2"] = phase_d2(csv_rows, args.archive)
        (args.output / "D2_positive_patterns.json").write_text(
            json.dumps(results["d2"], indent=2) + "\n"
        )
    if args.phase in ("d3", "all"):
        results["d3"] = phase_d3(csv_rows, args.archive)
        (args.output / "D3_failure_taxonomy.json").write_text(
            json.dumps(results["d3"], indent=2) + "\n"
        )
    if args.phase in ("d3b", "all"):
        results["d3b"] = phase_d3b(csv_rows, args.archive)
        (args.output / "D3b_init_semantics.json").write_text(
            json.dumps(results["d3b"], indent=2) + "\n"
        )
    if args.phase in ("d4", "all"):
        d1 = results.get("d1") or phase_d1(csv_rows)
        results["d4"] = phase_d4(csv_rows, args.archive, d1)
        (args.output / "D4_ceiling_analysis.json").write_text(
            json.dumps(results["d4"], indent=2) + "\n"
        )
    if args.phase in ("d5", "all"):
        d1 = results.get("d1") or phase_d1(csv_rows)
        d3 = results.get("d3") or phase_d3(csv_rows, args.archive)
        d3b = results.get("d3b") or phase_d3b(csv_rows, args.archive)
        d4 = results.get("d4") or phase_d4(csv_rows, args.archive, d1)
        results["d5"] = phase_d5(d1, d3, d3b, d4)
        (args.output / "D5_intervention_map.json").write_text(
            json.dumps(results["d5"], indent=2) + "\n"
        )

    if args.phase == "all":
        write_markdown_summary(
            args.output,
            results["d0"],
            results["d1"],
            results["d2"],
            results["d3"],
            results["d3b"],
            results["d4"],
            results["d5"],
        )
        print(f"Wrote reports under {args.output.resolve()}")
        print(
            f"accept/request: {results['d1']['totals']['accept_per_request_pct']}% "
            f"({results['d1']['totals']['accepted']}/{results['d1']['totals']['requests']})"
        )
        print(f"D4 go/no-go: {results['d4']['go_no_go']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
