import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'scripts'))
import diagnose_inductiveness_gap as d

def model(path,init):
 path.write_text('\n'.join(['1 sort bitvec 1','2 sort bitvec 8','3 zero 2','4 one 2','5 state 2 x',f'6 init 2 5 {4 if init else 3}','7 next 2 5 5','8 bad 5'])+'\n')
def eq0(): return {'form':'eq','args':[{'form':'ref','ref':'state5'},{'form':'const','const':'0','width':8}]}
def test_false_initial_candidate_is_classified(tmp_path):
 p=tmp_path/'m.btor2'; model(p,1); r=d.diagnose_case(p,[eq0()],timeout_ms=2000,max_repair_sec=1)
 assert r['classification']=='FALSE_CANDIDATE'
 assert r['candidates'][0]['first_reachable_violation_depth']==0
 assert r['houdini']['removed_initial_indices']==[0]
def test_true_candidate_is_inductive_but_property_insufficient(tmp_path):
 p=tmp_path/'m.btor2'; model(p,0); p.write_text(p.read_text().replace('8 bad 5\n','8 one 1\n9 bad 8\n')); r=d.diagnose_case(p,[eq0()],timeout_ms=2000,max_repair_sec=1)
 assert r['classification']=='PROPERTY_INSUFFICIENT'
 assert r['conjunction']['c2_result']=='unsat'
 assert r['conjunction']['c3_result']=='sat'
