#!/usr/bin/env python3
"""Audit BTOR2 transition translator: classify ALL 127 failures.

Produces:
  logs/formal_yield/btor2_translation_failures.json
  logs/formal_yield/shortlist_dependency_cones.json
"""

import json, os, sys, re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)

# Target variables for shortlisted candidates
TARGET_STATES = {"79", "790", "1536", "1558", "2002"}


def parse_btor2(path):
    btor = {}
    for line in open(path):
        parts = line.strip().split()
        if not parts or parts[0][0] == ";": continue
        try: int(parts[0])
        except: continue
        btor[parts[0]] = parts[1:]
    return btor


def get_deps_recursive(btor, node_id, visited=None):
    """Get all recursive BTOR2 node dependencies."""
    if visited is None:
        visited = set()
    if node_id in visited or node_id not in btor:
        return set()
    visited.add(node_id)
    p = btor[node_id]
    op = p[0]
    deps = {node_id}
    if op in ("state", "input", "const", "zero", "ones", "sort", "bitvec"):
        return deps
    for arg in p[2:]:
        try:
            deps |= get_deps_recursive(btor, arg, visited)
        except Exception:
            pass
    return deps


def collect_operators(btor, node_id, visited=None):
    """Collect all operator types reachable from a node."""
    if visited is None:
        visited = set()
    if node_id in visited or node_id not in btor:
        return {}
    visited.add(node_id)
    p = btor[node_id]
    ops = {p[0]: 1}
    if p[0] in ("state", "input", "const", "zero", "ones", "sort", "bitvec"):
        return ops
    for arg in p[2:]:
        child_ops = collect_operators(btor, arg, visited)
        for k, v in child_ops.items():
            ops[k] = ops.get(k, 0) + v
    return ops


# --- Instrumented translation ---

def instrument_translate(btor, failures, translated_set, node_id, suffix="", depth=0, max_depth=30):
    """Translate a BTOR2 node and record failure details.
    Returns (success_bool, error_type, error_message).
    """
    if depth > max_depth:
        failures.append({
            "node_id": node_id,
            "op": btor.get(node_id, ["?"])[0],
            "raw_btor2": " ".join([node_id] + btor.get(node_id, [])),
            "error_type": "depth_overflow",
            "error_message": f"recursion depth {depth} exceeds max {max_depth}",
            "dependencies": [],
            "candidate_relevance": "unknown",
        })
        return False, "depth_overflow", f"depth {depth} > {max_depth}"

    if node_id not in btor:
        failures.append({
            "node_id": node_id,
            "op": "?",
            "raw_btor2": node_id,
            "error_type": "missing_node",
            "error_message": f"node {node_id} not found in BTOR2",
            "dependencies": [],
            "candidate_relevance": "unknown",
        })
        return False, "missing_node", f"node {node_id} not found"

    p = btor[node_id]
    op = p[0]

    # Terminal nodes - always succeed
    if op in ("const", "state", "input", "zero", "ones"):
        translated_set.add(node_id)
        return True, None, None

    # Recursively translate children first
    child_deps = []
    child_relevance = "low"
    for arg in p[2:]:
        ok, err_type, err_msg = instrument_translate(
            btor, failures, translated_set, arg, suffix, depth + 1, max_depth
        )
        if not ok:
            child_deps.append(arg)
            if err_type in ("slice_oob", "sort_mismatch", "sort_mismatch_concat",
                           "unsupported_op", "malformed_node"):
                child_relevance = "medium"

    # Check for known problematic patterns
    if op == "slice":
        if len(p) < 5:
            failures.append({
                "node_id": node_id,
                "op": op,
                "raw_btor2": " ".join([node_id] + p),
                "error_type": "malformed_node",
                "error_message": f"slice missing hi/lo (got {len(p)} parts)",
                "dependencies": child_deps,
                "candidate_relevance": child_relevance,
            })
            return False, "malformed_node", "slice missing parts"

        # BTOR2 slice format: slice <width> <expr> <hi> <lo>
        # Indices are inclusive. Validate.
        child_idx = 2
        hi_str, lo_str = p[3], p[4]
        child_node = p[child_idx]
        try:
            hi, lo = int(hi_str), int(lo_str)
        except ValueError:
            failures.append({
                "node_id": node_id,
                "op": op,
                "raw_btor2": " ".join([node_id] + p),
                "error_type": "malformed_node",
                "error_message": f"non-integer slice indices: hi={hi_str} lo={lo_str}",
                "dependencies": child_deps,
                "candidate_relevance": child_relevance,
            })
            return False, "malformed_node", "non-integer slice"

        # Check if we can determine source width
        if child_node in btor:
            child_p = btor[child_node]
            if child_p[0] == "state":
                src_w = int(child_p[1]) if len(child_p) > 1 else 1
                if hi >= src_w or lo > hi:
                    failures.append({
                        "node_id": node_id,
                        "op": op,
                        "raw_btor2": " ".join([node_id] + p),
                        "error_type": "slice_oob",
                        "error_message": f"slice {hi}:{lo} out of range for {src_w}-bit source (node {child_node})",
                        "dependencies": child_deps,
                        "candidate_relevance": child_relevance,
                    })
                    return False, "slice_oob", f"slice {hi}:{lo} OOB for {src_w}-bit"
            elif child_p[0] == "input":
                src_w = int(child_p[1]) if len(child_p) > 1 else 1
                if hi >= src_w or lo > hi:
                    failures.append({
                        "node_id": node_id,
                        "op": op,
                        "raw_btor2": " ".join([node_id] + p),
                        "error_type": "slice_oob",
                        "error_message": f"slice {hi}:{lo} out of range for {src_w}-bit input (node {child_node})",
                        "dependencies": child_deps,
                        "candidate_relevance": child_relevance,
                    })
                    return False, "slice_oob", f"slice {hi}:{lo} OOB for {src_w}-bit input"

    # concat sort check
    if op == "concat" and len(p) >= 4:
        arg_a, arg_b = p[2], p[3]
        # Check source widths if known
        wa, wb = None, None
        if arg_a in btor:
            if btor[arg_a][0] == "state":
                wa = int(btor[arg_a][1]) if len(btor[arg_a]) > 1 else 1
        if arg_b in btor:
            if btor[arg_b][0] == "state":
                wb = int(btor[arg_b][1]) if len(btor[arg_b]) > 1 else 1

    # collect unsupported ops
    supported = {
        "const", "state", "input", "zero", "ones",
        "not", "and", "or", "xor", "xnor",
        "eq", "neq", "add", "sub", "srl",
        "ult", "ulte", "ite", "slice", "concat",
        "redor", "redand", "uext",
        "next", "init", "sort", "cond",
    }

    if op not in supported:
        failures.append({
            "node_id": node_id,
            "op": op,
            "raw_btor2": " ".join([node_id] + p),
            "error_type": "unsupported_op",
            "error_message": f"operator '{op}' not in supported set",
            "dependencies": child_deps,
            "candidate_relevance": child_relevance,
        })
        return False, "unsupported_op", f"op '{op}' not supported"

    # If any child failed, mark this node as a cascade failure
    if child_deps:
        failures.append({
            "node_id": node_id,
            "op": op,
            "raw_btor2": " ".join([node_id] + p),
            "error_type": "missing_dependency",
            "error_message": f"depends on failed children: {child_deps}",
            "dependencies": child_deps,
            "candidate_relevance": child_relevance,
        })
        return False, "missing_dependency", f"child failures: {child_deps}"

    translated_set.add(node_id)
    return True, None, None


def compute_node_width(btor, node_id, cache=None):
    """Try to compute the bitwidth of a BTOR2 expression node.
    Returns width or None if unknown.
    """
    if cache is None:
        cache = {}
    if node_id in cache:
        return cache[node_id]
    if node_id not in btor:
        return None
    p = btor[node_id]
    op = p[0]

    if op == "const" and len(p) > 1:
        return int(p[1])
    if op == "state" and len(p) > 1:
        return int(p[1])
    if op == "input" and len(p) > 1:
        return int(p[1])
    if op in ("zero", "ones") and len(p) > 1:
        return int(p[1])
    if op == "not" and len(p) >= 3:
        return compute_node_width(btor, p[2], cache)
    if op in ("and", "or", "xor", "xnor", "redor", "redand", "eq", "neq",
              "ult", "ulte", "ugt", "uge"):
        return 1
    if op in ("add", "sub", "srl", "sll", "sra", "mul") and len(p) >= 3:
        return compute_node_width(btor, p[2], cache)
    if op == "ite" and len(p) >= 4:
        return compute_node_width(btor, p[3], cache)
    if op == "slice" and len(p) >= 5:
        try:
            return int(p[3]) - int(p[4]) + 1
        except (ValueError, IndexError):
            return None
    if op == "concat" and len(p) >= 4:
        wa = compute_node_width(btor, p[2], cache)
        wb = compute_node_width(btor, p[3], cache)
        if wa is not None and wb is not None:
            return wa + wb
    if op == "uext" and len(p) >= 3:
        base_w = compute_node_width(btor, p[2], cache)
        if base_w is not None:
            ext = int(p[1]) if len(p) > 1 else 0
            return max(base_w, ext)
    if op == "sext" and len(p) >= 3:
        base_w = compute_node_width(btor, p[2], cache)
        if base_w is not None:
            ext = int(p[1]) if len(p) > 1 else 0
            return max(base_w, ext)

    return None


def main():
    btor = parse_btor2(BTOR2_PATH)

    # --- Global audit: all transition lines ---
    next_lines = {lid: p for lid, p in btor.items() if p[0] == "next" and len(p) >= 4}
    total_transitions = len(next_lines)
    print(f"Total transition lines: {total_transitions}")

    failures = []
    translated = set()

    for lid, p in next_lines.items():
        next_expr = p[3]
        instrument_translate(btor, failures, translated, next_expr, "_next")

    num_translated = total_transitions - len(set(f["node_id"] for f in failures if f["op"] != "next"))
    # More precise: count unique transition targets that passed
    passed = 0
    for lid, p in next_lines.items():
        next_expr = p[3]
        if next_expr in translated:
            passed += 1

    print(f"Translated: {passed}")
    print(f"Failed: {total_transitions - passed}")

    # Deduplicate failures (keep only leaf failures, not cascade)
    cascade_ops = set()
    for f in failures:
        if f["error_type"] == "missing_dependency":
            cascade_ops.add(f["node_id"])

    leaf_failures = [f for f in failures if f["error_type"] != "missing_dependency"]
    cascade_failures = [f for f in failures if f["error_type"] == "missing_dependency"]

    print(f"Leaf failures: {len(leaf_failures)}, Cascade: {len(cascade_failures)}")

    # Classify by error type
    error_types = defaultdict(list)
    for f in leaf_failures:
        error_types[f["error_type"]].append(f)

    print("\n=== Failure Types ===")
    for et, flist in sorted(error_types.items(), key=lambda x: -len(x[1])):
        print(f"  {et}: {len(flist)}")

    # --- Mark candidate relevance ---
    # For each target state, get all dependencies
    target_dep_sets = {}
    for sid in TARGET_STATES:
        next_lid = None
        for lid, p in next_lines.items():
            if p[2] == sid:
                next_lid = p[3]
                break
        if next_lid:
            target_dep_sets[sid] = get_deps_recursive(btor, next_lid)

    # Mark which failures are candidate-relevant
    relevant_set = set()
    for sid, deps in target_dep_sets.items():
        relevant_set |= deps

    for f in leaf_failures:
        nid = f["node_id"]
        if nid in relevant_set:
            f["candidate_relevance"] = "high"
        elif any(nid in deps for deps in target_dep_sets.values()):
            f["candidate_relevance"] = "medium"
        else:
            f["candidate_relevance"] = "low"

    relevant_leaf = [f for f in leaf_failures if f["candidate_relevance"] in ("high", "medium")]
    print(f"\nCandidate-relevant leaf failures: {len(relevant_leaf)}")

    # --- Save failure classification ---
    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)

    # Build per-node failure map (node_id -> list of errors)
    failure_map = defaultdict(list)
    for f in leaf_failures:
        failure_map[f["node_id"]].append(f)
    for f in cascade_failures:
        failure_map[f["node_id"]].append(f)

    # For each transition line, record its status and failures
    transition_records = []
    for lid, p in sorted(next_lines.items(), key=lambda x: int(x[0])):
        sid = p[2]
        next_expr = p[3]
        deps = get_deps_recursive(btor, next_expr) - {next_expr}
        ops = collect_operators(btor, next_expr)
        is_relevant = bool(deps & relevant_set) or sid in TARGET_STATES

        transition_records.append({
            "transition_line": lid,
            "state_id": sid,
            "next_expr_node": next_expr,
            "dependency_count": len(deps),
            "operator_types": sorted(ops.keys()),
            "translated": next_expr in translated,
            "failure_nodes": [
                {"node_id": nid, "error_type": failure_map[nid][0]["error_type"],
                 "error_message": failure_map[nid][0]["error_message"]}
                for nid in sorted(deps & set(failure_map.keys()))
            ] if next_expr not in translated else [],
            "candidate_relevant": is_relevant,
        })

    failures_file = os.path.join(out_dir, "btor2_translation_failures.json")
    classification = {
        "btor2_path": BTOR2_PATH,
        "total_transition_lines": total_transitions,
        "translated": passed,
        "failed": total_transitions - passed,
        "leaf_failures": len(leaf_failures),
        "cascade_failures": len(cascade_failures),
        "unique_failing_nodes": len(set(f["node_id"] for f in leaf_failures)),
        "error_type_distribution": {k: len(v) for k, v in error_types.items()},
        "candidate_relevant_leaf_failures": len(relevant_leaf),
        "supported_operators": [
            "const", "state", "input", "zero", "ones",
            "not", "and", "or", "xor", "xnor",
            "eq", "neq", "add", "sub", "srl",
            "ult", "ulte", "ite", "slice", "concat",
            "redor", "redand", "uext",
        ],
        "unsupported_operators_encountered": [],
        "leaf_failures": sorted(leaf_failures, key=lambda f: -len(f.get("dependencies", []))),
        "transition_records": sorted(transition_records,
            key=lambda r: (1 if r["candidate_relevant"] else 0, -len(r["failure_nodes"]))),
    }

    # Collect unsupported ops
    unsupp = set()
    for f in leaf_failures:
        if f["error_type"] == "unsupported_op":
            unsupp.add(f["raw_btor2"].split()[1] if len(f["raw_btor2"].split()) > 1 else "?")
    classification["unsupported_operators_encountered"] = sorted(unsupp)

    with open(failures_file, "w") as f:
        json.dump(classification, f, indent=2)
    print(f"\nSaved: {failures_file}")

    # --- Dependency cones for shortlisted candidates ---
    print("\n=== Dependency Cones for Shortlisted Candidates ===")

    SHORTLIST = [
        {"rank": 1, "lemma": "(=> (= state1536 10) (= state790 0))",
         "vars": ["state1536", "state790"], "targets": ["1536", "790"]},
        {"rank": 2, "lemma": "(=> (= state1536 0) (= state1558 0))",
         "vars": ["state1536", "state1558"], "targets": ["1536", "1558"]},
        {"rank": 3, "lemma": "(=> (= state2002 1) (= state1536 0))",
         "vars": ["state2002", "state1536"], "targets": ["2002", "1536"]},
        {"rank": 4, "lemma": "(! (and (= state1536 10) (= state79 1)))",
         "vars": ["state1536", "state79"], "targets": ["1536", "79"]},
        {"rank": 5, "lemma": "(=> (= state1536 11) (= ((_ extract 12 12) i_wb_data) 1))",
         "vars": ["state1536", "i_wb_data"], "targets": ["1536"], "has_input": True},
    ]

    cone_records = []
    for cand in SHORTLIST:
        all_deps = set()
        all_next_nodes = {}
        all_failing = set()
        for sid in cand["targets"]:
            next_lid = None
            for lid, p in next_lines.items():
                if p[2] == sid:
                    next_lid = p[3]
                    break
            all_next_nodes[sid] = next_lid
            if next_lid:
                deps = get_deps_recursive(btor, next_lid)
                all_deps |= deps
                for dep in deps:
                    if dep in set(f["node_id"] for f in leaf_failures):
                        all_failing.add(dep)

        # Check which target states have translated next-state
        translated_targets = []
        blocked_targets = []
        for sid in cand["targets"]:
            nid = all_next_nodes.get(sid)
            if nid and nid in translated:
                translated_targets.append(sid)
            elif nid:
                # Find root failure
                root_failures = [f for f in leaf_failures if f["node_id"] in get_deps_recursive(btor, nid)]
                blocked_targets.append({
                    "state": sid,
                    "next_node": nid,
                    "failures": [
                        {"node": f["node_id"], "type": f["error_type"], "msg": f["error_message"]}
                        for f in root_failures[:5]
                    ]
                })
            else:
                blocked_targets.append({"state": sid, "next_node": None, "failures": [{"type": "no_next", "msg": "no next line found"}]})

        cone_size = len(all_deps)
        can_generate_queries = len(blocked_targets) == 0

        cone_records.append({
            "rank": cand["rank"],
            "lemma": cand["lemma"],
            "variables": cand["vars"],
            "target_states": cand["targets"],
            "next_state_nodes": all_next_nodes,
            "cone_size": cone_size,
            "translation_status": "fully_translated" if can_generate_queries else "blocked",
            "translated_targets": translated_targets,
            "blocked_targets": blocked_targets,
            "blocking_failures": [f["error_type"] for f in leaf_failures if f["node_id"] in all_failing],
            "can_generate_init_query": True,
            "can_generate_one_step_query": can_generate_queries,
            "can_generate_self_induction_query": can_generate_queries,
        })

    for cr in cone_records:
        print(f"\n  Candidate {cr['rank']}: {cr['lemma'][:60]}")
        print(f"    Cone size: {cr['cone_size']}, Status: {cr['translation_status']}")
        print(f"    Translated: {cr['translated_targets']}")
        for bt in cr["blocked_targets"]:
            print(f"    Blocked: state{bt['state']} (next=L{bt['next_node']})")
            for bf in bt["failures"]:
                print(f"      - {bf['type']}: {bf['msg'][:80]}")

    cones_file = os.path.join(out_dir, "shortlist_dependency_cones.json")
    with open(cones_file, "w") as f:
        json.dump(cone_records, f, indent=2)
    print(f"\nSaved: {cones_file}")

    # --- Print top examples per error type ---
    print("\n=== Top Examples Per Error Type ===")
    for et in ["slice_oob", "unsupported_op", "missing_node"]:
        examples = error_types.get(et, [])
        if examples:
            print(f"\n  {et} ({len(examples)} total):")
            for ex in examples[:3]:
                print(f"    {ex['raw_btor2'][:120]}")
                print(f"    -> {ex['error_message']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
