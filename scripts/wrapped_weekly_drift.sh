#!/bin/bash
# Wrapper for weekly_drift_review.py - runs Sunday at 2:12 AM
# Note: Uses algorithmic drift detection, no LLM needed

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting weekly_drift_review"

python3 "$SCRIPT_DIR/weekly_drift_review.py" \
    --workspace "$WORKSPACE" \
    --max-groups 200 \
    >> "$LOG_DIR/weekly_drift_review.out.log" 2>> "$LOG_DIR/weekly_drift_review.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Completed with exit code $EXIT_CODE"
exit $EXIT_CODE
