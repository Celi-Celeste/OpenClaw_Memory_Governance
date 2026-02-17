#!/usr/bin/env python3
"""Run daily memory consolidation and transcript mirror rotation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from memory_lib import (
    MemoryEntry,
    ensure_workspace_layout,
    normalize_text,
    parse_date_from_filename,
    parse_memory_file,
    parse_iso_date,
    transcript_file,
    write_memory_file,
)


def _status_rank(status: str) -> int:
    order = {"active": 3, "refined": 2, "historical": 1}
    return order.get(status, 0)


def consolidate_semantic(workspace: Path, dry_run: bool) -> int:
    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    deduped = 0
    for path in sorted(semantic_dir.glob("*.md")):
        preamble, entries = parse_memory_file(path)
        if not entries:
            continue
        best_by_key: Dict[str, MemoryEntry] = {}
        for entry in entries:
            key = normalize_text(entry.body)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = entry
                continue
            winner = existing
            loser = entry
            if entry.get_float("importance", 0.0) > existing.get_float("importance", 0.0):
                winner, loser = entry, existing
            elif entry.get_float("importance", 0.0) == existing.get_float("importance", 0.0):
                if _status_rank(entry.meta.get("status", "")) > _status_rank(existing.meta.get("status", "")):
                    winner, loser = entry, existing
            if winner is entry:
                best_by_key[key] = entry
            deduped += 1
            if winner.meta.get("supersedes", "none") == "none" and loser.meta.get("supersedes", "none") != "none":
                winner.meta["supersedes"] = loser.meta.get("supersedes", "none")
        merged = list(best_by_key.values())
        if not dry_run:
            write_memory_file(path, preamble, merged)
    return deduped


def prune_episodic(workspace: Path, retention_days: int, dry_run: bool) -> int:
    episodic_dir = workspace / "memory" / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    cutoff = dt.date.today() - dt.timedelta(days=retention_days)
    removed = 0
    for path in sorted(episodic_dir.glob("*.md")):
        file_date = parse_date_from_filename(path.name)
        if file_date and file_date < cutoff:
            removed += 1
            if not dry_run:
                path.unlink(missing_ok=True)
    return removed


def _extract_timestamp(obj: Dict, fallback: dt.datetime) -> dt.datetime:
    for key in ["timestamp", "time", "createdAt", "created_at", "ts"]:
        value = obj.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            try:
                return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
            except (OSError, ValueError):
                continue
        parsed = parse_iso_date(str(value))
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
    return fallback


def _extract_role(obj: Dict) -> str:
    for key in ["role", "speaker", "author"]:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "unknown"


def _extract_text(obj: Dict) -> str:
    value = obj.get("content")
    if isinstance(value, str) and value.strip():
        return value.strip()
    for key in ["text", "message", "output"]:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(value, list):
        chunks: List[str] = []
        for item in value:
            if isinstance(item, dict):
                txt = item.get("text")
                if isinstance(txt, str) and txt.strip():
                    chunks.append(txt.strip())
            elif isinstance(item, str):
                chunks.append(item.strip())
        if chunks:
            return " ".join(chunks)
    return json.dumps(obj, ensure_ascii=True)


def _iter_session_events(sessions_dir: Path, since_date: dt.date) -> Iterable[Tuple[dt.datetime, str, str, str]]:
    for jsonl in sorted(sessions_dir.glob("*.jsonl")):
        fallback_ts = dt.datetime.fromtimestamp(jsonl.stat().st_mtime, tz=dt.timezone.utc)
        with jsonl.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ts = _extract_timestamp(obj, fallback=fallback_ts)
                if ts.date() < since_date:
                    continue
                role = _extract_role(obj)
                text = _extract_text(obj)
                text = " ".join(text.split())
                if len(text) > 1500:
                    text = text[:1497] + "..."
                yield (ts, role, text, jsonl.name)


def build_transcript_mirror(
    workspace: Path,
    sessions_dir: Path | None,
    retention_days: int,
    dry_run: bool,
) -> Tuple[int, int]:
    transcript_dir = workspace / "memory" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    since = today - dt.timedelta(days=retention_days - 1)

    written = 0
    if sessions_dir and sessions_dir.exists():
        by_day: Dict[dt.date, List[Tuple[dt.datetime, str, str, str]]] = defaultdict(list)
        for item in _iter_session_events(sessions_dir, since_date=since):
            by_day[item[0].date()].append(item)
        for day, events in sorted(by_day.items()):
            events.sort(key=lambda x: x[0])
            out = [f"# {day.isoformat()}", ""]
            for ts, role, text, source in events:
                out.append(f"## {ts.strftime('%H:%M:%S')} - {role} ({source})")
                out.append(text)
                out.append("")
            path = transcript_file(workspace, day)
            written += 1
            if not dry_run:
                path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

    removed = 0
    for path in sorted(transcript_dir.glob("*.md")):
        file_date = parse_date_from_filename(path.name)
        if file_date and file_date < since:
            removed += 1
            if not dry_run:
                path.unlink(missing_ok=True)
    return written, removed


def resolve_sessions_dir(args: argparse.Namespace) -> Path | None:
    if args.sessions_dir:
        return Path(args.sessions_dir).expanduser().resolve()
    if args.agent_id:
        return (Path.home() / ".openclaw" / "agents" / args.agent_id / "sessions").resolve()
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--episodic-retention-days", type=int, default=14)
    parser.add_argument("--transcript-retention-days", type=int, default=7)
    parser.add_argument("--sessions-dir", default="", help="Path to OpenClaw sessions directory.")
    parser.add_argument("--agent-id", default="", help="Agent id used to infer ~/.openclaw/agents/<id>/sessions.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    sessions_dir = resolve_sessions_dir(args)

    deduped = consolidate_semantic(workspace, dry_run=args.dry_run)
    pruned = prune_episodic(workspace, retention_days=args.episodic_retention_days, dry_run=args.dry_run)
    written, removed = build_transcript_mirror(
        workspace,
        sessions_dir=sessions_dir,
        retention_days=args.transcript_retention_days,
        dry_run=args.dry_run,
    )

    print(
        "daily_consolidate "
        f"semantic_deduped={deduped} "
        f"episodic_pruned={pruned} "
        f"transcripts_written={written} "
        f"transcripts_removed={removed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
