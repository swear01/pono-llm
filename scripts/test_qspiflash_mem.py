#!/usr/bin/env python3
"""
Test LLM-guided on qspiflash and mem_slave_tlm candidates.
These have known-init symmetric pairs and manageable state counts.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hwmcc_llm_benchmark as bench

bench.BENCHMARKS = {
    "qspi-p151": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2019/wolf/2019C/qspiflash_dualflexpress_divthree-p151.btor2"),
    "qspi-p162": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2019/wolf/2019C/qspiflash_dualflexpress_divfive-p162.btor2"),
    "qspi-p65": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2019/wolf/2019C/qspiflash_qflexpress_divfive-p65.btor2"),
    "mem_slave": Path("/home/swear01/hwmcc_benchmarks/2025/wordlevel/bv/2025/sosylab/safety-func/systemc/mem_slave_tlm.4.cil.btor2"),
}

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--timeout", "120"]
    bench.main()
