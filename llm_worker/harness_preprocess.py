"""Q4 harness preprocessor: raw request → ordered task card for LLM self-check.

Section order (stable / important first):
  1. Self-check checklist (fixed)
  2. MUST_FALSIFY (bad-path literals this batch)
  3. INIT_TABLE (reset vs CTI; grows with feedback / init_raw)
  4. Micro-example (this batch top-1)
  5. CANDIDATES (soft suggestions)
  6. REPAIR (retry only)
  7. CTI summary (compact)
  8. Frame hints (compact)
  9. Task meta + json output line
"""

from __future__ import annotations

from typing import Any

from prompt_format import (
    _failed_clause_from_rejected_json,
    _format_disjunct_json,
    batch_cti_total,
    forbidden_disjuncts_for_witness,
    format_literal_line,
    negate_digest_lit_to_disjunct,
    normalize_rhs,
    parse_digest_lit_line,
    pick_digest_literal_lines,
    witness_refs_from_feedback,
)

SELF_CHECK_CHECKLIST = """Self-check (verify before output json):
  [CTI]  No disjunct positively matches any MUST_FALSIFY literal (do not restate bad path).
  [INIT] Whole OR-clause is FALSE at every INIT_TABLE init value (CTI column is NOT init).
  [OR]   ≤8 disjuncts per clause; prefer 1 disjunct unless retry suggests otherwise.
  [OUT]  Include self_check object documenting refs you verified."""


def _digest_stats(req: dict) -> list[dict[str, Any]]:
    digest = req.get("cti_digest") or {}
    return list(digest.get("literal_stats") or [])


def _count_for_lit(stats: list[dict], lit: str) -> int:
    for row in stats:
        if str(row.get("lit", "")).strip() == lit:
            return int(row.get("count", 0))
    return 0


def build_must_falsify(req: dict, *, max_n: int = 8) -> list[dict[str, Any]]:
    """Positive CTI/digest literals the block must falsify (not copy as true disjunct)."""
    stats = _digest_stats(req)
    out: list[dict[str, Any]] = []
    if stats:
        for row in stats:
            lit = str(row.get("lit", "")).strip()
            parsed = parse_digest_lit_line(lit)
            if not parsed:
                continue
            ref, rhs, pol = parsed
            out.append({
                "lit": lit,
                "ref": ref,
                "rhs": rhs,
                "positive_polarity": pol,
                "count": int(row.get("count", 0)),
            })
            if len(out) >= max_n:
                break
        return out

    # Single-CTI mode: cube literals
    from prompt_format import _iter_cube_literals

    for ref, rhs, pol in _iter_cube_literals(req.get("cti") or {}):
        line = format_literal_line(ref, rhs, pol)
        out.append({
            "lit": line,
            "ref": ref,
            "rhs": rhs,
            "positive_polarity": pol,
            "count": 1,
        })
    return out[:max_n]


def _cti_top_for_ref(stats: list[dict], ref: str) -> str | None:
    for row in stats:
        lit = str(row.get("lit", "")).strip()
        parsed = parse_digest_lit_line(lit)
        if parsed and parsed[0] == ref:
            return lit
    return None


def build_init_table(req: dict) -> list[dict[str, Any]]:
    """ref → init value (when known) + cti_top mode."""
    rows: dict[str, dict[str, Any]] = {}
    stats = _digest_stats(req)

    init_raw = req.get("init_raw") or {}
    for ref, val in (init_raw.get("values") or {}).items():
        rows[str(ref)] = {
            "ref": str(ref),
            "init": str(val),
            "cti_top": _cti_top_for_ref(stats, str(ref)),
            "source": "init_raw",
        }

    for ref, val in witness_refs_from_feedback(req):
        if ref not in rows:
            rows[ref] = {
                "ref": ref,
                "init": val,
                "cti_top": _cti_top_for_ref(stats, ref),
                "source": "witness",
            }

    for item in build_must_falsify(req, max_n=10):
        ref = item["ref"]
        if ref in rows:
            if not rows[ref].get("cti_top"):
                rows[ref]["cti_top"] = item["lit"]
            continue
        rows[ref] = {
            "ref": ref,
            "init": None,
            "cti_top": item["lit"],
            "source": "digest",
        }

    result = list(rows.values())
    result.sort(key=lambda r: (0 if r.get("init") else 1, r["ref"]))
    return result[:15]


def _feedback_raw_entries(req: dict) -> list[dict[str, Any]]:
    raw = req.get("feedback_raw")
    if isinstance(raw, list) and raw:
        return list(raw)
    legacy: list[dict[str, Any]] = []
    for fb in req.get("feedback") or []:
        wit = fb.get("witness") or {}
        entry: dict[str, Any] = {
            "reason": fb.get("reason"),
            "witness": wit,
        }
        rejected = fb.get("rejected_json")
        if rejected:
            failed, idx = _failed_clause_from_rejected_json(str(rejected))
            if failed:
                entry["failed_clause"] = failed
            if idx is not None:
                entry["clause_idx"] = idx
        legacy.append(entry)
    return legacy


def build_candidates(req: dict, *, max_n: int = 8) -> list[dict[str, Any]]:
    """Soft digest-negation suggestions; prefer C++ init_safe hints when present."""
    stats = _digest_stats(req)
    cti_total = batch_cti_total(req)
    hints = req.get("candidate_hints") or []
    out: list[dict[str, Any]] = []

    if hints:
        for rank, hint in enumerate(hints[: max_n + 3], start=1):
            dj = hint.get("block_disjunct") or {}
            if not dj:
                lit = str(hint.get("lit", ""))
                dj = negate_digest_lit_to_disjunct(lit) or {}
            if not dj.get("ref"):
                continue
            block_line = format_literal_line(
                str(dj.get("ref", "")),
                str(dj.get("rhs", "")),
                bool(dj.get("polarity", True)),
            )
            out.append({
                "rank": rank,
                "lit": hint.get("lit") or "",
                "count": int(hint.get("count", 0)),
                "block": block_line,
                "disjunct_json": dj,
                "init_safe": bool(hint.get("init_safe", False)),
                "reason": hint.get("reason"),
            })
    else:
        for lit in pick_digest_literal_lines(req, max_n=max_n + 3):
            dj = negate_digest_lit_to_disjunct(lit)
            if not dj:
                continue
            block_line = format_literal_line(
                str(dj.get("ref", "")),
                str(dj.get("rhs", "")),
                bool(dj.get("polarity", True)),
            )
            out.append({
                "lit": lit,
                "count": _count_for_lit(stats, lit),
                "block": block_line,
                "disjunct_json": dj,
                "init_safe": None,
            })

    out.sort(
        key=lambda c: (
            0 if c.get("init_safe") else 1,
            -(c.get("count") or 0),
        )
    )
    out = out[:max_n]
    if cti_total:
        for c in out:
            c["cti_total"] = cti_total
    for i, c in enumerate(out, start=1):
        c["rank"] = i
    return out


def build_constraints(req: dict) -> dict[str, Any]:
    """Cumulative witness forbidden refs/disjuncts + must_falsify digest lits."""
    must = [m["lit"] for m in build_must_falsify(req, max_n=5)]
    forbidden_refs: list[str] = []
    forbidden_disjuncts: list[str] = []
    seen_ref: set[str] = set()
    seen_dj: set[str] = set()

    for fb in _feedback_raw_entries(req):
        if str(fb.get("reason") or "") != "rejected_initial":
            continue
        wit = fb.get("witness") or {}
        wref = str(wit.get("ref") or "")
        wval = str(wit.get("next_value") or "")
        if wref and wref not in seen_ref:
            seen_ref.add(wref)
            forbidden_refs.append(wref)
        if wref and wval:
            for tmpl in forbidden_disjuncts_for_witness(wref, wval):
                line = format_literal_line(
                    str(tmpl.get("ref", "")),
                    str(tmpl.get("rhs", "")),
                    bool(tmpl.get("polarity", True)),
                )
                if line not in seen_dj:
                    seen_dj.add(line)
                    forbidden_disjuncts.append(line)

    return {
        "must_falsify": must,
        "forbidden_refs": forbidden_refs,
        "forbidden_disjuncts": forbidden_disjuncts,
    }


def _failed_clause_line(failed_clause: list[dict[str, Any]]) -> str | None:
    parts = [
        format_literal_line(
            str(d.get("ref", "")),
            str(d.get("rhs", "")),
            bool(d.get("polarity", True)),
        )
        for d in failed_clause
        if d.get("ref")
    ]
    if parts:
        return " | ".join(parts)
    return None


def build_repair(req: dict) -> list[str]:
    """Contrastive repair lines from feedback_raw (or legacy feedback)."""
    entries = _feedback_raw_entries(req)
    if not entries:
        return []

    lines: list[str] = []
    for fb in reversed(entries):
        reason = str(fb.get("reason") or "")
        wit = fb.get("witness") or {}
        wref = str(wit.get("ref") or "")
        wval = str(wit.get("next_value") or "")

        if reason == "rejected_initial" and wref and wval:
            failed_line = None
            failed_clause = list(fb.get("failed_clause") or [])
            if failed_clause:
                failed_line = _failed_clause_line(failed_clause)
            elif fb.get("rejected_json"):
                fc, _ = _failed_clause_from_rejected_json(str(fb["rejected_json"]))
                failed_line = _failed_clause_line(fc)

            lines.append("  last_fail: rejected_initial")
            if failed_line:
                lines.append(f"  you_tried: {failed_line}")
            lines.append(
                f"  init_witness: {wref}={normalize_rhs(wval)} (clause was TRUE at reset)"
            )
            must = build_must_falsify(req, max_n=3)
            if must:
                lines.append(
                    "  cti_still_need_falsify: "
                    + " | ".join(m["lit"] for m in must)
                )
            lines.append(
                "  try: pick init_safe CANDIDATES; avoid disjuncts true when "
                f"{wref}={normalize_rhs(wval)}"
            )
            break

        if reason == "induction_failed" and wref and wval:
            lines.append("  last_fail: induction_failed")
            lines.append(f"  ctg_witness: next({wref})={normalize_rhs(wval)}")
            lines.append("  try: stronger literal or different ref; keep MUST_FALSIFY + INIT_TABLE")
            break

    return lines


def format_must_falsify_section(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["MUST_FALSIFY: (no simple digest literals; falsify all CTI cube literals)"]
    lines = [
        "MUST_FALSIFY (clause OR must be FALSE when these hold — do NOT copy as true disjunct):",
    ]
    for item in items:
        count = item.get("count", 0)
        suffix = f"  (count={count})" if count else ""
        lines.append(f"  {item['lit']}{suffix}")
    return lines


def format_init_table_section(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "INIT_TABLE (reset/init values; CTI column is failing-state NOT init):",
        "  ref          init           cti_top",
    ]
    if not rows:
        lines.append("  (no refs yet)")
        return lines
    for row in rows:
        ref = row["ref"]
        init = row.get("init")
        init_s = normalize_rhs(str(init)) if init is not None else "?"
        cti = row.get("cti_top") or "—"
        same = ""
        if init is not None and row.get("cti_top"):
            parsed = parse_digest_lit_line(str(row["cti_top"]))
            if parsed:
                _, rhs, _ = parsed
                if normalize_rhs(str(init)) == normalize_rhs(rhs):
                    same = "  SAME"
        lines.append(f"  {ref:<12} {init_s:<14} {cti}{same}")
    return lines


def format_micro_example(must: list[dict[str, Any]]) -> list[str]:
    if not must:
        return []
    item = must[0]
    ref, rhs = item["ref"], normalize_rhs(item["rhs"])
    bad = json_disjunct(ref, rhs, item["positive_polarity"])
    ok = json_disjunct(ref, rhs, not item["positive_polarity"])
    return [
        "Micro-example (this batch top MUST_FALSIFY):",
        f"  CTI literal: {item['lit']}",
        f"  BAD (restates bad): {bad}",
        f"  OK (falsifies CTI): {ok}  — then verify INIT_TABLE before output",
    ]


def json_disjunct(ref: str, rhs: str, polarity: bool) -> str:
    return _format_disjunct_json({
        "ref": ref,
        "op": "eq",
        "rhs": rhs,
        "polarity": polarity,
    })


def format_candidates_section(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return []
    lines = [
        "CANDIDATES (soft suggestions — prefer init_safe=true; verify MUST_FALSIFY + INIT_TABLE):",
    ]
    for c in candidates:
        rank = c.get("rank", 0)
        count = c.get("count", 0)
        tag = ""
        if c.get("init_safe") is True:
            tag = "  [init_safe]"
        elif c.get("init_safe") is False:
            reason = c.get("reason") or "UNSAFE"
            tag = f"  [{reason}]"
        lines.append(f"  #{rank} {c['lit']} (count={count}) → block {c['block']}{tag}")
    return lines


def format_constraints_section(constraints: dict[str, Any]) -> list[str]:
    must = constraints.get("must_falsify") or []
    frefs = constraints.get("forbidden_refs") or []
    fdjs = constraints.get("forbidden_disjuncts") or []
    if not must and not frefs and not fdjs:
        return []
    lines = ["CONSTRAINTS:"]
    if must:
        lines.append("  must_falsify: " + " | ".join(must))
    if frefs:
        lines.append("  forbidden_refs: " + " | ".join(frefs))
    if fdjs:
        lines.append("  forbidden_disjuncts: " + " | ".join(fdjs[:8]))
    return lines


def format_cti_summary(req: dict, *, max_stats: int = 10, max_cubes: int = 2) -> list[str]:
    digest = req.get("cti_digest")
    if not digest:
        return []
    total = int(digest.get("cti_total") or 0)
    entries = list(req.get("cti_entries") or [])[:max_cubes]
    lines = [f"CTI summary (cti_total={total}, top stats only):"]
    for row in (digest.get("literal_stats") or [])[:max_stats]:
        lines.append(f"  {row.get('lit', '?')}  (count={row.get('count', 0)})")
    if entries:
        lines.append("  outlier sample cubes:")
        for ent in entries:
            cid = ent.get("cti_id", "?")
            if ent.get("literals"):
                body = " | ".join(str(x) for x in ent["literals"][:8])
            else:
                body = "(structured cube)"
            if len(body) > 120:
                body = body[:117] + "..."
            lines.append(f"    [{cid}] {body}")
    return lines


def format_frame_hints(req: dict, *, max_stats: int = 5) -> list[str]:
    snap = req.get("frame_snapshot") or {}
    digest = snap.get("clause_digest") or {}
    stats = digest.get("literal_stats") or []
    if not stats:
        total = snap.get("clauses_total")
        if total:
            return [f"Frame: clauses_total={total} (no literal stats in snapshot)"]
        return []
    lines = ["Frame hints (learned clause literal stats, reference only):"]
    for row in stats[:max_stats]:
        lines.append(f"  {row.get('lit', '?')}  (count={row.get('count', 0)})")
    return lines


def build_harness_packet(req: dict, sample_id: int = 0) -> dict[str, Any]:
    """Structured harness_packet v1 (debug / inspect script)."""
    snap = req.get("frame_snapshot") or {}
    init_rows = build_init_table(req)
    candidates = build_candidates(req)
    constraints = build_constraints(req)
    repair_lines = build_repair(req) if int(req.get("attempt", 1)) >= 2 else []

    init_table_out = []
    for row in init_rows:
        same = None
        init = row.get("init")
        cti_top = row.get("cti_top")
        if init is not None and cti_top:
            parsed = parse_digest_lit_line(str(cti_top))
            if parsed:
                _, rhs, _ = parsed
                same = normalize_rhs(str(init)) == normalize_rhs(rhs)
        init_table_out.append({
            "ref": row["ref"],
            "init": init,
            "cti_top": cti_top,
            "same": same,
        })

    return {
        "type": "harness_packet",
        "schema_version": 1,
        "task": {
            "batch_id": req.get("batch_id") or req.get("cti_id"),
            "frame_idx": req.get("frame_idx"),
            "attempt": int(req.get("attempt", 1)),
            "max_block_clauses": int(req.get("max_block_clauses", 3)),
            "sample_id": sample_id,
        },
        "proof": {
            "cti_total": batch_cti_total(req),
            "clauses_total": snap.get("clauses_total"),
            "feedback_count": len(_feedback_raw_entries(req)),
        },
        "init_table": init_table_out,
        "candidates": candidates,
        "constraints": constraints,
        "repair": repair_lines or None,
        "frame_hints": {
            "top_lits": [
                f"{row.get('lit')}(count={row.get('count', 0)})"
                for row in (snap.get("clause_digest") or {}).get("literal_stats") or []
            ][:5],
        },
    }


def harness_metrics(req: dict, sample_id: int = 0) -> dict[str, Any]:
    """Aggregate metrics for smoke gate / inspect script."""
    init_rows = build_init_table(req)
    known = sum(1 for r in init_rows if r.get("init") is not None)
    total = len(init_rows) or 1
    card = render_task_card(req, sample_id)
    constraints = build_constraints(req)
    candidates = build_candidates(req)
    return {
        "user_prompt_bytes": len(card.encode()),
        "init_table_rows": total,
        "init_table_known": known,
        "init_table_coverage_pct": round(100.0 * known / total, 1),
        "candidate_count": len(candidates),
        "init_safe_candidates": sum(1 for c in candidates if c.get("init_safe")),
        "forbidden_ref_count": len(constraints.get("forbidden_refs") or []),
        "has_feedback_raw": bool(req.get("feedback_raw")),
        "has_candidate_hints": bool(req.get("candidate_hints")),
        "has_init_raw": bool((req.get("init_raw") or {}).get("values")),
    }


def render_task_card(req: dict, sample_id: int = 0) -> str:
    """Build ordered user prompt for one API call."""
    batch_id = req.get("batch_id") or req.get("cti_id") or ""
    frame_idx = req.get("frame_idx")
    attempt = int(req.get("attempt", 1))
    max_clauses = int(req.get("max_block_clauses", 3))

    must = build_must_falsify(req)
    init_rows = build_init_table(req)
    candidates = build_candidates(req)
    constraints = build_constraints(req)
    repair = build_repair(req) if attempt >= 2 or _feedback_raw_entries(req) else []

    sections: list[str] = [
        SELF_CHECK_CHECKLIST,
        "",
        *format_must_falsify_section(must),
        "",
        *format_init_table_section(init_rows),
    ]

    micro = format_micro_example(must)
    if micro:
        sections.extend(["", *micro])

    cand_sec = format_candidates_section(candidates)
    if cand_sec:
        sections.extend(["", *cand_sec])

    constr_sec = format_constraints_section(constraints)
    if constr_sec:
        sections.extend(["", *constr_sec])

    if repair:
        sections.extend(["", "REPAIR:", *repair])

    cti_sec = format_cti_summary(req)
    if cti_sec:
        sections.extend(["", *cti_sec])

    frame_sec = format_frame_hints(req)
    if frame_sec:
        sections.extend(["", *frame_sec])

    sections.extend([
        "",
        f"task: batch_id={batch_id!r} frame_idx={frame_idx} attempt={attempt} sample_id={sample_id}",
        (
            f"Output json: ic3_frame_response with 1..{max_clauses} block_clauses, "
            "self_check object, and brief rationale."
        ),
        (
            'self_check example: {"must_falsify_refs":["state34"],'
            '"init_refs_checked":["state34"],"clause_false_at_init":true,'
            '"clause_false_on_cti_top":true}'
        ),
        f"source_cti_id={batch_id!r} sample_id={sample_id}",
    ])
    return "\n".join(sections)


def section_byte_sizes(req: dict, sample_id: int = 0) -> dict[str, int]:
    """Debug: byte size per section for harness tuning."""
    must = build_must_falsify(req)
    sizes = {
        "checklist": len(SELF_CHECK_CHECKLIST.encode()),
        "must_falsify": len("\n".join(format_must_falsify_section(must)).encode()),
        "init_table": len("\n".join(format_init_table_section(build_init_table(req))).encode()),
        "total": len(render_task_card(req, sample_id).encode()),
    }
    return sizes
