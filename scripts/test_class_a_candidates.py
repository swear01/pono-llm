#!/usr/bin/env python3
"""
Quick LLM-guided test for new Class-A candidates found by scan_class_a.py.
Tests: fifo-p0, gcd_bit_width_large, diffeq.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Patch the BENCHMARKS dict in hwmcc_llm_benchmark
import hwmcc_llm_benchmark as bench

bench.BENCHMARKS = {
    "fifo-p0": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2020/mann/fifo-p0.btor2"),
    "gcd": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/seq/gcd_2_3/gcd_bit_width_large.btor2"),
    "diffeq": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/seq/diffeq_1_4/diffeq.btor2"),
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
