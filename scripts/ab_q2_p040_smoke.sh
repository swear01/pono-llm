#!/usr/bin/env bash
# A/B smoke: pre-q2 baseline (tag) vs Q2.1+Q2.3 (HEAD) on vgasim_imgfifo-p040.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2}"
OUT_BASE="${OUT_BASE:-/tmp/q2_ab_p040_$(date +%Y%m%d_%H%M%S)}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"
STRICT="${STRICT:-0}"

mkdir -p "$OUT_BASE"

parse_llm_stats() {
  local err_file="$1"
  python3 - <<PY "$err_file"
import re, sys
text = open(sys.argv[1]).read() if sys.argv[1] else ""
stats = {}
for line in text.splitlines():
    if not line.startswith("LLM_STATS"):
        continue
    for part in line.split():
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                stats[k] = int(v)
            except ValueError:
                stats[k] = v
print(stats.get("accepted", 0), stats.get("requests", 0), stats.get("candidates", 0),
      stats.get("rejected_initial", 0), stats.get("induction_fail", 0))
PY
}

ensure_smoke_max_attempts() {
  # Older tags may lack MAX_ATTEMPTS in smoke_p040.sh; patch for fair A/B.
  local smoke="$ROOT/scripts/smoke_p040.sh"
  if ! grep -q 'MAX_ATTEMPTS=' "$smoke"; then
    sed -i 's/PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"/PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"\nMAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"/' "$smoke"
    sed -i 's/--llm-max-attempts 1/--llm-max-attempts "$MAX_ATTEMPTS"/' "$smoke"
  fi
}

run_variant() {
  local label="$1"
  local git_ref="$2"
  local run_dir="$OUT_BASE/$label"
  mkdir -p "$run_dir"

  echo "=== [$label] checkout $git_ref ==="
  git -C "$ROOT" checkout "$git_ref" --quiet
  ensure_smoke_max_attempts

  echo "=== [$label] build ==="
  make -C "$ROOT/build" -j"$(nproc)" pono 2>&1 | tail -3

  echo "=== [$label] smoke (max_attempts=$MAX_ATTEMPTS) ==="
  BTOR="$BTOR" MAX_ATTEMPTS="$MAX_ATTEMPTS" PARALLEL_SAMPLES="$PARALLEL_SAMPLES" \
    STRICT="$STRICT" \
    bash "$ROOT/scripts/smoke_p040.sh" 2>&1 | tee "$run_dir/smoke.log" || true

  local manifest
  manifest="$(grep -o 'RUN_DIR=/tmp/pono_smoke_[^ ]*' "$run_dir/smoke.log" | head -1 | cut -d= -f2-)"
  if [[ -n "$manifest" && -d "$manifest" ]]; then
    cp -a "$manifest" "$run_dir/artifacts"
    echo "$manifest" >"$run_dir/artifact_path.txt"
  fi

  local stats_line=""
  if [[ -f "$run_dir/artifacts/pono_stderr.log" ]]; then
    stats_line="$(parse_llm_stats "$run_dir/artifacts/pono_stderr.log")"
  fi
  echo "$label $git_ref $stats_line" >>"$OUT_BASE/summary.tsv"
  echo "=== [$label] stats: $stats_line (accepted requests candidates rejected_initial induction_fail) ==="
}

main() {
  local head_ref
  head_ref="$(git -C "$ROOT" rev-parse HEAD)"
  trap 'git -C "$ROOT" checkout "$head_ref" --quiet 2>/dev/null || true' EXIT

  echo "OUT_BASE=$OUT_BASE"
  echo "BTOR=$BTOR"
  printf "label\tgit_ref\taccepted\trequests\tcandidates\trejected_initial\tinduction_fail\n" >"$OUT_BASE/summary.tsv"

  run_variant "A0_baseline" "pre-q2-clause-quality"
  run_variant "A1_q2" "$head_ref"

  python3 - <<PY
from pathlib import Path
out = Path("$OUT_BASE")
rows = []
for line in out.joinpath("summary.tsv").read_text().splitlines()[1:]:
    parts = line.split()
    if len(parts) < 7:
        continue
    label, ref, acc, req, cand, ri, ind = parts[0], parts[1], *map(int, parts[2:7])
    api = req or cand or 1
    rows.append((label, acc, api, 100 * acc / api, ri, ind))

print("\\n=== Q2 p040 A/B summary ===")
print(f"{'label':<14} {'accept':>6} {'api':>5} {'accept/api%':>12} {'rej_init':>9} {'ind_fail':>9}")
for label, acc, api, pct, ri, ind in rows:
    print(f"{label:<14} {acc:>6} {api:>5} {pct:>11.1f}% {ri:>9} {ind:>9}")
if len(rows) == 2:
    d = rows[1][3] - rows[0][3]
    print(f"\\nDelta accept/api: {d:+.1f} pp")
print(f"\\nArtifacts: {out}")
PY
}

main "$@"
