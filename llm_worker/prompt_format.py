"""Compact text formats for sidecar LLM prompts (no C++/schema changes)."""

from __future__ import annotations

import json
import re
from typing import Iterable


def normalize_rhs(rhs: str) -> str:
    if rhs == "#b0":
        return "0"
    if rhs == "#b1":
        return "1"
    if rhs == "true":
        return "1"
    if rhs == "false":
        return "0"
    return rhs


def batch_cti_total(request: dict) -> int:
    """Total CTIs in batch: prefer cti_digest.cti_total over len(cti_entries)."""
    digest = (request or {}).get("cti_digest") or {}
    if "cti_total" in digest:
        return int(digest["cti_total"])
    return len((request or {}).get("cti_entries") or [])


def format_literal_line(ref: str, rhs: str, polarity: bool) -> str:
    prefix = "" if polarity else "!"
    return f"{prefix}{ref}={normalize_rhs(rhs)}"


def _iter_cube_literals(cti: dict) -> Iterable[tuple[str, str, bool]]:
    cube = (cti or {}).get("cube") or {}
    for lit in cube.get("literals") or []:
        atom = lit.get("atom") or {}
        ref = atom.get("ref") or ""
        if not ref:
            continue
        rhs = atom.get("rhs", "")
        polarity = bool(lit.get("polarity", True))
        yield ref, rhs, polarity


def _iter_digest_literals(entry: dict) -> Iterable[tuple[str, str, bool]]:
    if entry.get("literals"):
        for line in entry["literals"]:
            m = re.match(r"(!?)(state\d+|input\d+)=(.+)", str(line))
            if m:
                yield m.group(2), m.group(3), m.group(1) != "!"
        return
    yield from _iter_cube_literals(entry.get("cti") or {})


def collect_refs_from_request(req: dict) -> set[str]:
    """Refs appearing in CTI batch and feedback witnesses."""
    refs: set[str] = set()
    for ref, _, _ in _iter_cube_literals(req.get("cti") or {}):
        refs.add(ref)
    for ent in req.get("cti_entries") or []:
        for ref, _, _ in _iter_digest_literals(ent):
            refs.add(ref)
    digest = req.get("cti_digest") or {}
    for row in digest.get("literal_stats") or []:
        lit = str(row.get("lit", ""))
        for m in re.finditer(r"!?((?:state|input)\d+)=", lit):
            refs.add(m.group(1))
    for fb in req.get("feedback") or []:
        wref = (fb.get("witness") or {}).get("ref") or ""
        if wref:
            refs.add(wref)
    return refs


def format_symbol_hints(refs: set[str], registry: dict) -> str:
    if not refs or not registry:
        return ""
    lines = ["Symbol hints (CTI/witness refs only):"]
    for ref in sorted(refs):
        ent = registry.get(ref) or {}
        if not ent:
            continue
        verilog = ent.get("verilog") or ""
        if verilog and len(verilog) > 80:
            verilog = verilog[:77] + "..."
        width = ent.get("width", "")
        lines.append(f"  {ref}: width={width}, verilog={verilog or 'n/a'}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def sample_generalization_hint(sample_id: int) -> str:
    hints = {
        0: "Strategy: prefer MINIMAL block (1-2 disjuncts); drop datapath/incidental CTI literals.",
        1: "Strategy: derive block from high-frequency clause_digest literals; avoid restating samples.",
        2: "Strategy: OR of 3-4 literals covering all sample CTI cores; generalize beyond single cube.",
    }
    return hints.get(sample_id % 3, hints[0])


def format_proof_context(req: dict) -> str:
    snap = req.get("frame_snapshot") or {}
    ctx = snap.get("proof_context") or req.get("proof_context") or {}
    if not ctx:
        ctx = {
            "frame_idx": req.get("frame_idx", snap.get("frame_idx", 0)),
            "clauses_total": snap.get("clauses_total") or len(snap.get("clauses") or []),
            "cti_total": batch_cti_total(req),
            "attempt": req.get("attempt", 1),
            "feedback_count": len(req.get("feedback") or []),
        }
    return "proof_context: " + json.dumps(ctx, separators=(",", ":"))


def _repair_line(reason: str, wref: str, wval: str) -> str:
    if reason == "rejected_initial" and wref:
        return (
            f"    Repair: block MUST be false when {wref}={wval} at initial state "
            f"(witness is current-state value)."
        )
    if reason == "induction_failed" and wref:
        return (
            f"    Repair: block must be inductive relative to frame; falsify transition "
            f"where next({wref})={wval} (CTG-like witness)."
        )
    if reason == "rejected_initial":
        return "    Repair: block must NOT hold on any initial state."
    if reason == "induction_failed":
        return "    Repair: block must be relatively inductive at this frame."
    return ""


def format_feedback_block(feedback: list[dict]) -> str:
    if not feedback:
        return ""
    correctness: list[str] = []
    inductiveness: list[str] = []
    other: list[str] = []

    for i, fb in enumerate(feedback):
        reason = fb.get("reason", "?")
        witness = fb.get("witness") or {}
        wref = witness.get("ref", "")
        wval = witness.get("next_value", "")
        entry = [f"  [{i}] {reason}"]
        if wref or wval:
            entry.append(f"      witness: {wref} -> {wval}")
        repair = _repair_line(reason, wref, wval)
        if repair:
            entry.append(repair)
        rejected = fb.get("rejected_json")
        if rejected:
            text = str(rejected)
            if len(text) > 200:
                text = text[:197] + "..."
            entry.append(f"      rejected: {text}")
        block = "\n".join(entry)
        if reason == "rejected_initial":
            correctness.append(block)
        elif reason == "induction_failed":
            inductiveness.append(block)
        else:
            other.append(block)

    lines: list[str] = []
    if correctness:
        lines.append("=== Correctness failures (init / reachable) ===")
        lines.extend(correctness)
    if inductiveness:
        lines.append("=== Inductiveness failures (CTG-like) ===")
        lines.extend(inductiveness)
    if other:
        lines.append("=== Other failures ===")
        lines.extend(other)
    return "\n".join(lines)


def _negative_stats_from_feedback(feedback: list[dict]) -> list[dict]:
    stats: dict[tuple[str, str], int] = {}
    for fb in feedback:
        reason = fb.get("reason", "?")
        rejected = fb.get("rejected_json") or ""
        if not rejected:
            continue
        for m in re.finditer(r"!?((?:state|input)\d+)=(?:0|1)", str(rejected)):
            key = (m.group(0), reason)
            stats[key] = stats.get(key, 0) + 1
    return [
        {"lit": lit, "count": count, "reason": reason}
        for (lit, reason), count in sorted(stats.items(), key=lambda x: -x[1])
    ]


def _format_disjunct(dj: dict) -> str | None:
    atom = dj.get("atom") or {}
    ref = atom.get("ref") or ""
    if ref:
        return format_literal_line(ref, atom.get("rhs", ""), bool(dj.get("polarity", True)))
    expr = dj.get("expr")
    if expr:
        text = str(expr)
        if len(text) > 120:
            text = text[:117] + "..."
        return text
    return None


def _format_clause_line(clause: dict) -> str | None:
    parts: list[str] = []
    for dj in clause.get("disjuncts") or []:
        formatted = _format_disjunct(dj)
        if formatted:
            parts.append(formatted)
    if not parts:
        return None
    return " | ".join(parts)


def format_frame_summary_only(frame_snapshot: dict) -> str:
    snap = frame_snapshot or {}
    frame_idx = snap.get("frame_idx", 0)
    total = int(snap.get("clauses_total") or len(snap.get("clauses") or []))
    return (
        f"Frame (frame_idx={frame_idx}, clauses_total={total}): "
        "clause bodies omitted on attempt 1; use CTI digest and symbol hints."
    )


def format_frame_clause_digest(frame_snapshot: dict, feedback: list[dict] | None = None) -> str:
    snap = frame_snapshot or {}
    digest = snap.get("clause_digest") or {}
    frame_idx = snap.get("frame_idx", 0)
    total = int(digest.get("clauses_total") or snap.get("clauses_total") or 0)
    lines = [
        f"Clause digest (frame_idx={frame_idx}, clauses_total={total}):",
        "High-frequency blocking literals across frame:",
    ]
    for row in digest.get("literal_stats") or []:
        lit = row.get("lit", "?")
        count = row.get("count", 0)
        lines.append(f"  {lit}  (count={count})")
    neg = list(digest.get("negative_stats") or [])
    if feedback:
        neg = neg + _negative_stats_from_feedback(feedback)
    for row in neg:
        lit = row.get("lit", "?")
        count = row.get("count", 0)
        reason = row.get("reason", "?")
        lines.append(f"  AVOID {lit}  (count={count}, reason={reason})")
    sample_lines: list[str] = []
    for clause in snap.get("clauses") or []:
        line = _format_clause_line(clause)
        if line:
            sample_lines.append(line)
    if sample_lines:
        lines.append("")
        lines.append(f"Sample clauses (n={len(sample_lines)}, CTI/relevance-ranked):")
        lines.extend(sample_lines)
    lines.append("")
    lines.append(
        "MIC hint: keep literals matching high-frequency stats; "
        "drop CTI literals only in outlier cubes or negative_stats."
    )
    return "\n".join(lines)


def format_frame_snapshot(
    frame_snapshot: dict,
    max_clauses: int = 0,
    *,
    attempt: int = 1,
    has_feedback: bool = False,
    feedback: list[dict] | None = None,
) -> str:
    snap = frame_snapshot or {}
    if snap.get("clause_digest"):
        return format_frame_clause_digest(snap, feedback=feedback)
    if attempt == 1 and not has_feedback and max_clauses == 0:
        return format_frame_summary_only(snap)

    frame_idx = snap.get("frame_idx", 0)
    clauses = list(snap.get("clauses") or [])
    total = int(snap.get("clauses_total") or len(clauses))

    if max_clauses > 0 and total > max_clauses:
        clauses = clauses[-max_clauses:]
        header = (
            f"Frame snapshot (frame_idx={frame_idx}, "
            f"showing last {len(clauses)} of {total} clauses):"
        )
        note = (
            "Older clauses exist in the frame but are omitted below; "
            "avoid proposing blocks equivalent to listed clauses."
        )
    else:
        header = f"Frame snapshot (frame_idx={frame_idx}, {total} clauses):"
        note = ""

    lines: list[str] = []
    for clause in clauses:
        line = _format_clause_line(clause)
        if line:
            lines.append(line)

    out = [header]
    if note:
        out.append(note)
    out.extend(lines)
    return "\n".join(out)


def format_cti_literals(cti: dict) -> str:
    seen: set[tuple[str, str, bool]] = set()
    lines: list[str] = []
    for ref, rhs, polarity in _iter_cube_literals(cti):
        key = (ref, rhs, polarity)
        if key in seen:
            continue
        seen.add(key)
        lines.append(format_literal_line(ref, rhs, polarity))
    header = f"CTI cube ({len(lines)} literals, ! = polarity false):"
    if not lines:
        return header
    return header + "\n" + "\n".join(lines)


def _truncate_cube_body(body: str, max_chars: int = 280) -> str:
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 3] + "..."


def format_cti_batch_digest(
    digest: dict,
    sample_entries: list[dict],
    *,
    max_sample_cubes: int = 8,
) -> str:
    """Statistical digest + representative sample cubes (not full enumeration)."""
    cti_total = int(digest.get("cti_total") or 0)
    shown = list(sample_entries[:max_sample_cubes])
    lines = [
        f"CTI digest (cti_total={cti_total}, sample_cubes={len(shown)}/{len(sample_entries)}):",
        "High-frequency literals across all CTI cubes:",
    ]
    for row in (digest.get("literal_stats") or [])[:20]:
        lit = row.get("lit", "?")
        count = row.get("count", 0)
        lines.append(f"  {lit}  (count={count})")
    lines.append("")
    lines.append("Representative sample cubes:")
    for ent in shown:
        cid = ent.get("cti_id", "?")
        if ent.get("literals"):
            body = " | ".join(ent["literals"][:12])
        else:
            lit_text = format_cti_literals(ent.get("cti") or {})
            body_lines = lit_text.split("\n")
            if len(body_lines) > 1:
                body = " | ".join(body_lines[1:13])
            else:
                body = body_lines[0] if body_lines else "(empty)"
        lines.append(f"[{cid}] {_truncate_cube_body(body)}")
    return "\n".join(lines)


def format_cti_batch_all(entries: list[dict]) -> str:
    """Compact listing of all CTI cubes in a blocking-round batch."""
    lines = [f"All CTI cubes this blocking round (cti_total={len(entries)}):"]
    for ent in entries:
        cid = ent.get("cti_id", "?")
        lit_text = format_cti_literals(ent.get("cti") or {})
        body_lines = lit_text.split("\n")
        if len(body_lines) > 1:
            body = " | ".join(body_lines[1:])
        else:
            body = body_lines[0] if body_lines else "(empty)"
        lines.append(f"[{cid}] {body}")
    return "\n".join(lines)
