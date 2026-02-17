#!/usr/bin/env python3
"""Run weekly semantic drift review and soft-forgetting transitions."""

from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from memory_lib import (
    MemoryEntry,
    ensure_workspace_layout,
    jaccard_similarity,
    parse_iso_date,
    parse_memory_file,
    write_memory_file,
)

SUPERSEDE_HINTS = [
    "no longer",
    "replaced",
    "supersede",
    "superseded",
    "instead",
    "changed to",
    "moved from",
    "switched to",
]


def classify_relation(newer: MemoryEntry, older: MemoryEntry) -> str:
    sim = jaccard_similarity(newer.token_set(), older.token_set())
    body = newer.body.lower()
    if sim >= 0.20 and any(hint in body for hint in SUPERSEDE_HINTS):
        return "SUPERSEDES"
    if sim >= 0.85:
        return "REINFORCES"
    if sim >= 0.55:
        return "REFINES"
    return "UNRELATED"


def load_semantic_entries(workspace: Path) -> List[Tuple[Path, str, List[MemoryEntry]]]:
    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    items: List[Tuple[Path, str, List[MemoryEntry]]] = []
    for path in sorted(semantic_dir.glob("*.md")):
        preamble, entries = parse_memory_file(path)
        items.append((path, preamble, entries))
    return items


def append_drift_log(workspace: Path, lines: List[str], dry_run: bool) -> None:
    if not lines:
        return
    path = workspace / "memory" / "drift-log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip() + "\n\n"
    payload = existing + "\n".join(lines).rstrip() + "\n"
    if not dry_run:
        path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    bundles = load_semantic_entries(workspace)

    all_entries: List[Tuple[Path, MemoryEntry]] = []
    for path, _, entries in bundles:
        for e in entries:
            all_entries.append((path, e))

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=args.window_days)
    recent: List[Tuple[Path, MemoryEntry]] = []
    older: List[Tuple[Path, MemoryEntry]] = []

    for path, entry in all_entries:
        ts = parse_iso_date(entry.meta.get("time", "")) or now
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        if entry.meta.get("status", "active") == "historical":
            continue
        if ts >= cutoff:
            recent.append((path, entry))
        else:
            older.append((path, entry))

    by_file: Dict[Path, Tuple[str, List[MemoryEntry]]] = {}
    for path, preamble, entries in bundles:
        by_file[path] = (preamble, entries)

    actions: List[str] = []
    changed = 0
    relation_counts = defaultdict(int)
    for _, new_entry in recent:
        new_tags = set(new_entry.tags())
        for _, old_entry in older:
            if old_entry.meta.get("status", "active") == "historical":
                continue
            old_tags = set(old_entry.tags())
            if new_tags and old_tags and not (new_tags & old_tags):
                continue
            relation = classify_relation(new_entry, old_entry)
            relation_counts[relation] += 1
            if relation == "SUPERSEDES":
                old_entry.meta["status"] = "historical"
                new_entry.meta["supersedes"] = f"mem:{old_entry.entry_id}"
                changed += 1
                actions.append(
                    f"- {now.date().isoformat()} SUPERSEDES new=mem:{new_entry.entry_id} "
                    f"old=mem:{old_entry.entry_id}"
                )

    if changed and not args.dry_run:
        for path, (preamble, entries) in by_file.items():
            write_memory_file(path, preamble, entries)
    append_drift_log(workspace, actions, dry_run=args.dry_run)

    print(
        "weekly_drift_review "
        f"supersedes={relation_counts['SUPERSEDES']} "
        f"refines={relation_counts['REFINES']} "
        f"reinforces={relation_counts['REINFORCES']} "
        f"changed={changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
