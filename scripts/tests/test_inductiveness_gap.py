import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'scripts'))
import diagnose_inductiveness_gap as d

def model(path,init):
 path.write_text('\n'.join(['1 sort bitvec 1','2 sort bitvec 8','3 zero 2','4 one 2','5 state 2 x',f'6 init 2 5 {4 if init else 3}','7 next 2 5 5','8 bad 5'])+'\n')
def eq0(): return {'form':'eq','args':[{'form':'ref','ref':'state5'},{'form':'const','const':'0','width':8}]}
def phase_model(path,guarded_bad):
 lines=['1 sort bitvec 1','2 zero 1','3 one 1','4 state 1 c','5 state 1 d0','6 state 1 d1','7 state 1 d2','8 state 1 x','9 init 1 4 2','10 init 1 5 2','11 init 1 6 2','12 init 1 7 2','13 init 1 8 2','14 next 1 4 4','15 next 1 5 4','16 next 1 6 5','17 next 1 7 6','18 ite 1 4 7 2','19 next 1 8 18','20 eq 1 4 2','21 eq 1 8 3']
 lines.extend(['22 and 1 20 21','23 bad 22'] if guarded_bad else ['22 bad 21'])
 path.write_text('\n'.join(lines)+'\n')
def x0(): return {'form':'eq','args':[{'form':'ref','ref':'state8'},{'form':'const','const':'0','width':1}]}
def c0(): return {'form':'eq','args':[{'form':'ref','ref':'state4'},{'form':'const','const':'0','width':1}]}
def test_false_initial_candidate_is_classified(tmp_path):
 p=tmp_path/'m.btor2'; model(p,1); r=d.diagnose_case(p,[eq0()],timeout_ms=2000,max_repair_sec=1)
 assert r['classification']=='FALSE_CANDIDATE'
 assert r['candidates'][0]['first_reachable_violation_depth']==0
 assert r['bounded_correctness']['violating_candidate_ids']==[0]
 assert r['bounded_correctness']['first_reachable_violation_depth']==0
 assert r['houdini']['removed_initial_indices']==[0]
 assert r['houdini']['initial_candidate_count']==1
 assert r['houdini']['surviving_candidate_ids']==[]
 assert r['k_induction_status']=='skipped-false-or-undecided-candidate'
 assert r['cti']['status']=='not-applicable'
def test_true_candidate_is_inductive_but_property_insufficient(tmp_path):
 p=tmp_path/'m.btor2'; model(p,0); p.write_text(p.read_text().replace('8 bad 5\n','8 one 1\n9 bad 8\n')); r=d.diagnose_case(p,[eq0()],timeout_ms=2000,max_repair_sec=1)
 assert r['classification']=='PROPERTY_INSUFFICIENT'
 assert r['conjunction']['c2_result']=='unsat'
 assert r['conjunction']['c3_result']=='sat'

def test_bounded_repair_finds_guard_structure_after_k_induction_fails(tmp_path):
 p=tmp_path/'guarded.btor2'; phase_model(p,True)
 r=d.diagnose_case(p,[x0()],timeout_ms=2000,max_repair_sec=2,repair_pool=[])
 assert [row['success'] for row in r['k_induction']]==[False,False,False]
 assert r['cti']['full_cti_reachable'] is False
 assert r['cti']['blocking_depth']==16
 assert r['classification']=='GUARD_STRUCTURE'
 assert r['micro_repair']['accepted'] is True
 assert r['micro_repair']['helper_count']==1
 assert r['micro_repair']['proof']=={'c1_result':'unsat','c2_result':'unsat','c3_result':'unsat'}

def test_bounded_repair_finds_one_existing_helper(tmp_path):
 p=tmp_path/'helper.btor2'; phase_model(p,False)
 r=d.diagnose_case(p,[x0()],timeout_ms=2000,max_repair_sec=2,repair_pool=[c0()])
 assert r['classification']=='MISSING_HELPER'
 assert r['micro_repair']['accepted'] is True
 assert r['micro_repair']['helper_count']<=2
 assert r['micro_repair']['proof']=={'c1_result':'unsat','c2_result':'unsat','c3_result':'unsat'}

def test_repair_budget_cannot_exceed_preregistered_limit(tmp_path):
 p=tmp_path/'m.btor2'; model(p,0)
 with pytest.raises(ValueError,match='max_repair_sec'):
  d.diagnose_case(p,[eq0()],timeout_ms=2000,max_repair_sec=31)
