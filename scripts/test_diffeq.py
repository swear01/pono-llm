#!/usr/bin/env python3
"""
Test LLM-guided IC3IA on diffeq (differential equation benchmark).
diffeq has 6 symmetric pairs ALL in hot_refs (depth=6):
  eq(vu_1_buf, vx_1_buf), eq(vu_1_buf, vy_1_buf), eq(vx_1_buf, vy_1_buf)
  eq(vu_2_buf, vx_2_buf), eq(vu_2_buf, vy_2_buf), eq(vx_2_buf, vy_2_buf)
Previous test at depth=4 had 0 hot_refs -- now depth=6 should work.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

bench.BENCHMARKS = {
    "diffeq": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2024/hkust/seq/diffeq_1_4/diffeq.btor2"),
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
