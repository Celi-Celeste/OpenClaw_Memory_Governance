#!/usr/bin/env python3
"""Run backend profile selection once, then mark complete."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from memory_lib import atomic_write_text, ensure_workspace_layout, is_under_root
from select_memory_profile import detect_qmd, load_json, resolve_profile_paths, write_json


def deep_merge(base, overlay):
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            if key in out:
                out[key] = deep_merge(out[key], value)
            else:
                out[key] = value
        return out
    return overlay


def now_z() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument(
        "--profiles-dir",
        default="",
        help="Directory containing openclaw.memory-profile*.json files. Defaults to skill references/profiles.",
    )
    parser.add_argument("--target-config", default="~/.openclaw/openclaw.json", help="OpenClaw config to merge selected profile into.")
    parser.add_argument("--state-file", default="memory/state/profile-bootstrap.json", help="Workspace-relative bootstrap state file.")
    parser.add_argument("--output", default="openclaw.memory-profile.selected.json", help="Workspace-relative selected profile snapshot.")
    parser.add_argument("--qmd-command", default="qmd", help="Command used for qmd detection.")
    parser.add_argument("--qmd-timeout-seconds", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="Re-run bootstrap even if state file exists.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    ensure_workspace_layout(workspace)
    skill_root = Path(__file__).resolve().parents[1]
    profiles_dir = Path(args.profiles_dir).expanduser().resolve() if args.profiles_dir else (skill_root / "references" / "profiles").resolve()
    builtin_profile, qmd_profile = resolve_profile_paths(profiles_dir)

    state_path = (workspace / args.state_file).resolve()
    if not is_under_root(state_path, workspace):
        raise SystemExit("Refusing state-file outside workspace.")
    if state_path.exists() and not args.force:
        payload = {
            "status": "skipped",
            "reason": "already_bootstrapped",
            "state_file": str(state_path),
        }
        print(json.dumps(payload, indent=2))
        return 0

    qmd_detected, qmd_reason = detect_qmd(args.qmd_command, args.qmd_timeout_seconds)
    selected_backend = "qmd" if qmd_detected else "builtin"
    selected_profile_path = qmd_profile if selected_backend == "qmd" else builtin_profile
    selected_profile = load_json(selected_profile_path)

    output_path = (workspace / args.output).resolve()
    if not is_under_root(output_path, workspace):
        raise SystemExit("Refusing output outside workspace.")
    if not args.dry_run:
        write_json(output_path, selected_profile)

    target_config = Path(args.target_config).expanduser().resolve()
    current_payload = {}
    if target_config.exists():
        current_payload = load_json(target_config)
    merged = deep_merge(current_payload, selected_profile)
    if not args.dry_run:
        write_json(target_config, merged)

    state_payload = {
        "bootstrapped_at": now_z(),
        "selected_backend": selected_backend,
        "selected_profile": str(selected_profile_path),
        "qmd_detected": qmd_detected,
        "qmd_detection_reason": qmd_reason,
        "output_path": str(output_path),
        "target_config": str(target_config),
    }
    if not args.dry_run:
        atomic_write_text(state_path, json.dumps(state_payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": "applied", **state_payload, "dry_run": bool(args.dry_run)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
