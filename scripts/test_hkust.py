#!/usr/bin/env python3
"""
Test LLM-guided on HKUST arithmetic benchmarks.
These are similar to fib_05 which showed 6x speedup.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

HKUST_BASE = Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust")

bench.BENCHMARKS = {
    "fib_05": HKUST_BASE / "arithmetic_circuits/fib_05/fib_05.btor2",
    "fib_23": HKUST_BASE / "arithmetic_circuits/fib_23/fib_23.btor2",
    "gcd_23": HKUST_BASE / "seq/gcd_2_3/gcd_bit_width_large.btor2",
    "gcd_24": HKUST_BASE / "seq/gcd_2_4/gcd_bit_width_large.btor2",
    "counter": HKUST_BASE / "seq/counter_wrapper_1_3/counter_bit_width_small.btor2",
    "77c":    HKUST_BASE / "arithmetic_circuits/77.c/77.c.btor2",
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
