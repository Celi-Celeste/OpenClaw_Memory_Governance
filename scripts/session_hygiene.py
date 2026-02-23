#!/usr/bin/env python3
"""Harden OpenClaw session JSONL storage with redaction, retention, and permissions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from memory_lib import atomic_write_text, file_lock, is_under_root, redact_secrets

SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|passphrase|private[_-]?key|bearer)"
)


def resolve_sessions_dir(args: argparse.Namespace) -> Path:
    if args.sessions_dir:
        return Path(args.sessions_dir).expanduser().resolve()
    if args.agent_id:
        return (Path.home() / ".openclaw" / "agents" / args.agent_id / "sessions").resolve()
    raise SystemExit("Provide --sessions-dir or --agent-id.")


def apply_permissions(path: Path, mode: int, dry_run: bool) -> bool:
    if dry_run:
        return False
    try:
        os.chmod(path, mode)
        return True
    except OSError:
        return False


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(key.strip()))


def _redact_value(value: Any, key_hint: str = "") -> Tuple[Any, bool]:
    if isinstance(value, str):
        if _is_sensitive_key(key_hint) and value.strip():
            redacted = "<REDACTED>"
            return redacted, redacted != value
        redacted = redact_secrets(value)
        return redacted, redacted != value
    if isinstance(value, list):
        changed = False
        updated = []
        for item in value:
            new_item, item_changed = _redact_value(item, key_hint=key_hint)
            updated.append(new_item)
            changed = changed or item_changed
        return updated, changed
    if isinstance(value, dict):
        changed = False
        updated: Dict[str, Any] = {}
        for k, v in value.items():
            new_v, v_changed = _redact_value(v, key_hint=str(k))
            updated[k] = new_v
            changed = changed or v_changed
        return updated, changed
    return value, False


def redact_jsonl_file(path: Path, dry_run: bool) -> Tuple[int, int]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    out_lines = []
    changed_events = 0
    changed_lines = 0

    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            out_lines.append(raw)
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            out_lines.append(raw)
            continue

        redacted_obj, changed = _redact_value(obj)
        if changed:
            changed_events += 1
            rendered = json.dumps(redacted_obj, ensure_ascii=False)
            out_lines.append(rendered)
            if rendered != stripped:
                changed_lines += 1
        else:
            out_lines.append(raw)

    if changed_lines > 0 and not dry_run:
        atomic_write_text(path, "\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

    return changed_events, changed_lines


def prune_sessions_store(store_path: Path, existing_jsonl: set[str], dry_run: bool) -> int:
    if not store_path.exists():
        return 0

    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    removed = 0
    cleaned: Dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            cleaned[key] = value
            continue
        session_id = str(value.get("sessionId", "")).strip()
        if not session_id:
            cleaned[key] = value
            continue
        if any(name.startswith(f"{session_id}") and name.endswith(".jsonl") for name in existing_jsonl):
            cleaned[key] = value
            continue
        removed += 1

    if removed > 0 and not dry_run:
        atomic_write_text(store_path, json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return removed


def list_safe_jsonl_files(sessions_dir: Path) -> Tuple[list[Path], int, int]:
    safe_files: list[Path] = []
    skipped_symlink = 0
    skipped_outside = 0
    sessions_root = sessions_dir.resolve()
    for path in sorted(sessions_dir.glob("*.jsonl")):
        if path.is_symlink():
            skipped_symlink += 1
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not is_under_root(resolved, sessions_root):
            skipped_outside += 1
            continue
        safe_files.append(resolved)
    return safe_files, skipped_symlink, skipped_outside


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-dir", default="", help="Explicit OpenClaw sessions directory.")
    parser.add_argument("--agent-id", default="", help="OpenClaw agent id for default sessions path.")
    parser.add_argument("--retention-days", type=int, default=30, help="Delete JSONL logs older than this many days. Set <=0 to disable pruning.")
    parser.add_argument("--skip-recent-minutes", type=int, default=30, help="Skip redaction for files modified within this window.")
    parser.add_argument("--disable-redaction", action="store_true", help="Disable in-place secret redaction.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sessions_dir = resolve_sessions_dir(args)
    if not sessions_dir.exists():
        raise SystemExit(f"sessions directory does not exist: {sessions_dir}")

    lock_path = sessions_dir / ".session-hygiene.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("session_hygiene skipped=lock_held")
            return 0

        now = dt.datetime.now(dt.timezone.utc)
        prune_cutoff = now - dt.timedelta(days=max(args.retention_days, 0))
        recent_cutoff = now - dt.timedelta(minutes=max(args.skip_recent_minutes, 0))

        perms_dirs = 0
        perms_files = 0
        redacted_events = 0
        redacted_files = 0
        skipped_recent = 0
        pruned_files = 0
        skipped_symlink = 0
        skipped_outside = 0

        if apply_permissions(sessions_dir, 0o700, args.dry_run):
            perms_dirs += 1

        jsonl_files, skipped_symlink, skipped_outside = list_safe_jsonl_files(sessions_dir)
        for path in jsonl_files:
            stat = path.stat()
            mtime = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)

            if args.retention_days > 0 and mtime < prune_cutoff:
                pruned_files += 1
                if not args.dry_run:
                    path.unlink(missing_ok=True)
                continue

            if apply_permissions(path, 0o600, args.dry_run):
                perms_files += 1

            if args.disable_redaction:
                continue
            if mtime >= recent_cutoff:
                skipped_recent += 1
                continue

            changed_events, changed_lines = redact_jsonl_file(path, dry_run=args.dry_run)
            redacted_events += changed_events
            if changed_lines > 0:
                redacted_files += 1

        sessions_json = sessions_dir / "sessions.json"
        if sessions_json.exists():
            if apply_permissions(sessions_json, 0o600, args.dry_run):
                perms_files += 1
            existing_jsonl = {p.name for p in jsonl_files if p.exists()}
            pruned_store_entries = prune_sessions_store(sessions_json, existing_jsonl=existing_jsonl, dry_run=args.dry_run)
        else:
            pruned_store_entries = 0

        print(
            "session_hygiene "
            f"sessions_dir={sessions_dir} "
            f"retention_days={args.retention_days} "
            f"redaction_enabled={str(not args.disable_redaction).lower()} "
            f"permissions_dirs={perms_dirs} "
            f"permissions_files={perms_files} "
            f"redacted_files={redacted_files} "
            f"redacted_events={redacted_events} "
            f"skipped_recent={skipped_recent} "
            f"pruned_files={pruned_files} "
            f"skipped_symlink={skipped_symlink} "
            f"skipped_outside={skipped_outside} "
            f"pruned_store_entries={pruned_store_entries}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
