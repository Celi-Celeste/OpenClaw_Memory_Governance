#!/bin/bash
# Wrapper for health_check.py
# Runs every 6 hours

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting health check"

python3 "$SCRIPT_DIR/health_check.py" \
    --alert \
    >> "$LOG_DIR/health_check.out.log" 2>> "$LOG_DIR/health_check.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Health check completed with exit code $EXIT_CODE"
exit $EXIT_CODE
