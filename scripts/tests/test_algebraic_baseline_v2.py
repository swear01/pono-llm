import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/"scripts"))
import build_algebraic_baseline_corpus_v2 as c
def test_fixed_cases_and_corpus(tmp_path):
 assert len(c.CASES)==6 and len({x.family for x in c.CASES})==4
 root=Path('/home/swear01/hwmcc_benchmarks')
 if not root.is_dir(): pytest.skip('HWMCC unavailable')
 out=tmp_path/'c2'; m=c.build(root,ROOT/'artifacts/phase1_2_frozen_v2',out); assert m['query_count']==6; assert c.validate(out)==m
 assert all((out/q['query']).is_file() for q in m['queries'])
 assert 'bv_poly_kernel' not in (ROOT/'scripts/build_algebraic_baseline_corpus_v2.py').read_text()
