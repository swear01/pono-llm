#!/usr/bin/env python3
"""Diagnose Q2 current-method failures from p040 smoke artifact directories."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reuse Phase Q0 taxonomy helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_accept_diagnosis as diag  # noqa: E402


@dataclass
class SmokeRun:
    label: str
    path: Path
    requests: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    llm_stats: dict[str, Any] = field(default_factory=dict)


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


def parse_llm_stats(stderr_path: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    if not stderr_path.exists():
        return stats
    for line in stderr_path.read_text().splitlines():
        if not line.startswith("LLM_STATS"):
            continue
        for part in line.split():
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            try:
                stats[k] = int(v)
            except ValueError:
                stats[k] = v
    return stats


def load_smoke_run(path: Path, label: str = "") -> SmokeRun:
    art_dir = path
    if (path / "artifacts").is_dir():
        art_dir = path / "artifacts"
    run = SmokeRun(
        label=label or path.name,
        path=path,
        requests=load_jsonl(art_dir / "requests.jsonl"),
        responses=load_jsonl(art_dir / "responses.jsonl"),
        llm_stats=parse_llm_stats(art_dir / "pono_stderr.log"),
    )
    return run


def discover_runs(root: Path, glob_pat: str = "*") -> list[SmokeRun]:
    runs: list[SmokeRun] = []
    if (root / "requests.jsonl").exists() or (root / "artifacts" / "requests.jsonl").exists():
        return [load_smoke_run(root, root.name)]

    for child in sorted(root.glob(glob_pat)):
        if not child.is_dir():
            continue
        if (child / "artifacts" / "requests.jsonl").exists():
            runs.append(load_smoke_run(child, child.name))
        elif (child / "requests.jsonl").exists():
            runs.append(load_smoke_run(child, child.name))
    return runs


def failed_clause_from_feedback(
    fb: dict[str, Any], resp: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], int | None]:
    try:
        meta = json.loads(fb.get("rejected_json") or "{}")
    except json.JSONDecodeError:
        meta = {}
    clauses = meta.get("block_clauses") or []
    if not clauses and resp:
        clauses = diag.collect_clauses(resp)
    idx = meta.get("clause_idx")
    if idx is not None and isinstance(idx, int) and 0 <= idx < len(clauses):
        return list(clauses[idx]), idx
    if clauses:
        return list(clauses[-1]), len(clauses) - 1
    return [], None


def classify_ri_with_clause_idx(
    fb: dict[str, Any], resp: dict[str, Any] | None, cti_refs: set[str]
) -> dict[str, Any]:
    """Like d3b but uses Q2.3 clause_idx when present."""
    wit = fb.get("witness") or {}
    wref = str(wit.get("ref") or "")
    wval = str(wit.get("next_value") or "")
    if not wref:
        return {"category": "no_witness"}

    clause, clause_idx = failed_clause_from_feedback(fb, resp)
    if not clause:
        return {"category": "empty_clause", "witness": wit}

    refs_in_clause = {str(d.get("ref") or "") for d in clause}
    wit_in_cti = wref in cti_refs
    wit_disjuncts = [d for d in clause if d.get("ref") == wref]
    wit_lit_true = any(
        diag.disjunct_true_at_witness_ref(d, wref, wval) is True for d in wit_disjuncts
    )

    if wref not in refs_in_clause:
        cat = "A_witness_not_in_failed_clause"
    elif len(clause) == 1:
        cat = (
            "B1_single_witness_lit_true_at_init"
            if wit_lit_true
            else "B2_single_witness_lit_false_at_witness"
        )
    elif wit_lit_true:
        cat = "C1_multi_witness_lit_true_at_init"
    else:
        cat = "C2_multi_or_other_disjunct_at_init"

    dj = clause[0] if len(clause) == 1 else None
    pattern = None
    if cat in ("B1_single_witness_lit_true_at_init", "B2_single_witness_lit_false_at_witness") and dj:
        tag = diag.parse_witness_value_tag(wval)
        pattern = (
            f"{tag}_clause_eq_{str(dj.get('rhs'))[:16]}_pol_{dj.get('polarity', True)}"
        )

    return {
        "category": cat,
        "witness": wit,
        "witness_in_cti": wit_in_cti,
        "failed_clause_disjuncts": len(clause),
        "clause_idx": clause_idx,
        "pattern": pattern,
        "failed_clause": clause,
        "used_clause_idx": clause_idx is not None,
    }


def disjunct_matches_cti_literal(dj: dict[str, Any], cti_refs: set[str], req: dict[str, Any]) -> bool:
    ref = str(dj.get("ref") or "")
    if ref not in cti_refs:
        return False
    # Heuristic: same ref appears in CTI with matching rhs/polarity intent.
    for ent in req.get("cti_entries") or []:
        for lit in (ent.get("cti") or {}).get("cube", {}).get("literals") or []:
            atom = lit.get("atom") or {}
            if atom.get("ref") != ref:
                continue
            if str(atom.get("rhs")) == str(dj.get("rhs")):
                return bool(lit.get("polarity", True)) == bool(dj.get("polarity", True))
    return True  # ref in digest/cti, shape unknown


def analyze_run(run: SmokeRun) -> dict[str, Any]:
    art = diag.BenchArtifacts(
        slug=run.label,
        path=run.path,
        requests=run.requests,
        responses=run.responses,
    )
    resp_stats = diag.analyze_responses(art)
    fb_stats = diag.analyze_feedback(art)

    resps = {
        (
            r.get("source_cti_id"),
            int(r.get("attempt") or 1),
            int(r.get("sample_id") or 0),
        ): r
        for r in run.responses
    }

    ri_categories: Counter[str] = Counter()
    ri_patterns: Counter[str] = Counter()
    init_tags: Counter[str] = Counter()
    clause_sizes: Counter[int] = Counter()
    used_clause_idx = 0
    total_ri = 0
    cti_copy_disjuncts = 0
    total_disjuncts = 0
    retry_same_witness: Counter[str] = Counter()
    retry_same_pattern: Counter[str] = Counter()
    attempt_ri: Counter[int] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    first_fail_by_batch: dict[str, tuple[str, str | None]] = {}

    for req in run.requests:
        batch_id = str(req.get("batch_id") or "")
        attempt = int(req.get("attempt") or 1)
        cti_refs = diag.cti_refs_from_request(req)

        for resp in run.responses:
            if resp.get("source_cti_id") != batch_id:
                continue
            for clause in diag.collect_clauses(resp):
                for dj in clause:
                    total_disjuncts += 1
                    if disjunct_matches_cti_literal(dj, cti_refs, req):
                        cti_copy_disjuncts += 1

        for fb in req.get("feedback") or []:
            reason = str(fb.get("reason") or "")
            if reason != "rejected_initial":
                continue
            total_ri += 1
            attempt_ri[attempt] += 1
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
            entry = classify_ri_with_clause_idx(fb, resp, cti_refs)
            cat = entry["category"]
            ri_categories[cat] += 1
            wit = entry.get("witness") or {}
            wref = str(wit.get("ref") or "")
            wval = str(wit.get("next_value") or "")
            init_tags[diag.parse_witness_value_tag(wval)] += 1
            if entry.get("pattern"):
                ri_patterns[entry["pattern"]] += 1
            if entry.get("failed_clause_disjuncts"):
                clause_sizes[int(entry["failed_clause_disjuncts"])] += 1
            if entry.get("used_clause_idx"):
                used_clause_idx += 1

            base_batch = re.sub(r"_a\d+$", "", batch_id)
            if attempt == 1:
                first_fail_by_batch[base_batch] = (wref, entry.get("pattern"))
            elif base_batch in first_fail_by_batch:
                prev_ref, prev_pat = first_fail_by_batch[base_batch]
                if wref and wref == prev_ref:
                    retry_same_witness[wref] += 1
                if entry.get("pattern") and entry.get("pattern") == prev_pat:
                    retry_same_pattern[str(entry.get("pattern"))] += 1

            if len(examples[cat]) < 2:
                examples[cat].append(
                    {
                        "batch_id": batch_id,
                        "attempt": attempt,
                        "witness": wit,
                        "pattern": entry.get("pattern"),
                        "failed_clause": entry.get("failed_clause"),
                        "clause_idx": entry.get("clause_idx"),
                    }
                )

    stats = run.llm_stats
    req_n = stats.get("requests") or len(run.requests) or 1
    acc = stats.get("accepted", 0)
    share = lambda c: round(100.0 * ri_categories[c] / total_ri, 1) if total_ri else 0.0

    return {
        "label": run.label,
        "path": str(run.path),
        "llm_stats": stats,
        "accept_per_request_pct": round(100.0 * acc / req_n, 1),
        "response_shape": resp_stats,
        "feedback_summary": fb_stats,
        "rejected_initial_taxonomy": {
            "total": total_ri,
            "categories": dict(ri_categories.most_common()),
            "category_share_pct": {k: share(k) for k in ri_categories},
            "top_patterns": ri_patterns.most_common(10),
            "init_witness_tags": dict(init_tags.most_common()),
            "failed_clause_disjunct_counts": dict(sorted(clause_sizes.items())),
            "clause_idx_used_pct": round(100.0 * used_clause_idx / total_ri, 1) if total_ri else 0,
            "examples": dict(examples),
        },
        "cti_literal_copy": {
            "disjuncts_matching_cti_pct": round(100.0 * cti_copy_disjuncts / total_disjuncts, 1)
            if total_disjuncts
            else 0,
            "total_disjuncts": total_disjuncts,
        },
        "retry_stagnation": {
            "rejected_initial_by_attempt": dict(sorted(attempt_ri.items())),
            "same_witness_on_retry_top": retry_same_witness.most_common(8),
            "same_pattern_on_retry_top": retry_same_pattern.most_common(8),
        },
    }


def aggregate_runs(per_run: list[dict[str, Any]]) -> dict[str, Any]:
    total_acc = sum((r.get("llm_stats") or {}).get("accepted", 0) for r in per_run)
    total_req = sum((r.get("llm_stats") or {}).get("requests", 0) for r in per_run) or 1
    cats: Counter[str] = Counter()
    total_ri = 0
    mic_pcts: list[float] = []
    single_pcts: list[float] = []
    cti_copy_pcts: list[float] = []

    for r in per_run:
        tax = r.get("rejected_initial_taxonomy") or {}
        total_ri += tax.get("total", 0)
        for k, v in (tax.get("categories") or {}).items():
            cats[k] += v
        rs = r.get("response_shape") or {}
        if rs.get("mic_top1_shape_pct") is not None:
            mic_pcts.append(rs["mic_top1_shape_pct"])
        if rs.get("single_disjunct_clause_pct") is not None:
            single_pcts.append(rs["single_disjunct_clause_pct"])
        cti_copy_pcts.append((r.get("cti_literal_copy") or {}).get("disjuncts_matching_cti_pct", 0))

    def cat_share(c: str) -> float:
        return round(100.0 * cats[c] / total_ri, 1) if total_ri else 0.0

    return {
        "runs": len(per_run),
        "accept_per_request_pct": round(100.0 * total_acc / total_req, 1),
        "accepted": total_acc,
        "requests": total_req,
        "rejected_initial_total": total_ri,
        "category_share_pct": {k: cat_share(k) for k in cats},
        "mean_mic_top1_shape_pct": round(statistics.mean(mic_pcts), 1) if mic_pcts else None,
        "mean_single_disjunct_clause_pct": round(statistics.mean(single_pcts), 1)
        if single_pcts
        else None,
        "mean_cti_copy_disjunct_pct": round(statistics.mean(cti_copy_pcts), 1) if cti_copy_pcts else None,
    }


def write_summary_md(report: dict[str, Any], out_path: Path) -> None:
    agg = report.get("aggregate") or {}
    cats = agg.get("category_share_pct") or {}
    lines = [
        "# Q2 current-method smoke diagnosis",
        "",
        f"Runs analyzed: **{agg.get('runs', 0)}**",
        f"Aggregate accept/API: **{agg.get('accept_per_request_pct')}%** "
        f"({agg.get('accepted')}/{agg.get('requests')})",
        f"rejected_initial feedback entries: **{agg.get('rejected_initial_total')}**",
        "",
        "## Init-semantics taxonomy (Q2 smoke)",
        "",
        f"- B2 (CTI/init mismatch): **{cats.get('B2_single_witness_lit_false_at_witness', 0)}%**",
        f"- C2 (OR sibling at init): **{cats.get('C2_multi_or_other_disjunct_at_init', 0)}%**",
        f"- B1 (clause equals init): **{cats.get('B1_single_witness_lit_true_at_init', 0)}%**",
        f"- A (witness not in failed clause): **{cats.get('A_witness_not_in_failed_clause', 0)}%**",
        "",
        "## Response shape",
        "",
        f"- Mean MIC top-1 shape match: **{agg.get('mean_mic_top1_shape_pct')}%**",
        f"- Mean single-disjunct clauses: **{agg.get('mean_single_disjunct_clause_pct')}%**",
        f"- Mean CTI-literal copy in disjuncts: **{agg.get('mean_cti_copy_disjunct_pct')}%**",
        "",
        "## Interpretation",
        "",
    ]

    b2 = cats.get("B2_single_witness_lit_false_at_witness", 0)
    c2 = cats.get("C2_multi_or_other_disjunct_at_init", 0)
    if b2 >= 50:
        lines.append(
            "- **B2 still dominant** after Q2.1: model copies CTI-shaped literals that fail "
            "init witness check → Q3.1 witness templates + Q3.2 digest-negate."
        )
    if c2 >= 25:
        lines.append(
            "- **C2 still material**: multi-disjunct OR fails at init → Q3.3 enforce ≤1 disjunct/clause."
        )
    mic = agg.get("mean_mic_top1_shape_pct") or 0
    if mic < 15:
        lines.append(
            "- **Low MIC alignment**: blocks rarely match mechanical digest-negate top-1 → Q3.2."
        )

    stagnation = []
    for run in report.get("per_run") or []:
        rs = run.get("retry_stagnation") or {}
        if rs.get("same_witness_on_retry_top"):
            stagnation.append(run["label"])
    if stagnation:
        lines.append(
            f"- **Retry stagnation**: same witness ref on retry in {len(stagnation)} run(s) "
            "→ Q3.4 negative literal stats + stronger repair templates."
        )

    lines.extend(["", "## Per-run", ""])
    for run in report.get("per_run") or []:
        lines.append(
            f"- `{run['label']}`: accept/API {run.get('accept_per_request_pct')}% "
            f"(RI taxonomy n={(run.get('rejected_initial_taxonomy') or {}).get('total', 0)})"
        )

    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Smoke RUN_DIR or multiround OUT_BASE (child dirs with artifacts/)",
    )
    ap.add_argument(
        "--filter",
        default="*",
        help="Glob under multiround base (e.g. 'A1_q2_*')",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("diagnosis/Q2_smoke_current_method.json"),
    )
    ap.add_argument(
        "--summary",
        type=Path,
        default=Path("diagnosis/Q2_current_method_summary.md"),
    )
    args = ap.parse_args()

    all_runs: list[SmokeRun] = []
    for inp in args.inputs:
        if not inp.exists():
            print(f"skip missing: {inp}", file=sys.stderr)
            continue
        all_runs.extend(discover_runs(inp, args.filter))

    if not all_runs:
        print("No smoke runs found.", file=sys.stderr)
        sys.exit(1)

    per_run = [analyze_run(r) for r in all_runs]
    report = {
        "inputs": [str(p) for p in args.inputs],
        "filter": args.filter,
        "per_run": per_run,
        "aggregate": aggregate_runs(per_run),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    write_summary_md(report, args.summary)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.summary}")
    agg = report["aggregate"]
    print(
        f"Aggregate: accept/API={agg.get('accept_per_request_pct')}% "
        f"B2={agg.get('category_share_pct', {}).get('B2_single_witness_lit_false_at_witness')}% "
        f"C2={agg.get('category_share_pct', {}).get('C2_multi_or_other_disjunct_at_init')}%"
    )


if __name__ == "__main__":
    main()
