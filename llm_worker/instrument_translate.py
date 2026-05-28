#!/usr/bin/env python3
"""Instrument BTOR2SMT._translate to capture exact failure reasons per node.

Produces a precise per-node failure classification.
"""

import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smt_checker import BTOR2SMT, parse_btor2

BTOR2_PATH = os.path.expanduser(
    "~/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/"
    "qspiflash_dualflexpress_divfive-p040.btor2"
)

TARGET_STATES = {"79", "790", "1536", "1558", "2002"}


def main():
    btor = parse_btor2(BTOR2_PATH)

    # Build BTOR2SMT for the real translator
    btor_smt = BTOR2SMT(btor)
    original_translate = btor_smt._translate

    # Instrumentation
    translate_log = {}  # node_id -> {success, error_type, error_msg}

    def instrumented_translate(lid, suffix="", depth=0):
        """Wraps original _translate to log failures."""
        result = original_translate(lid, suffix, depth)
        if lid not in translate_log:
            if result is not None:
                translate_log[lid] = {"success": True, "suffix": suffix}
            else:
                # Determine why it failed
                if lid not in btor:
                    translate_log[lid] = {
                        "success": False,
                        "error_type": "missing_node",
                        "error_msg": f"node {lid} not in BTOR2",
                        "btor2_line": "(missing)"
                    }
                elif depth > 30:
                    translate_log[lid] = {
                        "success": False,
                        "error_type": "depth_overflow",
                        "error_msg": f"depth {depth} > 30",
                        "btor2_line": " ".join([lid] + btor[lid])
                    }
                else:
                    p = btor[lid]
                    op = p[0]
                    # Try to get more specific error
                    if op == "slice" and len(p) >= 5:
                        src_node = p[2]
                        try:
                            hi, lo = int(p[3]), int(p[4])
                        except ValueError:
                            translate_log[lid] = {
                                "success": False,
                                "error_type": "malformed_slice",
                                "error_msg": f"non-integer indices: hi={p[3]} lo={p[4]}",
                                "btor2_line": " ".join([lid] + p)
                            }
                            return None
                        # Check source width
                        if src_node in btor and btor[src_node][0] in ("state", "input"):
                            src_w = int(btor[src_node][1])
                            if hi >= src_w:
                                translate_log[lid] = {
                                    "success": False,
                                    "error_type": "slice_oob_hi",
                                    "error_msg": f"slice hi={hi} >= src_w={src_w} on node {src_node}",
                                    "btor2_line": " ".join([lid] + p)
                                }
                                return None
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "slice_translate_fail",
                            "error_msg": f"slice translation failed (src={src_node})",
                            "btor2_line": " ".join([lid] + p)
                        }
                    elif op in ("and", "or", "xor", "xnor", "eq", "neq",
                                "add", "sub", "srl", "ult", "ulte") and len(p) >= 4:
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "binop_child_fail",
                            "error_msg": f"child of {op} failed translation",
                            "btor2_line": " ".join([lid] + p)
                        }
                    elif op == "not" and len(p) >= 3:
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "unop_child_fail",
                            "error_msg": f"child of not failed translation",
                            "btor2_line": " ".join([lid] + p)
                        }
                    elif op == "ite" and len(p) >= 5:
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "ite_child_fail",
                            "error_msg": f"ite child failed translation",
                            "btor2_line": " ".join([lid] + p)
                        }
                    elif op == "concat" and len(p) >= 4:
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "concat_child_fail",
                            "error_msg": f"concat child failed translation",
                            "btor2_line": " ".join([lid] + p)
                        }
                    else:
                        translate_log[lid] = {
                            "success": False,
                            "error_type": "unknown",
                            "error_msg": f"translation returned None for {op}",
                            "btor2_line": " ".join([lid] + p)
                        }
                return None
        return result

    btor_smt._translate = instrumented_translate

    # --- Run get_transition_constraints to trigger translation of ALL next lines ---
    btor_smt.get_transition_constraints()

    # --- Analyze: which next lines succeeded/failed ---
    next_lines = {lid: p for lid, p in btor.items()
                  if p[0] == "next" and len(p) >= 4}

    transition_status = {}
    for lid, p in next_lines.items():
        sid = p[2]
        next_expr = p[3]
        name = f"state{sid}"
        if name not in btor_smt.next_vars:
            transition_status[lid] = {"status": "no_state_var", "sid": sid}
            continue

        visited = set()
        def check_success(nid):
            if nid in translate_log:
                return translate_log[nid].get("success", False)
            # If not in translate_log, might not have been visited
            # Check if it was cached
            if nid in btor_smt.cache:
                return True
            return None

        # Check if the top-level next_expr was successfully translated
        if next_expr in translate_log and translate_log[next_expr]["success"]:
            transition_status[lid] = {"status": "translated", "sid": sid, "next_expr": next_expr}
        else:
            # Collect failure tree
            failures = []
            def collect_failures(nid, depth=0):
                if depth > 20: return
                if nid in translate_log and not translate_log[nid].get("success"):
                    failures.append({"node": nid, "error_type": translate_log[nid]["error_type"],
                                     "error_msg": translate_log[nid]["error_msg"],
                                     "btor2": translate_log[nid].get("btor2_line", "?")})
                if nid in btor:
                    p = btor[nid]
                    op = p[0]
                    if op == "slice" and len(p) >= 3:
                        collect_failures(p[2], depth + 1)
                    elif op == "not" and len(p) >= 3:
                        collect_failures(p[2], depth + 1)
                    elif op == "ite" and len(p) >= 5:
                        collect_failures(p[2], depth + 1)
                        collect_failures(p[3], depth + 1)
                        collect_failures(p[4], depth + 1)
                    elif len(p) >= 4 and op in ("and", "or", "xor", "xnor", "eq", "neq",
                                                  "add", "sub", "srl", "ult", "ulte", "concat"):
                        collect_failures(p[2], depth + 1)
                        collect_failures(p[3], depth + 1)

            collect_failures(next_expr)

            # Find root cause (deepest unique failures)
            error_types = {}
            for f in failures:
                et = f["error_type"]
                if et not in error_types: error_types[et] = f

            transition_status[lid] = {
                "status": "failed",
                "sid": sid,
                "next_expr": next_expr,
                "error_types": list(error_types.keys()),
                "root_failures": [error_types[et] for et in sorted(error_types.keys())]
            }

    # Summary
    total = len(transition_status)
    translated = sum(1 for v in transition_status.values() if v["status"] == "translated")
    failed = sum(1 for v in transition_status.values() if v["status"] == "failed")
    skipped = sum(1 for v in transition_status.values() if v["status"] == "no_state_var")

    print(f"Total next lines: {total}")
    print(f"Translated: {translated}")
    print(f"Failed: {failed}")
    print(f"Skipped (no state var): {skipped}")

    # Error type distribution
    from collections import Counter
    error_counts = Counter()
    for v in transition_status.values():
        if v["status"] == "failed":
            for et in v["error_types"]:
                error_counts[et] += 1

    print("\n=== Error Type Distribution ===")
    for et, count in error_counts.most_common():
        print(f"  {et}: {count}")

    # Target state analysis
    print("\n=== Target State Transitions ===")
    for sid in TARGET_STATES:
        found = None
        for lid, v in transition_status.items():
            if v.get("sid") == sid:
                found = (lid, v)
                break
        if found:
            lid, v = found
            print(f"\n  state{sid} (next line {lid}, next_expr L{v['next_expr']}):")
            print(f"    Status: {v['status']}")
            if v["status"] == "failed":
                for et in v["error_types"]:
                    print(f"    Error: {et}")

    # Save detailed results
    out_dir = "logs/formal_yield"
    os.makedirs(out_dir, exist_ok=True)

    # Convert transition_status for JSON
    json_status = {}
    for lid, v in transition_status.items():
        key = f"line_{lid}_state_{v.get('sid','?')}"
        json_status[key] = {k: v for k, v in v.items() if k != "root_failures"}
        if v["status"] == "failed" and v.get("root_failures"):
            json_status[key]["root_failures"] = v["root_failures"][:3]

    result = {
        "btor2_path": BTOR2_PATH,
        "total_next_lines": total,
        "translated": translated,
        "failed": failed,
        "skipped": skipped,
        "error_type_distribution": dict(error_counts),
        "target_state_transitions": {
            sid: {
                "status": next(
                    (v["status"] for v in transition_status.values() if v.get("sid") == sid),
                    "not_found"
                ),
                "error_types": next(
                    (v.get("error_types", []) for v in transition_status.values()
                     if v.get("sid") == sid),
                    []
                )
            }
            for sid in TARGET_STATES
        },
        "per_transition": json_status
    }

    with open(os.path.join(out_dir, "btor2_translation_failures.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved: logs/formal_yield/btor2_translation_failures.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
