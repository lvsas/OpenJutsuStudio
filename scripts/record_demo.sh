#!/usr/bin/env bash
# OpenGenjutsu — Demo recording script (≤2 min)
# Records a real end-to-end case: upload video + character sheet → final result.
#
# Usage: bash scripts/record_demo.sh
# Requires: app running on http://127.0.0.1:8000, ffmpeg, ffprobe

set -euo pipefail

APP_URL="${OPENGENJUTSU_APP_URL:-http://127.0.0.1:8000}"
OUTPUT_DIR="work/demo"
mkdir -p "$OUTPUT_DIR"

echo "=== OpenGenjutsu Demo Recording ==="
echo "App: $APP_URL"
echo ""

# 1. Health check
echo "[1/5] Health check..."
curl -sf "$APP_URL/health" | python3 -m json.tool
echo ""

# 2. Create demo video (or use existing)
DEMO_VIDEO="prototypes/test_input_downloaded.mp4"
if [ ! -f "$DEMO_VIDEO" ]; then
    echo "[2/5] Creating demo video..."
    ffmpeg -y -f lavfi -i "testsrc=duration=5:size=1280x704:rate=24" \
        -c:v libx264 -pix_fmt yuv420p "$OUTPUT_DIR/demo_input.mp4" 2>/dev/null
    DEMO_VIDEO="$OUTPUT_DIR/demo_input.mp4"
else
    echo "[2/5] Using existing demo video: $DEMO_VIDEO"
fi

# 3. Upload video + create job
echo "[3/5] Uploading video and creating job..."
JOB_RESPONSE=$(curl -sf -X POST "$APP_URL/api/jobs" \
    -F "video=@$DEMO_VIDEO" \
    -F "edit_prompt=Replace the two riders with two original adventurers in dark teal and gold armor" \
    -F "ripple_strength=1.2")
JOB_ID=$(echo "$JOB_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job ID: $JOB_ID"
echo ""

# 4. Poll for completion
echo "[4/5] Waiting for render to complete..."
while true; do
    STATUS=$(curl -sf "$APP_URL/api/jobs/$JOB_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
    echo "  Status: $STATUS"
    if [ "$STATUS" = "done" ] || [ "$STATUS" = "error" ]; then
        break
    fi
    sleep 5
done

# 5. Download result
if [ "$STATUS" = "done" ]; then
    echo "[5/5] Downloading result..."
    RESULT_URL=$(curl -sf "$APP_URL/api/jobs/$JOB_ID" | python3 -c "import sys,json; print(json.load(sys.stdin)['result_url'])")
    curl -sf -o "$OUTPUT_DIR/demo_result.mp4" "$APP_URL$RESULT_URL"
    echo "Result saved to: $OUTPUT_DIR/demo_result.mp4"
    echo ""
    echo "=== Demo Complete ==="
    echo "Input:  $DEMO_VIDEO"
    echo "Output: $OUTPUT_DIR/demo_result.mp4"
    echo "Job:    $JOB_ID"
else
    echo "Job failed with status: $STATUS"
    exit 1
fi
