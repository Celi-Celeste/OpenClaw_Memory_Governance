#!/bin/bash
# Wrapper for daily_consolidate.py
# Runs daily at 3:25 AM
# Note: No LLM needed, runs directly

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"
AGENT_ID="main"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting daily_consolidate"

python3 "$SCRIPT_DIR/daily_consolidate.py" \
    --workspace "$WORKSPACE" \
    --agent-id "$AGENT_ID" \
    --transcript-root archive/transcripts \
    --transcript-mode sanitized \
    >> "$LOG_DIR/daily_consolidate.out.log" 2>> "$LOG_DIR/daily_consolidate.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Completed with exit code $EXIT_CODE"
exit $EXIT_CODE
