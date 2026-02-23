#!/bin/bash
# Wrapper for hourly_semantic_extract.py
# Runs hourly at :20
# Note: No LLM needed, runs directly

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting hourly_semantic_extract"

python3 "$SCRIPT_DIR/hourly_semantic_extract.py" \
    --workspace "$WORKSPACE" \
    >> "$LOG_DIR/hourly_semantic_extract.out.log" 2>> "$LOG_DIR/hourly_semantic_extract.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Completed with exit code $EXIT_CODE"
exit $EXIT_CODE
