#!/usr/bin/env bash
# Multi-round A/B on p040: B0 legacy harness vs B8 Q4 task card (current HEAD).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2}"
ROUNDS="${ROUNDS:-5}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
MAX_BLOCK_CLAUSES="${MAX_BLOCK_CLAUSES:-3}"
STRICT="${STRICT:-0}"
OUT_BASE="${OUT_BASE:-/tmp/q4_ab_multiround_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUT_BASE"
head_ref="$(git -C "$ROOT" rev-parse HEAD)"

parse_stats() {
  python3 - <<'PY' "$1"
import re, sys, json
text = open(sys.argv[1]).read() if sys.argv[1] else ""
stats = {}
for line in text.splitlines():
    if line.startswith("LLM_STATS"):
        for part in line.split():
            if "=" in part:
                k, v = part.split("=", 1)
                try: stats[k] = int(v)
                except ValueError: stats[k] = v
print(json.dumps(stats))
PY
}

inspect_harness() {
  local artifacts="$1"
  local out_json="$2"
  local req="$artifacts/requests.jsonl"
  if [[ -f "$req" ]]; then
    python3 "$ROOT/scripts/inspect_harness_packet.py" "$req" --json >"$out_json" 2>/dev/null || true
  fi
}

run_smoke() {
  local label="$1"
  local harness_legacy="$2"
  local round="$3"
  local run_dir="$OUT_BASE/${label}_r${round}"
  mkdir -p "$run_dir"

  git -C "$ROOT" checkout -f "$head_ref" --quiet
  make -C "$ROOT/build" -j"$(nproc)" pono >/dev/null 2>&1

  local sidecar_extra=()
  if [[ "$harness_legacy" == "1" ]]; then
    sidecar_extra+=(HARNESS_LEGACY=1)
  fi

  env "${sidecar_extra[@]}" BTOR="$BTOR" MAX_ATTEMPTS="$MAX_ATTEMPTS" \
    MAX_BLOCK_CLAUSES="$MAX_BLOCK_CLAUSES" STRICT="$STRICT" \
    bash "$ROOT/scripts/smoke_p040.sh" 2>&1 | tee "$run_dir/smoke.log" || true

  local artifact
  artifact="$(grep -o 'RUN_DIR=/tmp/pono_smoke_[^ ]*' "$run_dir/smoke.log" | head -1 | cut -d= -f2-)"
  if [[ -n "$artifact" && -d "$artifact" ]]; then
    cp -a "$artifact" "$run_dir/artifacts"
    inspect_harness "$run_dir/artifacts" "$run_dir/harness_inspect.json"
  fi
  if [[ -f "$run_dir/artifacts/pono_stderr.log" ]]; then
    parse_stats "$run_dir/artifacts/pono_stderr.log" >"$run_dir/stats.json"
  fi
}

echo "OUT_BASE=$OUT_BASE ROUNDS=$ROUNDS HEAD=$head_ref max_attempts=$MAX_ATTEMPTS"

for r in $(seq 1 "$ROUNDS"); do
  echo "=== Round $r/$ROUNDS ==="
  run_smoke "B0_legacy" "1" "$r"
  run_smoke "B8_q4" "0" "$r"
done

python3 - <<PY
import json
from pathlib import Path

out = Path("$OUT_BASE")
rows = []
for stats_path in sorted(out.glob("*/stats.json")):
    label_round = stats_path.parent.name
    parts = label_round.rsplit("_r", 1)
    label = parts[0] if len(parts) == 2 else label_round
    rnd = int(parts[1]) if len(parts) == 2 else 0
    s = json.loads(stats_path.read_text())
    req = s.get("requests", 0) or 1
    acc = s.get("accepted", 0)
    harness = {}
    hi = stats_path.parent / "harness_inspect.json"
    if hi.is_file():
        h = json.loads(hi.read_text())
        harness = h.get("aggregate") or {}
    rows.append({
        "label": label, "round": rnd,
        "accepted": acc, "requests": req,
        "pct": 100 * acc / req,
        "rejected_initial": s.get("rejected_initial", 0),
        "induction_fail": s.get("induction_fail", 0),
        "user_prompt_bytes_mean": harness.get("user_prompt_bytes_mean"),
        "init_table_coverage_pct_mean": harness.get("init_table_coverage_pct_mean"),
    })

from collections import defaultdict
agg = defaultdict(lambda: {"accepted": 0, "requests": 0, "rejected_initial": 0, "induction_fail": 0, "rounds": 0})
for r in rows:
    a = agg[r["label"]]
    a["accepted"] += r["accepted"]
    a["requests"] += r["requests"]
    a["rejected_initial"] += r["rejected_initial"]
    a["induction_fail"] += r["induction_fail"]
    a["rounds"] += 1

print("\n=== Per-round ===")
print(f"{'label':<12} {'rnd':>3} {'acc':>4} {'api':>4} {'%':>7} {'rej_init':>9} {'ind':>5} {'bytes':>6} {'init%':>6}")
for r in rows:
    print(
        f"{r['label']:<12} {r['round']:>3} {r['accepted']:>4} {r['requests']:>4} {r['pct']:>6.1f}% "
        f"{r['rejected_initial']:>9} {r['induction_fail']:>5} "
        f"{r.get('user_prompt_bytes_mean') or '-':>6} {r.get('init_table_coverage_pct_mean') or '-':>6}"
    )

print("\n=== Aggregate ($ROUNDS rounds) ===")
print(f"{'label':<12} {'acc':>5} {'api':>5} {'%':>8} {'rej_init':>9} {'ind':>5}")
for label in sorted(agg):
    a = agg[label]
    pct = 100 * a["accepted"] / a["requests"] if a["requests"] else 0
    print(f"{label:<12} {a['accepted']:>5} {a['requests']:>5} {pct:>7.1f}% {a['rejected_initial']:>9} {a['induction_fail']:>5}")

labels = sorted(agg)
if len(labels) == 2:
    p0 = 100 * agg[labels[0]]["accepted"] / agg[labels[0]]["requests"]
    p1 = 100 * agg[labels[1]]["accepted"] / agg[labels[1]]["requests"]
    print(f"\nDelta accept/api ({labels[1]} - {labels[0]}): {p1 - p0:+.1f} pp")
print(f"\nArtifacts: {out}")
PY

echo ""
echo "Harness inspect JSON per run: $OUT_BASE/*/harness_inspect.json"
