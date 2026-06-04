"""Compact text formats for sidecar LLM prompts (no C++/schema changes)."""

from __future__ import annotations

from typing import Any, Iterable


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


def format_frame_snapshot(frame_snapshot: dict, max_clauses: int = 0) -> str:
    snap = frame_snapshot or {}
    frame_idx = snap.get("frame_idx", 0)
    clauses = list(snap.get("clauses") or [])
    total = len(clauses)

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
        parts: list[str] = []
        for dj in clause.get("disjuncts") or []:
            formatted = _format_disjunct(dj)
            if formatted:
                parts.append(formatted)
        if parts:
            lines.append(" | ".join(parts))

    out = [header]
    if note:
        out.append(note)
    out.extend(lines)
    return "\n".join(out)


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
