#!/usr/bin/env python3
"""
Test LLM-guided IC3IA on brp2.3.prop3-func-interl.btor2.
brp2 has 3 HOT symmetric pairs (a_ok_SClient, a_ok_RClient, dve_invalid all eq).
These should be injected as Stage 0 invariants and close the proof.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

bench.BENCHMARKS = {
    "brp2": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2019/beem/brp2.3.prop3-func-interl.btor2"),
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
