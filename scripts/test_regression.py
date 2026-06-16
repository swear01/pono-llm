#!/usr/bin/env python3
"""Regression test: fib_05 and diffeq with fixed hot_refs secondary phase."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

bench.BENCHMARKS = {
    "fib_05": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/arithmetic_circuits/fib_05/fib_05.btor2"),
    "diffeq": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/seq/diffeq_1_4/diffeq.btor2"),
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
