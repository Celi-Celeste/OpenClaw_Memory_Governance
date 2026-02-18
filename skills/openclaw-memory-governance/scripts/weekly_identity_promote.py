#!/usr/bin/env python3
"""Promote recurring high-importance semantic memories into identity files."""

from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from memory_lib import (
    MemoryEntry,
    ensure_workspace_layout,
    file_lock,
    new_mem_id,
    normalize_text,
    parse_iso_date,
    parse_memory_file,
    utc_now_z,
    write_memory_file,
)

PREFERENCE_TAGS = {"preference", "style", "workflow", "tooling"}
DECISION_TAGS = {"decision", "architecture", "policy", "constraint"}


def _identity_targets(workspace: Path) -> Dict[str, Path]:
    base = workspace / "memory" / "identity"
    return {
        "identity": base / "identity.md",
        "preferences": base / "preferences.md",
        "decisions": base / "decisions.md",
    }


def _route_identity_file(tags: List[str]) -> str:
    lowered = {t.lower() for t in tags}
    if lowered & PREFERENCE_TAGS:
        return "preferences"
    if lowered & DECISION_TAGS:
        return "decisions"
    return "identity"


def _load_semantic_entries(workspace: Path, cutoff: dt.datetime) -> Dict[str, List[MemoryEntry]]:
    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    grouped: Dict[str, List[MemoryEntry]] = defaultdict(list)
    for path in sorted(semantic_dir.glob("*.md")):
        _, entries = parse_memory_file(path)
        for entry in entries:
            parsed = parse_iso_date(entry.meta.get("time", ""))
            if parsed is None:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            if parsed < cutoff:
                continue
            key = normalize_text(entry.body)
            if not key:
                continue
            grouped[key].append(entry)
    return grouped


def _load_existing_identity_signatures(workspace: Path) -> Tuple[set[str], set[str]]:
    keys: set[str] = set()
    origin_ids: set[str] = set()
    for path in _identity_targets(workspace).values():
        _, entries = parse_memory_file(path)
        for entry in entries:
            body_key = normalize_text(entry.body)
            if body_key:
                keys.add(body_key)
            origin_id = entry.meta.get("origin_id", "").strip()
            if origin_id:
                origin_ids.add(origin_id)
    return keys, origin_ids


def _select_best_entry(entries: List[MemoryEntry]) -> MemoryEntry:
    def sort_key(entry: MemoryEntry) -> Tuple[float, dt.datetime]:
        importance = entry.get_float("importance", 0.0)
        ts = parse_iso_date(entry.meta.get("time", "")) or dt.datetime.now(dt.timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return (importance, ts)

    return max(entries, key=sort_key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--min-importance", type=float, default=0.85)
    parser.add_argument("--min-recurrence", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("weekly_identity_promote skipped=lock_held")
            return 0

        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.window_days)

        grouped = _load_semantic_entries(workspace, cutoff=cutoff)
        existing_keys, existing_origin_ids = _load_existing_identity_signatures(workspace)

        target_files = _identity_targets(workspace)
        loaded_targets: Dict[str, Tuple[str, List[MemoryEntry]]] = {}
        for name, path in target_files.items():
            loaded_targets[name] = parse_memory_file(path)

        promoted_counts = {"identity": 0, "preferences": 0, "decisions": 0}
        skipped_duplicate = 0
        skipped_threshold = 0

        for key, entries in grouped.items():
            recurrence = len(entries)
            best = _select_best_entry(entries)
            if recurrence < args.min_recurrence or best.get_float("importance", 0.0) < args.min_importance:
                skipped_threshold += 1
                continue

            best_origin_id = best.meta.get("origin_id", "").strip() or best.entry_id
            if key in existing_keys or best_origin_id in existing_origin_ids:
                skipped_duplicate += 1
                continue

            target_name = _route_identity_file(best.tags())
            _, target_entries = loaded_targets[target_name]
            target_entries.append(
                MemoryEntry(
                    entry_id=new_mem_id(),
                    meta={
                        "time": utc_now_z(),
                        "layer": "identity",
                        "importance": f"{best.get_float('importance', args.min_importance):.2f}",
                        "confidence": f"{best.get_float('confidence', 0.75):.2f}",
                        "status": "active",
                        "source": "job:weekly-identity-promote",
                        "tags": str(best.tags()),
                        "supersedes": "none",
                        "origin_id": best_origin_id,
                        "recurrence": str(recurrence),
                    },
                    body=best.body,
                )
            )
            promoted_counts[target_name] += 1
            existing_keys.add(key)
            existing_origin_ids.add(best_origin_id)

        if not args.dry_run:
            for target_name, (preamble, entries) in loaded_targets.items():
                write_memory_file(target_files[target_name], preamble, entries)

        print(
            "weekly_identity_promote "
            f"promoted_identity={promoted_counts['identity']} "
            f"promoted_preferences={promoted_counts['preferences']} "
            f"promoted_decisions={promoted_counts['decisions']} "
            f"skipped_threshold={skipped_threshold} "
            f"skipped_duplicate={skipped_duplicate}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
