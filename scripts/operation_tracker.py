#!/usr/bin/env python3
"""Active monitoring system for long-running operations.

Prevents "I'll check later" failures by enforcing:
- Regular polling
- Progress logging
- Timeout alerts
- Automatic status updates
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TRACKER_FILE = Path.home() / ".openclaw/workspace/memory/tracking/active-operations.json"

def load_tracker():
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text())
    return {"operations": [], "last_updated": datetime.now(timezone.utc).isoformat()}

def save_tracker(data):
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    TRACKER_FILE.write_text(json.dumps(data, indent=2))

def add_operation(operation_id, description, estimated_minutes):
    tracker = load_tracker()
    
    # Remove any existing with same ID
    tracker["operations"] = [o for o in tracker["operations"] if o["id"] != operation_id]
    
    tracker["operations"].append({
        "id": operation_id,
        "description": description,
        "started": datetime.now(timezone.utc).isoformat(),
        "estimated_duration_minutes": estimated_minutes,
        "status": "in_progress",
        "progress": "0%",
        "last_update": datetime.now(timezone.utc).isoformat(),
        "next_poll": (datetime.now(timezone.utc).timestamp() + 120),  # 2 min default
        "updates": []
    })
    
    save_tracker(tracker)
    print(f"[TRACKER] Added: {operation_id}")

def update_operation(operation_id, progress, message=""):
    tracker = load_tracker()
    
    for op in tracker["operations"]:
        if op["id"] == operation_id:
            op["progress"] = progress
            op["last_update"] = datetime.now(timezone.utc).isoformat()
            op["next_poll"] = datetime.now(timezone.utc).timestamp() + 120
            if message:
                op["updates"].append({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "message": message
                })
            save_tracker(tracker)
            return True
    
    return False

def complete_operation(operation_id, status="complete", result=""):
    tracker = load_tracker()
    
    for op in tracker["operations"]:
        if op["id"] == operation_id:
            op["status"] = status
            op["completed"] = datetime.now(timezone.utc).isoformat()
            op["result"] = result
            save_tracker(tracker)
            print(f"[TRACKER] {operation_id}: {status}")
            return True
    
    return False

def list_active():
    tracker = load_tracker()
    active = [o for o in tracker["operations"] if o["status"] == "in_progress"]
    
    if not active:
        print("No active operations")
        return
    
    print("Active Operations:")
    print("-" * 60)
    for op in active:
        started = datetime.fromisoformat(op["started"].replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60
        print(f"  {op['id']}")
        print(f"    Progress: {op['progress']}")
        print(f"    Elapsed: {elapsed:.1f} min")
        print(f"    Status: {op['status']}")
        print()

def check_overdue():
    """Check for operations that need polling. Returns list of overdue ops."""
    tracker = load_tracker()
    now = datetime.now(timezone.utc).timestamp()
    overdue = []
    
    for op in tracker["operations"]:
        if op["status"] == "in_progress":
            if now > op.get("next_poll", 0):
                overdue.append(op)
    
    return overdue

def main():
    parser = argparse.ArgumentParser(description="Active operation tracker")
    parser.add_argument("action", choices=["add", "update", "complete", "list", "check"])
    parser.add_argument("--id", help="Operation ID")
    parser.add_argument("--desc", help="Operation description")
    parser.add_argument("--progress", help="Progress percentage")
    parser.add_argument("--message", help="Update message")
    parser.add_argument("--status", default="complete", help="Completion status")
    parser.add_argument("--estimate", type=int, help="Estimated duration in minutes")
    
    args = parser.parse_args()
    
    if args.action == "add":
        if not all([args.id, args.desc, args.estimate]):
            print("Error: --id, --desc, and --estimate required")
            sys.exit(1)
        add_operation(args.id, args.desc, args.estimate)
    
    elif args.action == "update":
        if not all([args.id, args.progress]):
            print("Error: --id and --progress required")
            sys.exit(1)
        update_operation(args.id, args.progress, args.message)
    
    elif args.action == "complete":
        if not args.id:
            print("Error: --id required")
            sys.exit(1)
        complete_operation(args.id, args.status, args.message or "")
    
    elif args.action == "list":
        list_active()
    
    elif args.action == "check":
        overdue = check_overdue()
        if overdue:
            print(f"[ALERT] {len(overdue)} operation(s) need polling:")
            for op in overdue:
                print(f"  - {op['id']}")
        else:
            print("All operations on track")

if __name__ == "__main__":
    main()
