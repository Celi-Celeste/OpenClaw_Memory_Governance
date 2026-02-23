#!/usr/bin/env python3
"""Model guard for LM Studio - handles locking, verification, and switching."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Tuple

# Lock file to prevent concurrent model operations
LOCK_DIR = Path(os.path.expanduser("~/.openclaw/model-locks"))
LOCK_FILE = LOCK_DIR / "lmstudio.lock"
DEFAULT_MODEL = "qwen/qwen3-4b-2507"
LMSTUDIO_API = "http://localhost:1234/v1/models"
LMS_BIN = os.path.expanduser("~/.lmstudio/bin/lms")


class ModelGuardError(Exception):
    """Raised when model guard cannot ensure correct state."""
    pass


def ensure_lock_dir() -> None:
    """Ensure lock directory exists."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(LOCK_DIR, 0o700)


@contextmanager
def model_lock(timeout_seconds: int = 300) -> Generator[bool, None, None]:
    """Acquire exclusive lock for model operations.
    
    Args:
        timeout_seconds: Maximum time to wait for lock (default 5 minutes)
        
    Yields:
        True if lock acquired, False if timeout
    """
    ensure_lock_dir()
    
    start_time = time.time()
    lock_acquired = False
    
    while time.time() - start_time < timeout_seconds:
        try:
            # Try to create lock file exclusively
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            # Write PID and timestamp
            timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
            os.write(fd, f"{os.getpid()}\n{timestamp}\n".encode())
            os.close(fd)
            os.chmod(LOCK_FILE, 0o600)
            lock_acquired = True
            break
        except FileExistsError:
            # Lock held, check if stale
            try:
                if LOCK_FILE.exists():
                    content = LOCK_FILE.read_text().strip().split('\n')
                    if len(content) >= 1:
                        pid = int(content[0])
                        # Check if process still exists
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            # Process dead, remove stale lock
                            LOCK_FILE.unlink()
                            continue
            except (ValueError, OSError):
                pass
            # Wait and retry
            time.sleep(1)
    
    if not lock_acquired:
        yield False
        return
    
    try:
        yield True
    finally:
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except OSError:
            pass


def get_loaded_model() -> Tuple[str | None, str]:
    """Get currently loaded model from LM Studio API.
    
    Returns:
        Tuple of (model_id, status_message)
    """
    try:
        import urllib.request
        req = urllib.request.Request(LMSTUDIO_API)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            models = data.get('data', [])
            if models:
                return models[0].get('id'), f"Found loaded model: {models[0].get('id')}"
            return None, "No model currently loaded"
    except Exception as e:
        return None, f"Error checking model: {e}"


def switch_model(target_model: str, max_wait_seconds: int = 120) -> Tuple[bool, str]:
    """Switch to target model.
    
    Args:
        target_model: Model identifier to load
        max_wait_seconds: Maximum time to wait for load
        
    Returns:
        Tuple of (success, message)
    """
    # Check current model first
    current, msg = get_loaded_model()
    if current == target_model:
        return True, f"Model {target_model} already loaded"
    
    # Unload current if needed
    if current:
        try:
            subprocess.run(
                [LMS_BIN, "unload"],
                check=True,
                capture_output=True,
                timeout=30
            )
        except subprocess.CalledProcessError as e:
            return False, f"Failed to unload current model: {e}"
    
    # Load target model
    try:
        result = subprocess.run(
            [LMS_BIN, "load", target_model],
            check=True,
            capture_output=True,
            timeout=max_wait_seconds
        )
    except subprocess.CalledProcessError as e:
        return False, f"Failed to load model {target_model}: {e}"
    except subprocess.TimeoutExpired:
        return False, f"Timeout loading model {target_model}"
    
    # Verify it loaded correctly
    time.sleep(1)  # Brief pause for API to stabilize
    verify, verify_msg = get_loaded_model()
    if verify != target_model:
        return False, f"Model verification failed: expected {target_model}, got {verify}"
    
    return True, f"Successfully switched to {target_model}"


def restore_default_model() -> Tuple[bool, str]:
    """Restore default model after job completion."""
    return switch_model(DEFAULT_MODEL)


@contextmanager
def guard_model(required_model: str | None = None) -> Generator[Tuple[bool, str], None, None]:
    """Context manager for model-guarded operations.
    
    Args:
        required_model: Model to ensure is loaded (None = use default)
        
    Yields:
        Tuple of (success, message)
    """
    target = required_model or DEFAULT_MODEL
    acquired = False
    switched = False
    original_model = None
    
    with model_lock(timeout_seconds=300) as lock_acquired:
        if not lock_acquired:
            yield False, "Could not acquire model lock (timeout or contention)"
            return
        
        acquired = True
        
        # Remember original model for restoration
        original_model, _ = get_loaded_model()
        
        # Switch to required model
        success, msg = switch_model(target)
        if not success:
            yield False, f"Model switch failed: {msg}"
            return
        
        switched = True
        
        try:
            yield True, f"Model guard active with {target}"
        finally:
            # Always try to restore default unless it was already the target
            if original_model and original_model != target:
                restore_default_model()


def main():
    parser = argparse.ArgumentParser(description="Model guard for LM Studio cron jobs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to ensure is loaded")
    parser.add_argument("--command", default="", help="Command to run with model guard")
    parser.add_argument("--timeout", type=int, default=300, help="Lock timeout in seconds")
    parser.add_argument("--no-restore", action="store_true", help="Don't restore default model after")
    parser.add_argument("--verify-only", action="store_true", help="Just verify current model, don't switch")
    args = parser.parse_args()

    if args.verify_only:
        model, msg = get_loaded_model()
        print(json.dumps({"model": model, "message": msg}))
        return 0 if model else 1

    if not args.command:
        parser.error("--command is required unless using --verify-only")
    
    with guard_model(args.model) as (success, msg):
        if not success:
            print(f"Model guard failed: {msg}", file=sys.stderr)
            return 1
        
        # Log which model is running the job
        print(f"[{dt.datetime.now(dt.timezone.utc).isoformat()}] Running with model: {args.model}")
        
        # Run the actual command
        try:
            result = subprocess.run(
                args.command,
                shell=True,
                check=False
            )
            return result.returncode
        except Exception as e:
            print(f"Command execution failed: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
