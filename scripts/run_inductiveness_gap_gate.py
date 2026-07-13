#!/usr/bin/env python3
"""Run Gate 5A on the six frozen Gate 4B0-v2 cases and close the gate."""
from __future__ import annotations
import argparse,hashlib,json
from collections import Counter
from pathlib import Path
import z3
import build_algebraic_baseline_corpus_v2 as corpus
import candidate_cert_check
import diagnose_inductiveness_gap as gap

def fsha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(gate4,capture,root,out,timeout_ms=20000,max_repair_sec=30):
 if out.exists(): raise FileExistsError(f"refusing to overwrite {out}")
 manifest=corpus.validate(gate4/"c2_queries"); out.mkdir(parents=True); cases=[]
 for q in manifest["queries"]:
  source=capture/q["candidate_source_file"]
  if fsha(source)!=q["candidate_source_file_sha256"]: raise ValueError("candidate source hash mismatch")
  entries=candidate_cert_check.load_predicate_entries(str(source)); entry=entries[q["candidate_row_index"]]
  if corpus.csha(entry["predicate_ast"])!=q["candidate_sha256"]: raise ValueError("candidate hash mismatch")
  report=gap.diagnose_case(root/q["benchmark_id"],[entry["predicate_ast"]],timeout_ms,max_repair_sec,[e["predicate_ast"] for e in entries]); report.update(benchmark_id=q["benchmark_id"],candidate_sha256=q["candidate_sha256"],family=q["recurrence_family"]); report["report_sha256"]=gap.csha(report); name=f"{Path(q['benchmark_id']).stem}.json"; (out/name).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n"); cases.append({"benchmark_id":q["benchmark_id"],"family":q["recurrence_family"],"classification":report["classification"],"report":name,"report_file_sha256":fsha(out/name),"report_sha256":report["report_sha256"]})
 counts=Counter(x["classification"] for x in cases); helper=[x for x in cases if x["classification"] in {"GUARD_STRUCTURE","MISSING_HELPER"}]; families={x["family"] for x in helper}
 if len(helper)>=3 and len(families)>=2: decision="GO_PROOF_GRAPH_COMPLETION"
 elif counts["K_INDUCTIVE"]>=3: decision="GO_STRONGER_INDUCTION_CONSUMER"
 elif counts["FALSE_CANDIDATE"]>=4 or counts["UNRESOLVED"]>=5: decision="GO_CERTIFIED_PROOF_SET_TRANSPORT"
 else: decision="STOP_ALGORITHM_EXPANSION"
 summary={"schema":"pono-inductiveness-gap-summary-v1","gate":"Gate 5A","case_count":len(cases),"classification_counts":dict(sorted(counts.items())),"cases":cases,"decision":decision,"proof_graph_authorized":decision=="GO_PROOF_GRAPH_COMPLETION","stronger_induction_authorized":decision=="GO_STRONGER_INDUCTION_CONSUMER","transport_authorized":decision=="GO_CERTIFIED_PROOF_SET_TRANSPORT","llm_authorized":False,"false_safe":0,"gate4_manifest_file_sha256":fsha(gate4/"c2_queries/manifest.json")}; summary["summary_sha256"]=gap.csha(summary); (out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
 files={str(p.relative_to(out)):fsha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='integrity.json'}; integrity={"schema":"pono-inductiveness-gap-integrity-v1","files":files}; integrity["integrity_sha256"]=gap.csha(integrity); (out/"integrity.json").write_text(json.dumps(integrity,indent=2,sort_keys=True)+"\n"); return summary,integrity
def main():
 p=argparse.ArgumentParser(); p.add_argument("gate4",type=Path); p.add_argument("capture",type=Path); p.add_argument("root",type=Path); p.add_argument("out",type=Path); p.add_argument("--timeout-ms",type=int,default=20000); p.add_argument("--max-repair-sec",type=int,default=30); a=p.parse_args()
 try: s,i=run(a.gate4,a.capture,a.root,a.out,a.timeout_ms,a.max_repair_sec); print(json.dumps({"decision":s["decision"],"counts":s["classification_counts"],"summary_sha256":s["summary_sha256"],"integrity_sha256":i["integrity_sha256"]},indent=2,sort_keys=True))
 except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError,z3.Z3Exception) as e: print(e); return 1
 return 0
if __name__=="__main__": raise SystemExit(main())
