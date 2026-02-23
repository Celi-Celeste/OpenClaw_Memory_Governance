#!/bin/bash
# Wrapper for importance_score.py - runs daily at 3:08 AM
# Note: Uses algorithmic scoring, no LLM needed

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting importance_score"

python3 "$SCRIPT_DIR/importance_score.py" \
    --workspace "$WORKSPACE" \
    --window-days 30 \
    --max-updates 400 \
    >> "$LOG_DIR/importance_score.out.log" 2>> "$LOG_DIR/importance_score.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Completed with exit code $EXIT_CODE"
exit $EXIT_CODE
