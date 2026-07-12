#!/usr/bin/env python3
"""Render matched source, lifted, and raw views for grammar routing."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR / "llm_worker"))

from btor2_reader import (  # noqa: E402
    build_bad_condition_text,
    build_transition_sketch,
    parse_btor2,
)
import build_paired_corpus  # noqa: E402
import cert_check  # noqa: E402
import grammar_routes  # noqa: E402
from experiment_manifest import file_sha256, stable_slug  # noqa: E402
import select_paired_pilot  # noqa: E402


VIEW_SCHEMA = "pono-llm-representation-view-bundle-v1"
ARMS = ("source", "lifted", "raw")
_LEXICAL_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def lexical_token_count(text: str) -> int:
    return sum(1 for _ in _LEXICAL_TOKEN.finditer(text))


def truncate_lexically(text: str, budget: int) -> tuple[str, bool]:
    if budget <= 0:
        raise ValueError("lexical token budget must be positive")
    tokens = list(_LEXICAL_TOKEN.finditer(text))
    if len(tokens) <= budget:
        return text, False
    marker = "\n\n[... deterministic middle truncation ...]\n\n"
    marker_tokens = lexical_token_count(marker)
    if budget <= marker_tokens + 2:
        raise ValueError("lexical token budget is too small for truncation marker")
    available = budget - marker_tokens
    prefix_count = (available + 1) // 2
    suffix_count = available - prefix_count
    prefix_end = tokens[prefix_count - 1].end()
    suffix_start = tokens[-suffix_count].start()
    return text[:prefix_end] + marker + text[suffix_start:], True


def verify_pilot(path: Path) -> dict:
    pilot = json.loads(path.read_text())
    if pilot.get("schema") != select_paired_pilot.PILOT_SCHEMA:
        raise ValueError("paired pilot has the wrong schema")
    declared = pilot.get("pilot_sha256")
    computed = build_paired_corpus.canonical_sha256({
        key: value for key, value in pilot.items() if key != "pilot_sha256"
    })
    if declared != computed:
        raise ValueError(
            f"paired pilot hash mismatch: declared {declared}, got {computed}"
        )
    return pilot


def verify_task_paths(task: dict, translation_repo: Path, source_repo: Path) -> tuple[Path, Path]:
    btor2 = translation_repo / task["path"]
    source = source_repo / task["source_path"]
    for path, digest, label in (
        (btor2, task["content_sha256"], "BTOR2"),
        (source, task["source_sha256"], "source"),
    ):
        if not path.is_file():
            raise ValueError(f"missing frozen {label} file: {path}")
        actual = file_sha256(path)
        if actual != digest:
            raise ValueError(
                f"{label} hash mismatch for {task['benchmark_id']}: "
                f"expected {digest}, got {actual}"
            )
    return btor2, source


def render_source(source: Path) -> str:
    return (
        "REPRESENTATION: PINNED SOURCE C\n"
        f"SOURCE_FILE: {source.name}\n\n"
        + source.read_text(errors="strict")
    )


def render_lifted(btor2: Path, task: dict) -> str:
    info = parse_btor2(str(btor2))
    mapped_refs = [row["state_ref"] for row in task["source_state_mapping"]]
    pc_refs = sorted({phase["pc_ref"] for phase in task["phases"]})
    refs = sorted(
        set(mapped_refs + pc_refs), key=lambda ref: int(ref[5:])
    )
    transitions = build_transition_sketch(info, refs)
    if not transitions:
        raise ValueError(f"lifted view has no decoded transitions: {btor2}")
    bad = build_bad_condition_text(info)
    if not bad:
        raise ValueError(f"lifted view cannot decode BAD: {btor2}")
    lines = [
        "REPRESENTATION: TARGET-DERIVED LIFTED RECURRENCE",
        f"MODULE: {info.module_name}",
        "",
        "PHASES:",
    ]
    for phase in task["phases"]:
        lines.append(
            f"- {phase['phase_id']}: {phase['pc_ref']} == "
            f"{phase['value']} (width {phase['width']})"
        )
    lines += ["", "TRANSITIONS:"]
    lines.extend(f"- {transition}" for transition in transitions)
    lines += ["", "BAD:", f"- {bad}"]
    return "\n".join(lines) + "\n"


def raw_line_table(path: Path) -> dict[int, str]:
    lines = {}
    for raw in path.read_text(errors="strict").splitlines():
        content = raw.split(";", 1)[0].strip()
        if not content:
            continue
        first = content.split(maxsplit=1)[0]
        try:
            node = int(first)
        except ValueError as exc:
            raise ValueError(f"invalid BTOR2 node line in {path}: {raw}") from exc
        if node in lines:
            raise ValueError(f"duplicate BTOR2 node {node} in {path}")
        lines[node] = content
    return lines


def render_raw(btor2: Path, task: dict, node_budget: int = 1200) -> str:
    if node_budget <= 0:
        raise ValueError("raw node budget must be positive")
    info = parse_btor2(str(btor2))
    model = cert_check.parse_btor2(str(btor2))
    lines = raw_line_table(btor2)
    selected_states = {
        int(row["state_ref"][5:]) for row in task["source_state_mapping"]
    }
    selected_states.update(
        int(phase["pc_ref"][5:]) for phase in task["phases"]
    )
    roots = sorted(
        set(model["bads"])
        | set(model["constraints"])
        | {phase["equality_node"] for phase in task["phases"]}
        | {
            model["nexts"][state]
            for state in selected_states
            if state in model["nexts"]
        }
    )
    statement_by_state: dict[int, list[int]] = {}
    for node, tokens in model["raw"].items():
        op = tokens[1]
        if op in {"init", "next"} and len(tokens) >= 5:
            statement_by_state.setdefault(int(tokens[3]), []).append(node)

    queue = deque(roots)
    selected = set()
    expanded_states = set()
    truncated_frontier = set()
    while queue:
        node = abs(queue.popleft())
        if node in selected:
            continue
        if len(selected) >= node_budget:
            truncated_frontier.add(node)
            truncated_frontier.update(abs(value) for value in queue)
            break
        if node not in lines:
            continue
        selected.add(node)
        for dependency in info.deps.get(node, []):
            queue.append(abs(dependency))
        tokens = model["raw"].get(node, [])
        if len(tokens) >= 3 and tokens[1] not in {
            "bad", "constraint", "init", "next", "output"
        }:
            try:
                sort_node = int(tokens[2])
            except ValueError:
                sort_node = 0
            if sort_node in lines:
                queue.append(sort_node)
        if node in model["states"] and node not in expanded_states:
            expanded_states.add(node)
            if node in model["inits"]:
                queue.append(model["inits"][node])
            if node in model["nexts"]:
                queue.append(model["nexts"][node])

    selected.update(state for state in selected_states if state in lines)
    statement_nodes = set()
    for state in sorted(selected & set(model["states"])):
        statement_nodes.update(statement_by_state.get(state, []))
    for node, tokens in model["raw"].items():
        if tokens[1] in {"bad", "constraint"}:
            statement_nodes.add(node)
    selected.update(statement_nodes)

    header = [
        "REPRESENTATION: RAW BTOR2 PROPERTY/TRANSITION CONE",
        f"ROOT_EXPRESSION_NODES: {','.join(map(str, roots))}",
        f"NODE_BUDGET: {node_budget}",
        f"SELECTED_LINES: {len(selected)}",
        f"TRUNCATED_FRONTIER_COUNT: {len(truncated_frontier)}",
        "",
    ]
    body = [lines[node] for node in sorted(selected) if node in lines]
    if truncated_frontier:
        body += [
            "",
            "TRUNCATED_FRONTIER_NODES: "
            + ",".join(map(str, sorted(truncated_frontier)[:100])),
        ]
    return "\n".join(header + body) + "\n"


def common_route_contract(task: dict) -> str:
    variables = [
        {
            "name": row["source_name"],
            "ref": row["state_ref"],
            "width": row["width"],
            "init": row["init"],
        }
        for row in task["source_state_mapping"]
    ]
    phases = [
        {
            "phase_id": phase["phase_id"],
            "guard": f"{phase['pc_ref']} == {phase['value']}",
            "width": phase["width"],
        }
        for phase in task["phases"]
    ]
    return f"""

TASK: Choose a small invariant-synthesis grammar. Do not output an invariant,
proof, coefficient value, or assertion. The formal backend expands every route,
runs Houdini, and checks the original BTOR2. Your output is untrusted routing
advice only.

MACHINE SEMANTICS:
- All state arithmetic is fixed-width bit-vector arithmetic modulo 2^width.
- Comparisons must state signed or unsigned semantics.
- A route may use only variables from the catalog below.
- Phase guards are applied by the formal experiment, not selected by you.

VARIABLE_CATALOG_JSON:
{json.dumps(variables, indent=2, sort_keys=True)}

PHASE_CATALOG_JSON:
{json.dumps(phases, indent=2, sort_keys=True)}

OUTPUT CONTRACT:
- Output exactly one JSON object and no Markdown.
- Top-level fields: "schema" and "routes" only.
- schema must be "{grammar_routes.ROUTE_SCHEMA}".
- routes must contain 1 to 8 route objects.
- Every route has exactly variables, family, relations, signedness, plus only
  the family field listed below.
- family="unary": one variable; optional constants integer list [-16,16].
- family="pairwise_offset": two same-width variables; optional offsets integer
  list [-16,16].
- family="affine": two or three same-width variables; optional
  coefficient_bound integer [1,8].
- family="sum_equality": three same-width variables ordered as result, addend1,
  addend2; no family-specific field.
- family="quadratic_recurrence": two same-width variables ordered as accumulator,
  counter; optional scales [1,8] and counter_shifts [-4,4].
- relations is a non-empty subset of ["eq","le","ge"].
- signedness is exactly "signed" or "unsigned".
- No explanation and no extra fields.
""".strip() + "\n"


def render_arm(arm: str, btor2: Path, source: Path, task: dict) -> str:
    if arm == "source":
        return render_source(source)
    if arm == "lifted":
        return render_lifted(btor2, task)
    if arm == "raw":
        return render_raw(btor2, task)
    raise ValueError(f"unknown representation arm: {arm}")


def build_prompt(body: str, contract: str, total_budget: int) -> tuple[str, bool]:
    contract_tokens = lexical_token_count(contract)
    separator = "\n\n--- COMMON FORMAL ROUTE CONTRACT ---\n"
    overhead = lexical_token_count(separator) + contract_tokens
    body_budget = total_budget - overhead
    if body_budget <= 20:
        raise ValueError(
            f"total lexical budget {total_budget} leaves no representation budget"
        )
    budgeted_body, truncated = truncate_lexically(body, body_budget)
    prompt = budgeted_body.rstrip() + separator + contract
    if lexical_token_count(prompt) > total_budget:
        raise RuntimeError("budgeted prompt exceeds its lexical-token contract")
    return prompt, truncated


def build_bundle(
    pilot_path: Path,
    translation_repo: Path,
    source_repo: Path,
    output: Path,
    lexical_budget: int,
) -> dict:
    pilot = verify_pilot(pilot_path)
    build_paired_corpus.verify_repository(
        translation_repo,
        build_paired_corpus.TRANSLATION_REVISION,
        "translation",
    )
    build_paired_corpus.verify_repository(
        source_repo, build_paired_corpus.SOURCE_REVISION, "source"
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite representation bundle: {output}")
    output.mkdir(parents=True)

    records = []
    for task in pilot["benchmarks"]:
        btor2, source = verify_task_paths(task, translation_repo, source_repo)
        contract = common_route_contract(task)
        slug = stable_slug(task["benchmark_id"])
        for arm in ARMS:
            body = render_arm(arm, btor2, source, task)
            full_prompt = body.rstrip() + "\n\n--- COMMON FORMAL ROUTE CONTRACT ---\n" + contract
            prompt, truncated = build_prompt(body, contract, lexical_budget)
            relative = Path("prompts") / f"{slug}.{arm}.txt"
            full_relative = Path("full_prompts") / f"{slug}.{arm}.txt"
            path = output / relative
            full_path = output / full_relative
            path.parent.mkdir(parents=True, exist_ok=True)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(prompt)
            full_path.write_text(full_prompt)
            records.append({
                "benchmark_id": task["benchmark_id"],
                "content_sha256": task["content_sha256"],
                "source_sha256": task["source_sha256"],
                "source_family_id": task["source_family_id"],
                "selection_role": task["selection_role"],
                "arm": arm,
                "prompt_path": relative.as_posix(),
                "prompt_sha256": file_sha256(path),
                "prompt_lexical_tokens": lexical_token_count(prompt),
                "full_prompt_path": full_relative.as_posix(),
                "full_prompt_sha256": file_sha256(full_path),
                "full_prompt_lexical_tokens": lexical_token_count(full_prompt),
                "representation_truncated": truncated,
            })
    records.sort(key=lambda row: (row["benchmark_id"], row["arm"]))
    manifest = {
        "schema": VIEW_SCHEMA,
        "pilot_sha256": pilot["pilot_sha256"],
        "translation_revision": build_paired_corpus.TRANSLATION_REVISION,
        "source_revision": build_paired_corpus.SOURCE_REVISION,
        "lexical_tokenizer": r"Unicode regex \w+|[^\w\s]",
        "lexical_token_budget": lexical_budget,
        "arms": list(ARMS),
        "record_count": len(records),
        "records": records,
    }
    manifest["bundle_sha256"] = build_paired_corpus.canonical_sha256({
        key: value for key, value in manifest.items() if key != "bundle_sha256"
    })
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot")
    parser.add_argument("translation_repo")
    parser.add_argument("source_repo")
    parser.add_argument("--out", required=True)
    parser.add_argument("--lexical-token-budget", type=int, default=6000)
    args = parser.parse_args()
    if args.lexical_token_budget <= 100:
        parser.error("--lexical-token-budget must be greater than 100")
    output = Path(args.out)
    manifest = build_bundle(
        Path(args.pilot),
        Path(args.translation_repo).expanduser().resolve(),
        Path(args.source_repo).expanduser().resolve(),
        output,
        args.lexical_token_budget,
    )
    print(json.dumps({
        "record_count": manifest["record_count"],
        "pilot_sha256": manifest["pilot_sha256"],
        "bundle_sha256": manifest["bundle_sha256"],
        "output": output.as_posix(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
