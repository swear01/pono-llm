#!/usr/bin/env python3
"""
Test with Stage 2 re-enabled (no longer skipped after Stage 0 injection).
Focus on diffeq (Stage 0 wasn't sufficient) and fib_05 (verify no regression).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

HKUST_BASE = Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust")

bench.BENCHMARKS = {
    "fib_05": HKUST_BASE / "arithmetic_circuits/fib_05/fib_05.btor2",
    "diffeq": HKUST_BASE / "seq/diffeq_1_4/diffeq.btor2",
    "fib_23": HKUST_BASE / "arithmetic_circuits/fib_23/fib_23.btor2",
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
