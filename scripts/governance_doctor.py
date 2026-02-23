#!/usr/bin/env python3
"""Health checks and optional self-heal for OpenClaw Memory Governance."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from memory_lib import file_lock, is_under_root, parse_iso_date, resolve_transcript_root
from select_memory_profile import detect_qmd

CRON_BEGIN = "# >>> OPENCLAW_MEMORY_GOVERNANCE_BEGIN >>>"
CRON_END = "# <<< OPENCLAW_MEMORY_GOVERNANCE_END <<<"

REQUIRED_SCRIPTS = [
    "memory_lib.py",
    "hourly_semantic_extract.py",
    "importance_score.py",
    "daily_consolidate.py",
    "confidence_gate.py",
    "confidence_gate_flow.py",
    "ordered_recall.py",
    "weekly_identity_promote.py",
    "weekly_drift_review.py",
    "transcript_lookup.py",
    "select_memory_profile.py",
    "bootstrap_profile_once.py",
    "activate.py",
    "governance_doctor.py",
    "session_hygiene.py",
    "render_schedule.py",
]

EXPECTED_LAUNCHD = [
    "com.openclaw.memory.bootstrap.plist",
    "com.openclaw.memory.importance.plist",
    "com.openclaw.memory.hourly.plist",
    "com.openclaw.memory.daily.plist",
    "com.openclaw.memory.weekly-identity.plist",
    "com.openclaw.memory.weekly.plist",
    "com.openclaw.memory.session-hygiene.plist",
]


def _now_z() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mode(path: Path) -> int | None:
    if not path.exists():
        return None
    return stat.S_IMODE(path.stat().st_mode)


def _chmod(path: Path, desired: int, dry_run: bool) -> bool:
    if dry_run:
        return False
    try:
        os.chmod(path, desired)
        return True
    except OSError:
        return False


def _load_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _cron_block_present() -> tuple[bool | None, str]:
    proc = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        if "no crontab" in stderr:
            return False, "no_crontab"
        if "not found" in stderr:
            return None, "crontab_missing"
        return None, f"crontab_error_{proc.returncode}"
    text = proc.stdout or ""
    return (CRON_BEGIN in text and CRON_END in text), "ok"


def _check_launchd_loaded(launchd_dir: Path) -> tuple[int, int]:
    if platform.system().lower() != "darwin":
        return 0, 0
    loaded = 0
    total = 0
    uid = str(os.getuid())
    for plist in EXPECTED_LAUNCHD:
        plist_path = launchd_dir / plist
        if not plist_path.exists():
            continue
        total += 1
        label = plist.replace(".plist", "")
        proc = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{label}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            loaded += 1
    return loaded, total


def _append_check(checks: List[Dict[str, Any]], check_id: str, result: str, message: str, fix_applied: bool = False) -> None:
    checks.append(
        {
            "id": check_id,
            "result": result,
            "message": message,
            "fix_applied": bool(fix_applied),
        }
    )


def _status(checks: List[Dict[str, Any]]) -> str:
    results = [c.get("result") for c in checks]
    if "fail" in results:
        return "fail"
    if "warn" in results:
        return "warn"
    return "ok"


def _next_actions(checks: List[Dict[str, Any]]) -> List[str]:
    actions: List[str] = []
    for c in checks:
        cid = c.get("id")
        result = c.get("result")
        if result not in {"warn", "fail"}:
            continue
        if cid == "scheduler_presence":
            actions.append("Run activate.py to install scheduler jobs, or run governance_doctor.py with --fix where applicable.")
        elif cid == "backend_consistency":
            actions.append("If qmd availability changed, rerun activate.py --force-bootstrap.")
        elif cid == "bootstrap_state":
            actions.append("Run activate.py to create or refresh profile bootstrap state.")
        elif cid == "transcript_root_safety":
            actions.append("Use archive/transcripts outside memory/ and keep transcript mode sanitized or off.")
        elif cid == "cadence_lock":
            actions.append("If lock remains stale, stop conflicting jobs and rerun governance_doctor.py --fix.")
        elif cid == "importance_freshness":
            actions.append("Verify scheduler jobs are running; importance_score checkpoint is stale or missing.")
    # Deduplicate while preserving order.
    seen = set()
    out: List[str] = []
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        out.append(action)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(Path.home() / ".openclaw" / "workspace"))
    parser.add_argument("--target-config", default=str(Path.home() / ".openclaw" / "openclaw.json"))
    parser.add_argument("--agent-id", default="main")
    parser.add_argument("--sessions-dir", default="")
    parser.add_argument("--launchd-dir", default=str(Path.home() / ".openclaw" / "memory-plists"))
    parser.add_argument("--transcript-root", default="archive/transcripts")
    parser.add_argument("--qmd-command", default="qmd")
    parser.add_argument("--qmd-timeout-seconds", type=int, default=4)
    parser.add_argument("--stale-lock-hours", type=int, default=24)
    parser.add_argument("--max-importance-age-hours", type=int, default=36)
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    workspace = Path(args.workspace).expanduser().resolve()
    target_config = Path(args.target_config).expanduser().resolve()
    launchd_dir = Path(args.launchd_dir).expanduser().resolve()
    script_dir = Path(__file__).resolve().parent
    checks: List[Dict[str, Any]] = []

    missing_scripts = [name for name in REQUIRED_SCRIPTS if not (script_dir / name).exists()]
    if missing_scripts:
        _append_check(
            checks,
            "script_integrity",
            "fail",
            "Missing required scripts: " + ", ".join(missing_scripts),
        )
    else:
        _append_check(checks, "script_integrity", "pass", "Required scripts are present.")

    required_dirs = [
        workspace / "memory" / "episodic",
        workspace / "memory" / "semantic",
        workspace / "memory" / "identity",
        workspace / "memory" / "state",
        workspace / "memory" / "locks",
        workspace / "memory" / "logs",
        workspace / "archive" / "transcripts",
    ]
    missing_dirs = [p for p in required_dirs if not p.exists()]
    created_count = 0
    if missing_dirs and args.fix:
        for path in missing_dirs:
            path.mkdir(parents=True, exist_ok=True)
            created_count += 1
        missing_dirs = [p for p in required_dirs if not p.exists()]
    if missing_dirs:
        _append_check(
            checks,
            "workspace_layout",
            "warn",
            f"Missing required directories ({len(missing_dirs)}).",
            fix_applied=created_count > 0,
        )
    else:
        message = "Workspace layout looks complete."
        if created_count > 0:
            message += f" Created {created_count} missing directories."
        _append_check(checks, "workspace_layout", "pass", message, fix_applied=created_count > 0)

    state_path = workspace / "memory" / "state" / "profile-bootstrap.json"
    state_payload = _load_json(state_path)
    if state_payload is None:
        _append_check(checks, "bootstrap_state", "warn", f"Bootstrap state missing or invalid: {state_path}")
    else:
        backend = str(state_payload.get("selected_backend", "")).strip()
        if backend not in {"builtin", "qmd"}:
            _append_check(checks, "bootstrap_state", "warn", "Bootstrap state exists but selected_backend is missing/invalid.")
        else:
            _append_check(checks, "bootstrap_state", "pass", f"Bootstrap state present (backend={backend}).")

    config_payload = _load_json(target_config)
    if config_payload is None:
        if target_config.exists():
            _append_check(checks, "target_config", "fail", f"Config exists but is invalid JSON: {target_config}")
        else:
            _append_check(checks, "target_config", "warn", f"Config not found: {target_config}")
    else:
        _append_check(checks, "target_config", "pass", f"Target config loaded: {target_config}")

    qmd_detected, qmd_reason = detect_qmd(args.qmd_command, args.qmd_timeout_seconds)
    configured_backend = "builtin"
    if config_payload is not None:
        if str(config_payload.get("memory", {}).get("backend", "")).strip() == "qmd":
            configured_backend = "qmd"
    if configured_backend == "qmd" and not qmd_detected:
        _append_check(
            checks,
            "backend_consistency",
            "fail",
            f"Configured backend is qmd but detection failed ({qmd_reason}).",
        )
    elif configured_backend != "qmd" and qmd_detected:
        _append_check(
            checks,
            "backend_consistency",
            "warn",
            "qmd is available but config backend is builtin (rerun activate.py --force-bootstrap if qmd is desired).",
        )
    else:
        _append_check(checks, "backend_consistency", "pass", f"Backend/config alignment ok ({configured_backend}).")

    cron_ok, cron_reason = _cron_block_present()
    launchd_existing = sum(1 for name in EXPECTED_LAUNCHD if (launchd_dir / name).exists())
    is_darwin = platform.system().lower() == "darwin"
    if is_darwin:
        if launchd_existing >= len(EXPECTED_LAUNCHD):
            _append_check(checks, "scheduler_presence", "pass", f"launchd plists present in {launchd_dir}")
        elif cron_ok is True:
            _append_check(checks, "scheduler_presence", "pass", "Managed cron block present.")
        else:
            _append_check(
                checks,
                "scheduler_presence",
                "warn",
                f"Scheduler entries not detected (launchd plists={launchd_existing}/{len(EXPECTED_LAUNCHD)}, cron={cron_reason}).",
            )
    else:
        if cron_ok is True:
            _append_check(checks, "scheduler_presence", "pass", "Managed cron block present.")
        else:
            _append_check(
                checks,
                "scheduler_presence",
                "warn",
                f"Managed cron block not detected ({cron_reason}).",
            )

    transcript_root = resolve_transcript_root(workspace, args.transcript_root)
    transcript_under_memory = is_under_root(transcript_root, workspace / "memory")
    transcript_outside_workspace = not is_under_root(transcript_root, workspace)
    if transcript_under_memory:
        _append_check(checks, "transcript_root_safety", "fail", f"Transcript root is under memory/: {transcript_root}")
    elif transcript_outside_workspace:
        _append_check(checks, "transcript_root_safety", "fail", f"Transcript root is outside workspace: {transcript_root}")
    else:
        transcript_root.mkdir(parents=True, exist_ok=True)
        fix_applied = False
        mode = _mode(transcript_root)
        if mode != 0o700 and args.fix:
            fix_applied = _chmod(transcript_root, 0o700, dry_run=False) or fix_applied
            mode = _mode(transcript_root)
        bad_files = []
        fixed_files = 0
        for path in transcript_root.glob("*.md"):
            file_mode = _mode(path)
            if file_mode != 0o600:
                bad_files.append(path)
                if args.fix and _chmod(path, 0o600, dry_run=False):
                    fixed_files += 1
        if mode != 0o700 or bad_files:
            if args.fix:
                mode = _mode(transcript_root)
                remaining = [p for p in transcript_root.glob("*.md") if _mode(p) != 0o600]
                if mode == 0o700 and not remaining:
                    _append_check(
                        checks,
                        "transcript_root_safety",
                        "pass",
                        f"Transcript permissions corrected ({fixed_files} files fixed).",
                        fix_applied=True,
                    )
                else:
                    _append_check(
                        checks,
                        "transcript_root_safety",
                        "warn",
                        f"Transcript permissions still need correction (dir_mode={oct(mode or 0)}, files={len(remaining)}).",
                        fix_applied=fix_applied or fixed_files > 0,
                    )
            else:
                _append_check(
                    checks,
                    "transcript_root_safety",
                    "warn",
                    f"Transcript permissions should be dir=0700,file=0600 (dir_mode={oct(mode or 0)}, files_needing_fix={len(bad_files)}).",
                )
        else:
            _append_check(checks, "transcript_root_safety", "pass", "Transcript root placement and permissions are safe.")

    legacy_dir = workspace / "memory" / "transcripts"
    if legacy_dir.exists() and any(legacy_dir.glob("*.md")):
        _append_check(
            checks,
            "legacy_transcripts",
            "warn",
            "Legacy transcript files detected under memory/transcripts; default retrieval exclusion may be weakened.",
        )
    else:
        _append_check(checks, "legacy_transcripts", "pass", "No legacy transcript files detected under memory/transcripts.")

    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    if lock_path.exists():
        age_hours = (now - dt.datetime.fromtimestamp(lock_path.stat().st_mtime, tz=dt.timezone.utc)).total_seconds() / 3600.0
        if age_hours > max(args.stale_lock_hours, 1):
            cleared = False
            if args.fix:
                with file_lock(lock_path) as locked:
                    if locked:
                        try:
                            lock_path.unlink(missing_ok=True)
                            cleared = True
                        except OSError:
                            cleared = False
            if cleared:
                _append_check(
                    checks,
                    "cadence_lock",
                    "pass",
                    f"Cleared stale cadence lock older than {args.stale_lock_hours}h.",
                    fix_applied=True,
                )
            else:
                _append_check(
                    checks,
                    "cadence_lock",
                    "warn",
                    f"Cadence lock is stale ({age_hours:.1f}h old).",
                )
        else:
            _append_check(checks, "cadence_lock", "pass", "Cadence lock age is normal.")
    else:
        _append_check(checks, "cadence_lock", "pass", "Cadence lock file not present (normal when idle).")

    sessions_dir = Path(args.sessions_dir).expanduser().resolve() if args.sessions_dir else (Path.home() / ".openclaw" / "agents" / args.agent_id / "sessions").resolve()
    if not sessions_dir.exists():
        _append_check(checks, "session_permissions", "pass", f"Sessions dir not found (skipped): {sessions_dir}")
    else:
        fixed = False
        dir_mode = _mode(sessions_dir)
        if dir_mode != 0o700 and args.fix:
            fixed = _chmod(sessions_dir, 0o700, dry_run=False) or fixed
            dir_mode = _mode(sessions_dir)
        files_needing = []
        for path in list(sessions_dir.glob("*.jsonl")) + [sessions_dir / "sessions.json"]:
            if not path.exists() or path.is_symlink():
                continue
            mode = _mode(path)
            if mode != 0o600:
                files_needing.append(path)
                if args.fix:
                    fixed = _chmod(path, 0o600, dry_run=False) or fixed
        if dir_mode == 0o700 and not files_needing:
            _append_check(checks, "session_permissions", "pass", "Session directory/file permissions are safe.")
        else:
            if args.fix:
                remaining = []
                for path in list(sessions_dir.glob("*.jsonl")) + [sessions_dir / "sessions.json"]:
                    if not path.exists() or path.is_symlink():
                        continue
                    if _mode(path) != 0o600:
                        remaining.append(path)
                if _mode(sessions_dir) == 0o700 and not remaining:
                    _append_check(checks, "session_permissions", "pass", "Session permissions corrected.", fix_applied=True)
                else:
                    _append_check(
                        checks,
                        "session_permissions",
                        "warn",
                        f"Session permissions still need correction (dir_mode={oct(_mode(sessions_dir) or 0)}, files={len(remaining)}).",
                        fix_applied=fixed,
                    )
            else:
                _append_check(
                    checks,
                    "session_permissions",
                    "warn",
                    f"Session permissions should be dir=0700,file=0600 (dir_mode={oct(dir_mode or 0)}, files_needing_fix={len(files_needing)}).",
                )

    if args.mode == "full":
        if is_darwin:
            loaded, total = _check_launchd_loaded(launchd_dir)
            if total == 0:
                _append_check(checks, "launchd_loaded", "warn", f"No launchd plists found in {launchd_dir}")
            elif loaded < total:
                _append_check(checks, "launchd_loaded", "warn", f"launchd loaded {loaded}/{total} expected jobs.")
            else:
                _append_check(checks, "launchd_loaded", "pass", "All detected launchd jobs are loaded.")

        importance_state = workspace / "memory" / "state" / "importance-score.json"
        payload = _load_json(importance_state)
        if payload is None:
            _append_check(checks, "importance_freshness", "warn", f"Importance checkpoint missing or invalid: {importance_state}")
        else:
            last_run = parse_iso_date(str(payload.get("last_run_at", "")).strip())
            if last_run is None:
                _append_check(checks, "importance_freshness", "warn", "Importance checkpoint missing last_run_at.")
            else:
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=dt.timezone.utc)
                age_h = (now - last_run).total_seconds() / 3600.0
                if age_h > max(args.max_importance_age_hours, 1):
                    _append_check(
                        checks,
                        "importance_freshness",
                        "warn",
                        f"Importance checkpoint is stale ({age_h:.1f}h old).",
                    )
                else:
                    _append_check(checks, "importance_freshness", "pass", f"Importance checkpoint freshness ok ({age_h:.1f}h).")

    overall = _status(checks)
    payload = {
        "status": overall,
        "checked_at": _now_z(),
        "mode": args.mode,
        "workspace": str(workspace),
        "target_config": str(target_config),
        "fix": bool(args.fix),
        "strict": bool(args.strict),
        "checks": checks,
        "next_actions": _next_actions(checks),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"governance_doctor status={overall} mode={args.mode} fix={bool(args.fix)}")
        for item in checks:
            print(f"- [{item['result'].upper()}] {item['id']}: {item['message']}")
        if payload["next_actions"]:
            print("next_actions:")
            for action in payload["next_actions"]:
                print(f"- {action}")

    if overall == "fail":
        return 1
    if overall == "warn" and args.strict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
