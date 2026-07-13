#!/usr/bin/env python3
"""Deterministically decompose why a frozen candidate set is not a proof."""
from __future__ import annotations
import argparse,hashlib,itertools,json,re,time
from pathlib import Path
import z3
from z3.z3util import get_vars
import candidate_cert_check,cert_check

DEPTHS=(1,2,4,8,16); K_VALUES=(2,3,4)
def csha(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
class Unroller:
 def __init__(self,path,asts):
  self.path=Path(path); self.base=candidate_cert_check.build_base_formulas(str(path)); self.model=self.base["model"]; self.pred=candidate_cert_check.compile_asts(asts,self.base); self.states={}; self.inputs={}; self._constraints={}; self._trans={}
  cache={}; self.next_expr={s:cert_check.build(self.model,self.model["nexts"][s],self.base["statevars"],self.base["inputvars"],cache) if s in self.model["nexts"] else self.base["statevars"][s] for s in self.model["states"]}
 def frame(self,t):
  if t not in self.states:
   self.states[t]={i:z3.BitVec(f"gap_state{i}@{t}",v.size()) for i,v in self.base["statevars"].items()}; self.inputs[t]={i:z3.BitVec(f"gap_input{i}@{t}",v.size()) for i,v in self.base["inputvars"].items()}
  return self.states[t],self.inputs[t]
 def subs(self,t):
  s,u=self.frame(t); return [(v,s[i]) for i,v in self.base["statevars"].items()]+[(v,u[i]) for i,v in self.base["inputvars"].items()]
 def at(self,e,t): return z3.substitute(e,*self.subs(t))
 def constraints(self,t):
  if t not in self._constraints: self._constraints[t]=self.at(self.base["constraints"],t)
  return self._constraints[t]
 def transition(self,t):
  if t not in self._trans:
   sn,_=self.frame(t+1); self._trans[t]=z3.And(*[sn[i]==self.at(e,t) for i,e in self.next_expr.items()])
  return self._trans[t]
 def init(self): return self.at(self.base["init"],0)
 def predicate(self,i,t): return self.at(self.pred[i],t)
 def conjunction(self,t): return z3.And(*[self.predicate(i,t) for i in range(len(self.pred))])
 def bad(self,t): return self.at(self.base["bad"],t)
 def path_formula(self,d): return z3.And(self.init(),self.constraints(0),*[z3.And(self.transition(t),self.constraints(t+1)) for t in range(d)])
def solve(f,timeout_ms):
 s=z3.Solver(); s.set(timeout=timeout_ms); s.add(f); start=time.perf_counter(); r=s.check(); return s,r,time.perf_counter()-start
def values(model,variables): return {str(v):str(model.eval(v,model_completion=True)) for v in sorted(variables,key=str)}
def result(f,timeout_ms,model_vars=()):
 s,r,wall=solve(f,timeout_ms); out={"result":str(r),"wall_time_sec":wall,"unknown_reason":s.reason_unknown() if r==z3.unknown else ""}
 if r==z3.sat:
  vals=values(s.model(),model_vars); out.update(model_hash=csha(vals),model_values=vals)
 return out,s.model() if r==z3.sat else None
def c123(path,asts,timeout_ms):
 checks=candidate_cert_check.certify(str(path),asts,timeout_ms); return {"c1_result":str(checks[0][1]),"c2_result":str(checks[1][1]),"c3_result":str(checks[2][1])}
def diagnose_case(path,asts,timeout_ms=20000,max_repair_sec=30,repair_pool=None):
 u=Unroller(path,asts); all_state0=list(u.frame(0)[0].values()); candidate_rows=[]; any_false=False
 for i,_ in enumerate(asts):
  trials=[]; first=None; max_valid=-1
  for d in (0,*DEPTHS):
   q=z3.And(u.path_formula(d),z3.Not(u.predicate(i,d))); rr,_=result(q,timeout_ms,list(u.frame(d)[0].values())); trials.append({"depth":d,**rr})
   if rr["result"]=="sat" and first is None: first=d; any_false=True
   if rr["result"]=="unsat": max_valid=d
  candidate_rows.append({"candidate_id":i,"bounded_checks":trials,"bounded_valid_up_to":max_valid,"first_reachable_violation_depth":first})
 one=z3.And(u.constraints(0),u.transition(0),u.constraints(1)); H0=u.conjunction(0); individual=[]
 for i in range(len(asts)):
  under_H,_=result(z3.And(one,H0,z3.Not(u.predicate(i,1))),timeout_ms,all_state0); alone,_=result(z3.And(one,u.predicate(i,0),z3.Not(u.predicate(i,1))),timeout_ms,all_state0); individual.append({"candidate_id":i,"under_conjunction":under_H,"alone":alone})
 conj_c2,cti_model=result(z3.And(one,H0,z3.Not(u.conjunction(1))),timeout_ms,all_state0); exact=c123(path,asts,timeout_ms); conjunction={"c1_result":exact["c1_result"],"c2_result":conj_c2["result"],"c3_result":exact["c3_result"],"cti_model_hash":conj_c2.get("model_hash")}
 houdini=candidate_cert_check.houdini_certify(str(path),asts,timeout_ms); survivors=[asts[i] for i in houdini["selected_indices"]]; survivor=c123(path,survivors,timeout_ms) if survivors else {"c1_result":"unsat","c2_result":"unsat","c3_result":"sat"}; houdini={**houdini,"survivor_results":survivor}
 krows=[]
 if not any_false:
  for k in K_VALUES:
   base,_=result(z3.And(u.path_formula(k-1),z3.Or(*[z3.Not(u.conjunction(t)) for t in range(k)])),timeout_ms); step_path=z3.And(*[z3.And(u.constraints(t),u.transition(t)) for t in range(k)],u.constraints(k)); step,_=result(z3.And(step_path,*[u.conjunction(t) for t in range(k)],z3.Not(u.conjunction(k))),timeout_ms); prop,_=result(z3.And(u.constraints(0),u.conjunction(0),u.bad(0)),timeout_ms); krows.append({"k":k,"base":base,"step":step,"property":prop,"success":all(x["result"]=="unsat" for x in (base,step,prop))})
 cti={"status":"not-applicable"}
 if cti_model is not None:
  full={i:cti_model.eval(v,model_completion=True) for i,v in u.frame(0)[0].items()}; refs={int(n[5:]) for a in asts for n in re.findall(r'"ref"\s*:\s*"(state\d+)"',json.dumps(a))}; badrefs={int(str(v)[5:]) for v in get_vars(u.base["bad"]) if re.fullmatch(r"state\d+",str(v))}; projections={"full":set(full),"support":refs,"bad_support":refs|badrefs}; cti={"model_hash":conj_c2.get("model_hash"),"support_variables":sorted(f"state{i}" for i in refs),"reachability":{}}
  for name,ids in projections.items():
   checks=[]
   for d in DEPTHS:
    cubes=[z3.And(*[u.frame(t)[0][i]==full[i] for i in sorted(ids)]) for t in range(d+1)]; rr,_=result(z3.And(u.path_formula(d),z3.Or(*cubes)),timeout_ms); checks.append({"depth":d,**rr})
   cti["reachability"][name]=checks
 repair={"status":"skipped","reason":"eligible only for bounded-valid-16 with unreached full CTI","search_seconds":0.0,"accepted":False}
 if any_false: classification="FALSE_CANDIDATE"
 elif houdini["ok"]: classification="SELECTION"
 elif any(x["success"] for x in krows): classification="K_INDUCTIVE"
 elif survivors and survivor["c1_result"]==survivor["c2_result"]=="unsat" and survivor["c3_result"]=="sat": classification="PROPERTY_INSUFFICIENT"
 elif exact["c1_result"]==exact["c2_result"]=="unsat" and exact["c3_result"]=="sat": classification="PROPERTY_INSUFFICIENT"
 else: classification="UNRESOLVED"
 return {"schema":"pono-inductiveness-gap-case-v1","benchmark_sha256":hashlib.sha256(Path(path).read_bytes()).hexdigest(),"candidate_count":len(asts),"classification":classification,"candidates":candidate_rows,"individual_c2":individual,"conjunction":conjunction,"houdini":houdini,"k_induction":krows,"cti":cti,"micro_repair":repair}
def main():
 p=argparse.ArgumentParser(); p.add_argument("model",type=Path); p.add_argument("candidates",type=Path); p.add_argument("output",type=Path); p.add_argument("--timeout-ms",type=int,default=20000); a=p.parse_args()
 try:
  asts=candidate_cert_check.load_predicate_asts(str(a.candidates)); r=diagnose_case(a.model,asts,a.timeout_ms); r["report_sha256"]=csha(r); a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n")
 except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,z3.Z3Exception) as e: print(e); return 1
 return 0
if __name__=="__main__": raise SystemExit(main())
