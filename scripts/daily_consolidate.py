#!/usr/bin/env python3
"""Run daily memory consolidation and transcript mirror rotation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from memory_lib import (
    DEFAULT_TRANSCRIPT_ROOT,
    LEGACY_TRANSCRIPT_ROOT,
    MemoryEntry,
    atomic_write_text,
    ensure_workspace_layout,
    file_lock,
    is_under_root,
    normalize_text,
    parse_date_from_filename,
    parse_memory_file,
    parse_iso_date,
    redact_secrets,
    resolve_transcript_root,
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
    return ""


def _iter_session_events(
    sessions_dir: Path,
    since_date: dt.date,
    transcript_mode: str,
) -> Iterable[Tuple[dt.datetime, str, str, str]]:
    sessions_root = sessions_dir.resolve()
    for jsonl in sorted(sessions_dir.glob("*.jsonl")):
        if jsonl.is_symlink():
            continue
        try:
            resolved_jsonl = jsonl.resolve(strict=True)
        except OSError:
            continue
        if not resolved_jsonl.is_file():
            continue
        if not is_under_root(resolved_jsonl, sessions_root):
            continue
        fallback_ts = dt.datetime.fromtimestamp(resolved_jsonl.stat().st_mtime, tz=dt.timezone.utc)
        with resolved_jsonl.open("r", encoding="utf-8") as fh:
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
                if not text:
                    continue
                text = " ".join(text.split())
                if transcript_mode == "sanitized":
                    text = redact_secrets(text)
                if len(text) > 1500:
                    text = text[:1497] + "..."
                yield (ts, role, text, jsonl.name)


def build_transcript_mirror(
    workspace: Path,
    sessions_dir: Path | None,
    transcript_dir: Path,
    retention_days: int,
    transcript_mode: str,
    dry_run: bool,
) -> Tuple[int, int]:
    today = dt.date.today()
    since = today - dt.timedelta(days=retention_days - 1)

    if transcript_mode == "off":
        removed = 0
        if transcript_dir.exists():
            for path in sorted(transcript_dir.glob("*.md")):
                removed += 1
                if not dry_run:
                    path.unlink(missing_ok=True)
        return 0, removed

    transcript_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(transcript_dir, 0o700)
    except OSError:
        pass
    written = 0
    if sessions_dir and sessions_dir.exists():
        by_day: Dict[dt.date, List[Tuple[dt.datetime, str, str, str]]] = defaultdict(list)
        for item in _iter_session_events(sessions_dir, since_date=since, transcript_mode=transcript_mode):
            by_day[item[0].date()].append(item)
        for day, events in sorted(by_day.items()):
            events.sort(key=lambda x: x[0])
            out = [f"# {day.isoformat()}", ""]
            for ts, role, text, source in events:
                out.append(f"## {ts.strftime('%H:%M:%S')} - {role} ({source})")
                out.append(text)
                out.append("")
            path = transcript_dir / f"{day.isoformat()}.md"
            written += 1
            if not dry_run:
                atomic_write_text(path, "\n".join(out).rstrip() + "\n", encoding="utf-8")
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass

    removed = 0
    for path in sorted(transcript_dir.glob("*.md")):
        file_date = parse_date_from_filename(path.name)
        if file_date and file_date < since:
            removed += 1
            if not dry_run:
                path.unlink(missing_ok=True)
    return written, removed


def migrate_legacy_transcripts(workspace: Path, transcript_dir: Path, dry_run: bool) -> Tuple[int, int]:
    legacy_dir = resolve_transcript_root(workspace, LEGACY_TRANSCRIPT_ROOT)
    if transcript_dir == legacy_dir or not legacy_dir.exists():
        return 0, 0

    legacy_files = sorted(legacy_dir.glob("*.md"))
    if not legacy_files:
        return 0, 0

    transcript_dir.mkdir(parents=True, exist_ok=True)
    existing_files = sorted(transcript_dir.glob("*.md"))
    if existing_files:
        return 0, len(legacy_files)

    migrated = 0
    for legacy_file in legacy_files:
        migrated += 1
        if not dry_run:
            target = transcript_dir / legacy_file.name
            shutil.move(str(legacy_file), str(target))
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
    return migrated, 0


def resolve_sessions_dir(args: argparse.Namespace) -> Path | None:
    if args.sessions_dir:
        return Path(args.sessions_dir).expanduser().resolve()
    if args.agent_id:
        return (Path.home() / ".openclaw" / "agents" / args.agent_id / "sessions").resolve()
    return None


def check_expired_entries(workspace: Path, dry_run: bool) -> Tuple[int, int]:
    """Check for and archive expired memory entries.

    Processes episodic and semantic layers, marking entries with passed
    valid_until dates as historical.

    Args:
        workspace: Path to OpenClaw workspace
        dry_run: If True, only report without modifying

    Returns:
        Tuple of (expired_episodic_count, expired_semantic_count)
    """
    today = dt.date.today()

    def process_layer(layer_dir: Path) -> int:
        """Process a single layer directory. Returns count of expired entries."""
        if not layer_dir.exists():
            return 0

        expired_count = 0
        for path in sorted(layer_dir.glob("*.md")):
            try:
                preamble, entries = parse_memory_file(path)
                modified = False

                for entry in entries:
                    valid_until = entry.meta.get("valid_until", "none")
                    if valid_until == "none":
                        continue

                    # Parse expiration date
                    try:
                        expiry_date = dt.date.fromisoformat(valid_until)
                        # Expire if date has passed (strictly less than today)
                        if expiry_date < today and entry.meta.get("status") != "historical":
                            entry.meta["status"] = "historical"
                            expired_count += 1
                            modified = True
                    except ValueError:
                        # Invalid date format, skip this entry
                        continue

                if modified and not dry_run:
                    write_memory_file(path, preamble, entries)
            except Exception as e:
                # Log error but continue processing other files
                print(f"check_expired_entries error processing {path}: {e}")
                continue

        return expired_count

    # Process both layers
    expired_episodic = process_layer(workspace / "memory" / "episodic")
    expired_semantic = process_layer(workspace / "memory" / "semantic")

    return expired_episodic, expired_semantic


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--episodic-retention-days", type=int, default=45)
    parser.add_argument("--transcript-retention-days", type=int, default=7)
    parser.add_argument(
        "--transcript-root",
        default=DEFAULT_TRANSCRIPT_ROOT,
        help="Transcript mirror root path. Relative paths are resolved from workspace root.",
    )
    parser.add_argument(
        "--allow-transcripts-under-memory",
        action="store_true",
        help="Allow transcript root under memory/. Disabled by default to preserve retrieval isolation.",
    )
    parser.add_argument(
        "--allow-external-transcript-root",
        action="store_true",
        help="Allow transcript root outside the workspace root. Disabled by default for safety.",
    )
    parser.add_argument(
        "--transcript-mode",
        choices=["sanitized", "full", "off"],
        default="sanitized",
        help="sanitized=redact likely secrets, full=raw transcript text, off=disable mirror files.",
    )
    parser.add_argument(
        "--acknowledge-transcript-risk",
        action="store_true",
        help=(
            "Required when using risky transcript options "
            "(full mode, external root, or root under memory/)."
        ),
    )
    parser.add_argument("--sessions-dir", default="", help="Path to OpenClaw sessions directory.")
    parser.add_argument("--agent-id", default="", help="Agent id used to infer ~/.openclaw/agents/<id>/sessions.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    sessions_dir = resolve_sessions_dir(args)
    transcript_dir = resolve_transcript_root(workspace, args.transcript_root)
    risky_options = []
    if args.transcript_mode == "full":
        risky_options.append("transcript-mode=full")
    if args.allow_external_transcript_root:
        risky_options.append("allow-external-transcript-root")
    if args.allow_transcripts_under_memory:
        risky_options.append("allow-transcripts-under-memory")
    if risky_options and not args.acknowledge_transcript_risk:
        raise SystemExit(
            "Refusing risky transcript options without explicit acknowledgment. "
            f"Detected: {', '.join(risky_options)}. "
            "Re-run with --acknowledge-transcript-risk if this is intentional."
        )
    if not is_under_root(transcript_dir, workspace) and not args.allow_external_transcript_root:
        raise SystemExit(
            "Refusing transcript root outside workspace. Keep transcripts under workspace/, "
            "or pass --allow-external-transcript-root to override."
        )
    memory_dir = (workspace / "memory").resolve()
    if is_under_root(transcript_dir, memory_dir) and not args.allow_transcripts_under_memory:
        raise SystemExit(
            "Refusing transcript root under memory/. Use --transcript-root outside memory/, "
            "or pass --allow-transcripts-under-memory to override."
        )

    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("daily_consolidate skipped=lock_held")
            return 0

        migrated, legacy_conflicts = migrate_legacy_transcripts(
            workspace,
            transcript_dir=transcript_dir,
            dry_run=args.dry_run,
        )

        deduped = consolidate_semantic(workspace, dry_run=args.dry_run)
        pruned = prune_episodic(workspace, retention_days=args.episodic_retention_days, dry_run=args.dry_run)
        expired_epi, expired_sem = check_expired_entries(workspace, dry_run=args.dry_run)
        written, removed = build_transcript_mirror(
            workspace,
            sessions_dir=sessions_dir,
            transcript_dir=transcript_dir,
            retention_days=args.transcript_retention_days,
            transcript_mode=args.transcript_mode,
            dry_run=args.dry_run,
        )

        print(
            "daily_consolidate "
            f"semantic_deduped={deduped} "
            f"episodic_pruned={pruned} "
            f"expired_episodic={expired_epi} "
            f"expired_semantic={expired_sem} "
            f"transcript_root={transcript_dir} "
            f"transcript_mode={args.transcript_mode} "
            f"transcripts_written={written} "
            f"transcripts_removed={removed} "
            f"legacy_migrated={migrated} "
            f"legacy_conflicts={legacy_conflicts}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
