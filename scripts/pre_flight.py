#!/usr/bin/env python3
"""Pre-flight checks and failure handling utilities.

Implements lessons from failure analysis:
- Detect issues before they cause problems
- Automatic fallbacks
- Systematized failure knowledge
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

FAILURE_LOG = Path.home() / ".openclaw/workspace/memory/failures/tool_failures.json"

def log_failure(tool: str, error: str, context: str) -> None:
    """Log tool failure for pattern analysis."""
    FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "error": error,
        "context": context,
    }
    
    if FAILURE_LOG.exists():
        data = json.loads(FAILURE_LOG.read_text())
    else:
        data = {"failures": []}
    
    data["failures"].append(entry)
    FAILURE_LOG.write_text(json.dumps(data, indent=2))

def check_gateway_status() -> Tuple[bool, str]:
    """Check if OpenClaw gateway is running."""
    try:
        result = subprocess.run(
            ["openclaw", "gateway", "status"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "running" in result.stdout.lower():
            return True, "Gateway running"
        return False, "Gateway not running"
    except Exception as e:
        return False, f"Gateway check failed: {e}"

def can_spawn_subagents() -> Tuple[bool, str]:
    """Check if subagent spawning is available."""
    gateway_ok, gateway_msg = check_gateway_status()
    if not gateway_ok:
        return False, f"Subagents unavailable: {gateway_msg}"
    
    # TODO: Add actual spawn test if needed
    return True, "Subagents likely available (gateway running)"

def execute_with_fallback(
    primary_func: Callable,
    fallback_func: Callable,
    failure_context: str
) -> any:
    """Execute primary function with automatic fallback on failure.
    
    Args:
        primary_func: Main function to try
        fallback_func: Fallback if primary fails
        failure_context: Description for failure log
        
    Returns:
        Result from primary or fallback
    """
    try:
        return primary_func()
    except Exception as e:
        # Log the failure
        log_failure(
            tool=primary_func.__name__,
            error=str(e),
            context=failure_context
        )
        
        # Execute fallback
        print(f"[FALLBACK] {primary_func.__name__} failed, using fallback")
        return fallback_func()

def pre_flight_check(tools: list[str]) -> Dict[str, Tuple[bool, str]]:
    """Run pre-flight checks for specified tools.
    
    Args:
        tools: List of tools to check ('subagents', 'gateway', 'ollama', etc.)
        
    Returns:
        Dict of tool -> (available, message)
    """
    results = {}
    
    for tool in tools:
        if tool == "subagents":
            results[tool] = can_spawn_subagents()
        elif tool == "gateway":
            results[tool] = check_gateway_status()
        elif tool == "ollama":
            # Quick check if Ollama responds
            try:
                import urllib.request
                req = urllib.request.Request("http://localhost:11434/api/tags")
                with urllib.request.urlopen(req, timeout=2) as r:
                    results[tool] = (True, "Ollama responding")
            except Exception as e:
                results[tool] = (False, f"Ollama not responding: {e}")
        elif tool == "lmstudio":
            try:
                import urllib.request
                req = urllib.request.Request("http://localhost:1234/v1/models")
                with urllib.request.urlopen(req, timeout=2) as r:
                    results[tool] = (True, "LM Studio responding")
            except Exception as e:
                results[tool] = (False, f"LM Studio not responding: {e}")
        else:
            results[tool] = (False, f"Unknown tool: {tool}")
    
    return results

def main():
    """CLI for pre-flight checks."""
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("tools", nargs="+", help="Tools to check")
    args = parser.parse_args()
    
    results = pre_flight_check(args.tools)
    
    print("Pre-flight Check Results:")
    print("-" * 50)
    for tool, (available, message) in results.items():
        status = "✅" if available else "❌"
        print(f"{status} {tool}: {message}")
    
    # Exit 1 if any unavailable
    if not all(r[0] for r in results.values()):
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
