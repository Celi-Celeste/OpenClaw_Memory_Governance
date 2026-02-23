#!/bin/bash
# Wrapper for jobs using Qwen3 Thinking via Ollama (parallel execution)
# Runs without affecting LM Studio's standard model

set -e

WORKSPACE="/Users/celeste/.openclaw/workspace"
SCRIPT_DIR="$WORKSPACE/skills/openclaw-memory-governance/scripts"
LOG_DIR="$WORKSPACE/memory/logs"

mkdir -p "$LOG_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting $JOB_NAME with Ollama (thinking model)"

# Verify Ollama is running and model is available
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "ERROR: Ollama not responding"
    exit 1
fi

# Check if thinking model is loaded
if ! curl -s http://localhost:11434/api/tags | grep -q "qwen3.*thinking"; then
    echo "Loading qwen3:thinking model..."
    ollama run qwen3:4b-thinking "Hello" > /dev/null 2>&1 || true
fi

# Run the Python script with Ollama model specified
python3 "$SCRIPT_DIR/$PYTHON_SCRIPT" \
    --workspace "$WORKSPACE" \
    --model "ollama:qwen3:4b-thinking" \
    --log-model "qwen3:4b-thinking-ollama" \
    >> "$LOG_DIR/$JOB_NAME.out.log" 2>> "$LOG_DIR/$JOB_NAME.err.log"

EXIT_CODE=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Completed with exit code $EXIT_CODE"
exit $EXIT_CODE
