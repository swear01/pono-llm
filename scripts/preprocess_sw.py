#!/usr/bin/env python3
"""
Software-benchmark pre-processor (portfolio mode).

Detects software-origin BTOR2 circuits (C-compiled with preserved variable names),
first tries k-induction and interpolation as a fast portfolio check, then falls
back to LLM-generated arithmetic loop invariants verified and injected as BTOR2
`constraint` statements for IC3IA.

Outputs the path of the constrained BTOR2 (or the original path if nothing was injected).

Usage:
    python3 scripts/preprocess_sw.py path/to/circuit.btor2

Example integration with pono:
    CONSTRAINED=$(python3 scripts/preprocess_sw.py circuit.btor2)
    build/pono --engine ic3ia -k 500 $CONSTRAINED

    # For the portfolio fast path (check stderr for FAST_ENGINE=<engine>):
    python3 scripts/preprocess_sw.py circuit.btor2 2>/tmp/sw.log
    ENGINE=$(grep 'FAST_ENGINE=' /tmp/sw.log | head -1 | sed 's/.*FAST_ENGINE=//')
    if [ -n "$ENGINE" ]; then
        build/pono --engine "$ENGINE" -k 500 circuit.btor2
    else
        CONSTRAINED=$(cat /tmp/constrained_path)
        build/pono --engine ic3ia -k 500 "$CONSTRAINED"
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
    constrained, n_injected, fast_engine = preprocess_software_benchmark(
        args.btor2, client, timeout_s=args.timeout_verify
    )

    if fast_engine:
        # Signal to caller: use this engine, not IC3IA
        print(f"FAST_ENGINE={fast_engine}", file=sys.stderr)

    if n_injected > 0:
        print(f"[preprocess_sw] {n_injected} constraints injected", file=sys.stderr)

    print(constrained)


if __name__ == "__main__":
    main()
