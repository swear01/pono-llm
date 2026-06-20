#!/usr/bin/env python3
"""
Software-benchmark pre-processor (portfolio mode).

Detects software-origin BTOR2 circuits (C-compiled with preserved variable names),
first tries k-induction and interpolation as a fast portfolio check, then falls
back to LLM-generated arithmetic loop invariants verified and injected as IC3IA
initial PREDICATES (sound over-approximation) for `pono --initial-predicates`.

stdout: always the ORIGINAL btor2 path (predicate injection never modifies the model).
stderr: FAST_ENGINE=<engine> if a portfolio engine proved it; PREDICATES=<json>
        if invariants were injected (run: pono --initial-predicates <json> <btor2>).

Usage:
    python3 scripts/preprocess_sw.py path/to/circuit.btor2

Example integration with pono (sound predicate injection):
    BTOR=$(python3 scripts/preprocess_sw.py circuit.btor2 2>/tmp/sw.log)
    ENGINE=$(grep 'FAST_ENGINE=' /tmp/sw.log | head -1 | sed 's/.*FAST_ENGINE=//')
    PREDS=$(grep 'PREDICATES='  /tmp/sw.log | head -1 | sed 's/.*PREDICATES=//')
    if [ -n "$ENGINE" ]; then
        build/pono --engine "$ENGINE" -k 500 "$BTOR"
    elif [ -n "$PREDS" ]; then
        build/pono --engine ic3ia -k 500 --initial-predicates "$PREDS" "$BTOR"
    else
        build/pono --engine ic3ia -k 500 "$BTOR"
    fi
"""
from __future__ import annotations

import argparse
import os
import sys

# Allow importing from llm_worker/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'llm_worker'))

from env_config import load_env
from invariant_arith import preprocess_software_benchmark
from llm_client import create_llm_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-process software-origin BTOR2 with LLM invariants")
    parser.add_argument("btor2", help="Path to BTOR2 file")
    parser.add_argument("--timeout-verify", type=int, default=8,
                        help="Per-candidate verification timeout in seconds (default: 8)")
    args = parser.parse_args()

    load_env()

    if not os.path.isfile(args.btor2):
        print(f"ERROR: file not found: {args.btor2}", file=sys.stderr)
        sys.exit(1)

    client = create_llm_client()
    pred_json, n_injected, fast_engine = preprocess_software_benchmark(
        args.btor2, client, timeout_s=args.timeout_verify
    )

    if fast_engine:
        # Signal to caller: run this engine on the ORIGINAL btor2, not IC3IA
        print(f"FAST_ENGINE={fast_engine}", file=sys.stderr)

    if pred_json:
        # SOUND predicate injection: caller runs
        #   pono -e ic3ia --initial-predicates <pred_json> <original btor2>
        print(f"[preprocess_sw] {n_injected} predicates injected", file=sys.stderr)
        print(f"PREDICATES={pred_json}", file=sys.stderr)

    # stdout is ALWAYS the original btor2 (predicate injection never modifies it).
    print(args.btor2)


if __name__ == "__main__":
    main()
