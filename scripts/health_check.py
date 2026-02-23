#!/usr/bin/env python3
"""Health monitoring for OpenClaw Memory Governance infrastructure."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any

# Thresholds
DISK_WARNING_GB = 10
DISK_CRITICAL_GB = 5
LMSTUDIO_DIR = Path.home() / ".lmstudio"
QMD_CACHE = Path.home() / ".cache" / "qmd"
WORKSPACE = Path.home() / ".openclaw" / "workspace"
LMS_BIN = Path.home() / ".lmstudio" / "bin" / "lms"


def get_disk_usage(path: Path) -> Dict[str, Any]:
    """Get disk usage statistics."""
    try:
        stat = shutil.disk_usage(path)
        free_gb = stat.free / (1024**3)
        total_gb = stat.total / (1024**3)
        used_pct = (stat.used / stat.total) * 100
        return {
            "path": str(path),
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_percent": round(used_pct, 1),
            "status": "ok" if free_gb > DISK_WARNING_GB else ("warn" if free_gb > DISK_CRITICAL_GB else "critical")
        }
    except Exception as e:
        return {"path": str(path), "error": str(e), "status": "error"}


def check_model_integrity() -> Dict[str, Any]:
    """Check if downloaded models are intact."""
    results = {"models": [], "status": "ok"}
    
    models_dir = LMSTUDIO_DIR / "models"
    if not models_dir.exists():
        results["status"] = "warn"
        results["message"] = "Models directory not found"
        return results
    
    # Check for expected models
    expected = [
        "lmstudio-community/Qwen3-4B-Instruct-2507-MLX-4bit",
        "lmstudio-community/Qwen3-4B-Thinking-2507-MLX-4bit",
        "lmstudio-community/Qwen3-VL-4B-Instruct-MLX-8bit"
    ]
    
    for model_path in expected:
        full_path = models_dir / model_path
        if full_path.exists():
            size_mb = sum(f.stat().st_size for f in full_path.rglob('*') if f.is_file()) / (1024**2)
            results["models"].append({
                "name": model_path,
                "present": True,
                "size_mb": round(size_mb, 1)
            })
        else:
            results["models"].append({
                "name": model_path,
                "present": False
            })
            results["status"] = "warn"
    
    return results


def check_qmd_health() -> Dict[str, Any]:
    """Check qmd index health."""
    result = {"status": "ok"}
    
    try:
        proc = subprocess.run(
            ["qmd", "status"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if proc.returncode != 0:
            result["status"] = "error"
            result["message"] = f"qmd status failed: {proc.stderr}"
            return result
        
        # Parse basic info from status
        result["raw_output"] = proc.stdout
        
        # Check index size
        index_file = QMD_CACHE / "index.sqlite"
        if index_file.exists():
            size_mb = index_file.stat().st_size / (1024**2)
            result["index_size_mb"] = round(size_mb, 2)
            
    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["message"] = "qmd status timeout"
    except FileNotFoundError:
        result["status"] = "error"
        result["message"] = "qmd binary not found"
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    
    return result


def check_lmstudio_server() -> Dict[str, Any]:
    """Check if LM Studio server is responsive."""
    result = {"status": "ok"}
    
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:1234/v1/models")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            models = data.get('data', [])
            result["loaded_model"] = models[0].get('id') if models else None
            result["model_count"] = len(models)
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
    
    return result


def check_memory_governance_locks() -> Dict[str, Any]:
    """Check for stale lock files."""
    result = {"status": "ok", "locks": []}
    
    lock_dirs = [
        WORKSPACE / "memory" / "locks",
        Path.home() / ".openclaw" / "model-locks"
    ]
    
    now = dt.datetime.now(dt.timezone.utc)
    stale_threshold_hours = 2
    
    for lock_dir in lock_dirs:
        if not lock_dir.exists():
            continue
        
        for lock_file in lock_dir.glob("*.lock"):
            try:
                stat = lock_file.stat()
                age_hours = (now.timestamp() - stat.st_mtime) / 3600
                
                lock_info = {
                    "file": str(lock_file),
                    "age_hours": round(age_hours, 2),
                    "stale": age_hours > stale_threshold_hours
                }
                result["locks"].append(lock_info)
                
                if lock_info["stale"]:
                    result["status"] = "warn"
                    
            except Exception as e:
                result["locks"].append({"file": str(lock_file), "error": str(e)})
    
    return result


def send_alert(check_results: Dict[str, Any], alert_channel: str | None = None) -> bool:
    """Send alert if critical issues found.
    
    For now, writes to a log file. Can be extended to send to Telegram, etc.
    """
    alerts = []
    
    # Check disk
    disk = check_results.get("disk", {})
    if disk.get("status") == "critical":
        alerts.append(f"CRITICAL: Disk space low ({disk.get('free_gb')} GB free)")
    elif disk.get("status") == "warn":
        alerts.append(f"WARNING: Disk space getting low ({disk.get('free_gb')} GB free)")
    
    # Check LM Studio
    lmstudio = check_results.get("lmstudio", {})
    if lmstudio.get("status") != "ok":
        alerts.append(f"WARNING: LM Studio server issue: {lmstudio.get('message')}")
    
    # Check qmd
    qmd = check_results.get("qmd", {})
    if qmd.get("status") != "ok":
        alerts.append(f"WARNING: qmd issue: {qmd.get('message')}")
    
    # Check locks
    locks = check_results.get("locks", {})
    stale_locks = [l for l in locks.get("locks", []) if l.get("stale")]
    if stale_locks:
        alerts.append(f"WARNING: {len(stale_locks)} stale lock files detected")
    
    if not alerts:
        return False
    
    # Write to alert log
    alert_file = WORKSPACE / "memory" / "logs" / "health-alerts.log"
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(alert_file, "a") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"Health Alert - {timestamp}\n")
        f.write(f"{'='*50}\n")
        for alert in alerts:
            f.write(f"- {alert}\n")
        f.write(f"\nFull results:\n{json.dumps(check_results, indent=2)}\n")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Health check for memory governance infrastructure")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--alert", action="store_true", help="Send alerts if issues found")
    parser.add_argument("--workspace", default=str(WORKSPACE))
    args = parser.parse_args()
    
    results = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "checks": {}
    }
    
    # Run all checks
    results["checks"]["disk"] = get_disk_usage(Path.home())
    results["checks"]["models"] = check_model_integrity()
    results["checks"]["qmd"] = check_qmd_health()
    results["checks"]["lmstudio"] = check_lmstudio_server()
    results["checks"]["locks"] = check_memory_governance_locks()
    
    # Determine overall status
    statuses = [c.get("status", "ok") for c in results["checks"].values()]
    if "critical" in statuses:
        results["overall_status"] = "critical"
    elif "error" in statuses:
        results["overall_status"] = "error"
    elif "warn" in statuses:
        results["overall_status"] = "warn"
    else:
        results["overall_status"] = "ok"
    
    # Send alerts if requested
    if args.alert and results["overall_status"] in ("critical", "error", "warn"):
        alerted = send_alert(results["checks"])
        results["alert_sent"] = alerted
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"Health Check: {results['overall_status'].upper()}")
        print(f"Disk: {results['checks']['disk'].get('free_gb', '?')} GB free ({results['checks']['disk'].get('status')})")
        print(f"LM Studio: {results['checks']['lmstudio'].get('loaded_model', 'none')} ({results['checks']['lmstudio'].get('status')})")
        print(f"qmd: {results['checks']['qmd'].get('status')}")
        print(f"Locks: {len(results['checks']['locks'].get('locks', []))} found")
        if results["checks"]["locks"].get("locks"):
            for lock in results["checks"]["locks"]["locks"]:
                status = "STALE" if lock.get("stale") else "ok"
                print(f"  - {lock['file']}: {lock.get('age_hours', '?')}h ({status})")
    
    return 0 if results["overall_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
