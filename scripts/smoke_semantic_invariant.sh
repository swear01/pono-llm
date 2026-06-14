#!/usr/bin/env bash
# Smoke test for the "semantic" LLM mode (Stage 0 + Stage 2).
#
# Usage:
#   ./scripts/smoke_semantic_invariant.sh [benchmark.btor2] [property_index]
#
# Defaults to p040 (vgasim_imgfifo) property 0.
# Requires: pono binary built, sidecar running in a separate terminal.
#
# To run the sidecar:
#   cd llm_worker && python3 sidecar.py \
#       --req-path /tmp/pono_inv_req.jsonl \
#       --resp-path /tmp/pono_inv_resp.jsonl
#
# The script runs pono with --llm-gen-mode semantic for up to 200 steps,
# then checks that a Stage 0 request appeared in the JSONL file.

set -euo pipefail

BTOR2="${1:-/home/swear01/hwmcc_benchmarks/2024/btor2/2019/wolf/2019C/vgasim_imgfifo-p040.btor2}"
PROP="${2:-0}"

REQ_PATH="/tmp/pono_inv_req.jsonl"
RESP_PATH="/tmp/pono_inv_resp.jsonl"
PONO="${PONO:-$(dirname "$0")/../build/bin/pono}"

if [[ ! -f "$PONO" ]]; then
    PONO="$(dirname "$0")/../build/pono"
fi

if [[ ! -f "$BTOR2" ]]; then
    echo "ERROR: BTOR2 file not found: $BTOR2"
    exit 1
fi

echo "=== Semantic Invariant Smoke Test ==="
echo "BTOR2:     $BTOR2"
echo "Property:  $PROP"
echo "REQ:       $REQ_PATH"
echo "RESP:      $RESP_PATH"
echo ""

# Clean old files
rm -f "$REQ_PATH" "$RESP_PATH"

echo "[1/3] Running pono with --llm-gen-mode semantic (max 200 steps, 90s timeout)..."
timeout 90 "$PONO" \
    --engine ic3ia \
    --llm-gen-mode semantic \
    --llm-req-path "$REQ_PATH" \
    --llm-resp-path "$RESP_PATH" \
    -k 200 \
    "$BTOR2" "$PROP" || true

echo ""
echo "[2/3] Checking Stage 0 request appeared in JSONL..."
if [[ ! -f "$REQ_PATH" ]]; then
    echo "FAIL: $REQ_PATH not created"
    exit 1
fi

STAGE0_COUNT=$(grep -c '"ic3_stage0_request"' "$REQ_PATH" 2>/dev/null || echo 0)
if [[ "$STAGE0_COUNT" -eq 0 ]]; then
    echo "FAIL: no ic3_stage0_request found in $REQ_PATH"
    echo "Contents:"
    cat "$REQ_PATH" 2>/dev/null | head -5
    exit 1
fi

echo "OK: found $STAGE0_COUNT Stage 0 request(s)"
echo ""

echo "[3/3] Checking request structure..."
FIRST_REQ=$(grep '"ic3_stage0_request"' "$REQ_PATH" | head -1)
for key in '"benchmark"' '"property_desc"' '"btor2_path"' '"request_id"' '"symbol_registry"'; do
    if echo "$FIRST_REQ" | grep -q "$key"; then
        echo "  OK: $key present"
    else
        echo "  WARN: $key missing"
    fi
done

STAGE2_COUNT=$(grep -c '"ic3_stage2_request"' "$REQ_PATH" 2>/dev/null || echo 0)
echo ""
echo "Stage 2 requests: $STAGE2_COUNT"

echo ""
echo "=== Smoke test PASSED ==="
