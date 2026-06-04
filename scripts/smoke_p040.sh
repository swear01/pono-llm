#!/usr/bin/env bash
# p040 IC3 Frame v1 smoke — isolated session (no shared /tmp/p040_*).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BTOR="${BTOR:-$HOME/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/qspiflash_dualflexpress_divfive-p040.btor2}"
RUN_DIR="$(mktemp -d /tmp/pono_smoke_XXXXXX)"

REQ="$RUN_DIR/requests.jsonl"
RESP="$RUN_DIR/responses.jsonl"
LOG="$RUN_DIR/llm_log.jsonl"
SIDECAR_LOG="$RUN_DIR/sidecar.log"
PONO_OUT="$RUN_DIR/pono_stdout.log"
PONO_ERR="$RUN_DIR/pono_stderr.log"
MANIFEST="$RUN_DIR/manifest.json"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "ERROR: DEEPSEEK_API_KEY not set" >&2
  exit 1
fi
if [[ ! -x "$ROOT/build/pono" ]]; then
  echo "ERROR: build/pono missing — run cmake build in $ROOT/build" >&2
  exit 1
fi
if [[ ! -f "$BTOR" ]]; then
  echo "ERROR: benchmark not found: $BTOR" >&2
  exit 1
fi

SNAPSHOT_MAX="${SNAPSHOT_MAX:-50}"
PONO_TIMEOUT="${PONO_TIMEOUT:-600}"
PARALLEL_SAMPLES="${PARALLEL_SAMPLES:-1}"

echo "RUN_DIR=$RUN_DIR"
echo "snapshot_max_clauses=$SNAPSHOT_MAX parallel_samples=$PARALLEL_SAMPLES"

python3 -u "$ROOT/llm_worker/sidecar.py" \
  --req-path "$REQ" \
  --resp-path "$RESP" \
  --log-path "$LOG" \
  --prompt-dir "$ROOT/llm_worker/prompts/" \
  --poll-interval 0.5 \
  --max-inflight-requests 4 \
  --snapshot-max-clauses "$SNAPSHOT_MAX" \
  >"$SIDECAR_LOG" 2>&1 &
SIDECAR_PID=$!
sleep 2

timeout "$PONO_TIMEOUT" "$ROOT/build/pono" -e ic3ia -k 5 \
  --llm-gen-mode async-cti \
  --llm-parallel-samples "$PARALLEL_SAMPLES" \
  --llm-reasoning-effort none \
  --llm-max-attempts 1 \
  --llm-accepted-budget 5 \
  --llm-req-path "$REQ" \
  --llm-resp-path "$RESP" \
  --llm-log "$LOG" \
  "$BTOR" >"$PONO_OUT" 2>"$PONO_ERR" || true

kill "$SIDECAR_PID" 2>/dev/null || true
wait "$SIDECAR_PID" 2>/dev/null || true

python3 - <<PY
import json, os
from pathlib import Path
run_dir = Path("$RUN_DIR")
manifest = {
    "run_dir": str(run_dir),
    "sidecar_pid": $SIDECAR_PID,
    "req_path": "$REQ",
    "resp_path": "$RESP",
    "btor": "$BTOR",
    "snapshot_max_clauses": int("$SNAPSHOT_MAX"),
}
(run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("manifest:", run_dir / "manifest.json")
PY

echo "--- pono result ---"
cat "$PONO_OUT" || true
echo "--- LLM_STATS ---"
grep LLM_STATS "$PONO_ERR" || true
echo "--- sidecar tail ---"
tail -8 "$SIDECAR_LOG" || true
echo "--- llm_log sample ---"
head -1 "$LOG" 2>/dev/null | python3 -m json.tool 2>/dev/null || true
echo "Artifacts kept in $RUN_DIR"
