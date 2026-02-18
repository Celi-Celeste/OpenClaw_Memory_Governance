#!/usr/bin/env python3
"""Select builtin vs qmd memory profile and optionally apply it."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            if key in out:
                out[key] = deep_merge(out[key], value)
            else:
                out[key] = value
        return out
    return overlay


def detect_qmd(command: str, timeout_seconds: int) -> Tuple[bool, str]:
    resolved = shutil.which(command)
    if not resolved:
        return False, "binary_not_found"
    try:
        proc = subprocess.run(
            [resolved, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 1),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"version_check_failed:{exc.__class__.__name__}"

    if proc.returncode != 0:
        return False, f"version_check_exit_{proc.returncode}"

    version = (proc.stdout or proc.stderr).strip().splitlines()
    if not version:
        return True, "detected_no_version_output"
    return True, version[0].strip()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def backup_file(path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    shutil.copy2(path, backup)
    return backup


def resolve_profile_paths(profiles_dir: Path) -> Tuple[Path, Path]:
    builtin_profile = profiles_dir / "openclaw.memory-profile.json"
    qmd_profile = profiles_dir / "openclaw.memory-profile.qmd.json"
    if not builtin_profile.exists():
        raise SystemExit(f"missing profile: {builtin_profile}")
    if not qmd_profile.exists():
        raise SystemExit(f"missing profile: {qmd_profile}")
    return builtin_profile, qmd_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument(
        "--profiles-dir",
        default="",
        help="Directory containing openclaw.memory-profile*.json files. Defaults to skill references/profiles.",
    )
    parser.add_argument(
        "--repo-root",
        default="",
        help="Deprecated fallback for older layouts. If set, profiles are loaded from this path.",
    )
    parser.add_argument(
        "--output",
        default="openclaw.memory-profile.selected.json",
        help="Workspace-relative output path for selected profile snapshot.",
    )
    parser.add_argument(
        "--target-config",
        default="",
        help="Optional OpenClaw config file to merge selected profile into (e.g. ~/.openclaw/openclaw.json).",
    )
    parser.add_argument(
        "--force-backend",
        choices=["auto", "builtin", "qmd"],
        default="auto",
        help="Force backend choice or auto-detect qmd availability.",
    )
    parser.add_argument("--qmd-command", default="qmd", help="Command used for qmd detection.")
    parser.add_argument("--qmd-timeout-seconds", type=int, default=4, help="qmd --version timeout.")
    parser.add_argument("--apply", action="store_true", help="Write selected profile output and optional target-config merge.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true", help="Disable backup when writing target-config.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    skill_root = Path(__file__).resolve().parents[1]
    if args.profiles_dir:
        profiles_dir = Path(args.profiles_dir).expanduser().resolve()
    elif args.repo_root:
        profiles_dir = Path(args.repo_root).expanduser().resolve()
    else:
        profiles_dir = (skill_root / "references" / "profiles").resolve()
    builtin_profile, qmd_profile = resolve_profile_paths(profiles_dir)

    qmd_detected = False
    qmd_reason = "not_checked"
    selected_backend = "builtin"

    if args.force_backend == "builtin":
        selected_backend = "builtin"
        qmd_reason = "forced_builtin"
    elif args.force_backend == "qmd":
        selected_backend = "qmd"
        qmd_detected, qmd_reason = detect_qmd(args.qmd_command, args.qmd_timeout_seconds)
    else:
        qmd_detected, qmd_reason = detect_qmd(args.qmd_command, args.qmd_timeout_seconds)
        selected_backend = "qmd" if qmd_detected else "builtin"

    selected_profile_path = qmd_profile if selected_backend == "qmd" else builtin_profile
    selected_profile = load_json(selected_profile_path)

    output_path = (workspace / args.output).resolve()
    if args.apply and not args.dry_run:
        write_json(output_path, selected_profile)

    merged_target = ""
    backup_created = ""
    if args.target_config:
        target_config = Path(args.target_config).expanduser().resolve()
        current: Dict[str, Any] = {}
        if target_config.exists():
            current = load_json(target_config)
        merged = deep_merge(current, selected_profile)
        merged_target = str(target_config)
        if args.apply and not args.dry_run:
            if target_config.exists() and not args.no_backup:
                backup_created = str(backup_file(target_config))
            write_json(target_config, merged)

    payload = {
        "selected_backend": selected_backend,
        "selected_profile": str(selected_profile_path),
        "qmd_detected": qmd_detected,
        "qmd_detection_reason": qmd_reason,
        "workspace": str(workspace),
        "profiles_dir": str(profiles_dir),
        "output_path": str(output_path),
        "target_config": merged_target,
        "backup_created": backup_created,
        "applied": bool(args.apply and not args.dry_run),
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
