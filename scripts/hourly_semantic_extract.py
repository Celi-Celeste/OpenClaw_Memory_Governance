#!/usr/bin/env python3
"""Promote high-importance episodic entries into semantic candidates."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from memory_lib import (
    MemoryEntry,
    ensure_workspace_layout,
    episodic_file,
    file_lock,
    new_mem_id,
    parse_memory_file,
    semantic_file,
    utc_now_z,
    write_memory_file,
)


def summarize_for_semantic(body: str) -> str:
    text = " ".join(body.split()).strip()
    if len(text) <= 280:
        return text
    return text[:277].rstrip() + "..."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--semantic-threshold", type=float, default=0.70)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("hourly_semantic_extract skipped=lock_held")
            return 0

        today = dt.date.today()
        days_back = max(1, int((args.lookback_hours + 23) / 24))
        dates = [today - dt.timedelta(days=offset) for offset in range(days_back)]

        promoted = 0
        for day in dates:
            epi_path = episodic_file(workspace, day)
            _, episodic_entries = parse_memory_file(epi_path)
            sem_path = semantic_file(workspace, day)
            sem_preamble, sem_entries = parse_memory_file(sem_path)
            existing_origin_ids = {e.meta.get("origin_id", "") for e in sem_entries}
            day_promoted = 0

            for entry in episodic_entries:
                importance = entry.get_float("importance", 0.0)
                if importance < args.semantic_threshold:
                    continue
                if entry.entry_id in existing_origin_ids:
                    continue
                summary = summarize_for_semantic(entry.body)
                if not summary:
                    continue
                new_entry = MemoryEntry(
                    entry_id=new_mem_id(),
                    meta={
                        "time": utc_now_z(),
                        "layer": "semantic",
                        "importance": f"{max(importance, args.semantic_threshold):.2f}",
                        "confidence": f"{entry.get_float('confidence', 0.65):.2f}",
                        "status": "active",
                        "source": "job:hourly-semantic-extract",
                        "tags": str(entry.tags()),
                        "supersedes": "none",
                        "origin_id": entry.entry_id,
                    },
                    body=f"Derived from mem:{entry.entry_id}. {summary}",
                )
                sem_entries.append(new_entry)
                promoted += 1
                day_promoted += 1

            if day_promoted and not args.dry_run:
                write_memory_file(sem_path, sem_preamble, sem_entries)

        print(f"hourly_semantic_extract promoted={promoted}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
