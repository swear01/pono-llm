#!/usr/bin/env python3
"""
Scan HWMCC 2025 wordlevel BV benchmarks for Class-A candidates.

Class-A: pono times out AND detect_symmetric_pairs() finds at least one pair.
These are prime targets for LLM-guided eq() invariant injection.

Usage:
    python3 scripts/scan_class_a.py [--all] [--limit N]

    --all    scan all 330 benchmarks (not just pono timeouts)
    --limit  stop after N files (default: all)

Output: TSV to stdout, sorted by pair count descending.
"""

import argparse
import csv
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm_worker"))
from btor2_reader import parse_btor2, detect_symmetric_pairs  # noqa: E402

HWMCC25_BV_DIR = "/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv"
HWMCC25_CSV    = "/home/swear01/hwmcc_benchmarks/2025/hwmcc25-wordlevel-bv.csv"


def load_pono_timeouts(csv_path: str) -> set[str]:
    """Return set of relative benchmark paths where pono timed out."""
    timeouts: set[str] = set()
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if row["config"] == "pono" and row["result"] == "none":
                timeouts.add(row["benchmark"])
    return timeouts


def load_pono_results(csv_path: str) -> dict[str, str]:
    """Return {rel_path: result} for pono rows."""
    results: dict[str, str] = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if row["config"] == "pono":
                results[row["benchmark"]] = row["result"]
    return results


def rel_path(abs_path: str) -> str:
    """Convert absolute .btor2 path to HWMCC 2025 relative path."""
    # /home/.../2025/wordlevel/bv/2019/beem/foo.btor2 -> 2019/beem/foo.btor2
    marker = "/wordlevel/bv/"
    idx = abs_path.find(marker)
    if idx == -1:
        return abs_path
    return abs_path[idx + len(marker):]


def scan_file(abs_path: str, max_pairs: int = 500, max_mb: float = 3.0) -> dict:
    """Parse one .btor2 and return symmetry info. Returns {} on parse error."""
    try:
        # Skip large files before parsing to avoid OOM
        size_mb = os.path.getsize(abs_path) / 1e6
        if size_mb > max_mb:
            return {"num_states": -1, "num_inputs": -1,
                    "pairs": [], "note": f"skipped-large-{size_mb:.1f}MB"}
        info = parse_btor2(abs_path)
        refs = [sv.ref for sv in info.states]
        # Skip very large state counts to avoid O(N²) blowup
        if len(refs) > 300:
            return {"num_states": len(info.states), "num_inputs": len(info.inputs),
                    "pairs": [], "note": "skipped-many-states"}
        pairs = detect_symmetric_pairs(info, refs)
        return {
            "num_states": len(info.states),
            "num_inputs": len(info.inputs),
            "pairs": pairs[:max_pairs],
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="scan all benchmarks, not just pono timeouts")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    pono_results = load_pono_results(HWMCC25_CSV)
    timeouts = {k for k, v in pono_results.items() if v == "none"}

    all_btor2 = []
    for root, _, files in os.walk(HWMCC25_BV_DIR):
        for f in files:
            if f.endswith(".btor2"):
                abs_p = os.path.join(root, f)
                all_btor2.append(abs_p)
    all_btor2.sort()

    if args.all:
        targets = all_btor2
    else:
        targets = [p for p in all_btor2 if rel_path(p) in timeouts]

    if args.limit:
        targets = targets[:args.limit]

    print(f"# Scanning {len(targets)} benchmarks "
          f"({'all' if args.all else 'pono-timeout only'})", file=sys.stderr)

    header = ["benchmark", "rel_path", "pono_result", "num_states",
              "num_inputs", "num_pairs", "pairs", "note"]
    print("\t".join(header))

    found_class_a = 0
    errors = 0
    t0 = time.time()

    for i, abs_p in enumerate(targets):
        rp = rel_path(abs_p)
        pono_res = pono_results.get(rp, "unknown")
        result = scan_file(abs_p)

        if "error" in result:
            errors += 1
            row = [os.path.basename(abs_p), rp, pono_res, "?", "?", "0", "", result["error"]]
        else:
            num_pairs = len(result["pairs"])
            pair_str = "; ".join(f"eq({a},{b})" for a, b in result["pairs"])
            note = "CLASS-A" if num_pairs > 0 and pono_res == "none" else ""
            if note:
                found_class_a += 1
            row = [
                os.path.basename(abs_p), rp, pono_res,
                str(result["num_states"]), str(result["num_inputs"]),
                str(num_pairs), pair_str, note,
            ]
        print("\t".join(row))

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"# {i+1}/{len(targets)} done in {elapsed:.1f}s, "
                  f"class-a={found_class_a} errors={errors}", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"# Done: {len(targets)} files, {found_class_a} Class-A, "
          f"{errors} errors, {elapsed:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
