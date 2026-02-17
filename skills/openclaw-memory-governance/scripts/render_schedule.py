#!/usr/bin/env python3
"""Render cron lines and optional launchd plists for cadence jobs."""

from __future__ import annotations

import argparse
import plistlib
import shlex
from pathlib import Path


def cron_lines(workspace: Path, scripts_dir: Path, agent_id: str) -> list[str]:
    logs = workspace / "memory" / "logs"
    q = shlex.quote
    lines = [
        f"0 * * * * /usr/bin/env python3 {q(str(scripts_dir / 'hourly_semantic_extract.py'))} --workspace {q(str(workspace))} >> {q(str(logs / 'hourly.log'))} 2>&1",
        (
            "10 3 * * * /usr/bin/env python3 "
            f"{q(str(scripts_dir / 'daily_consolidate.py'))} "
            f"--workspace {q(str(workspace))} "
            f"--agent-id {q(agent_id)} "
            "--transcript-root archive/transcripts "
            "--transcript-mode sanitized "
            f">> {q(str(logs / 'daily.log'))} 2>&1"
        ),
        (
            "10 4 * * 0 /usr/bin/env python3 "
            f"{q(str(scripts_dir / 'weekly_identity_promote.py'))} "
            f"--workspace {q(str(workspace))} "
            "--window-days 30 --min-importance 0.85 --min-recurrence 3 "
            f">> {q(str(logs / 'weekly-identity.log'))} 2>&1"
        ),
        (
            "20 4 * * 0 /usr/bin/env python3 "
            f"{q(str(scripts_dir / 'weekly_drift_review.py'))} "
            f"--workspace {q(str(workspace))} "
            "--window-days 7 "
            f">> {q(str(logs / 'weekly-drift.log'))} 2>&1"
        ),
    ]
    return lines


def write_launchd_plist(
    out_path: Path,
    label: str,
    script_path: Path,
    workspace: Path,
    logs_dir: Path,
    hour: int,
    minute: int,
    weekday: int | None = None,
    extra_args: list[str] | None = None,
) -> None:
    args = ["/usr/bin/env", "python3", str(script_path), "--workspace", str(workspace)]
    if extra_args:
        args.extend(extra_args)
    payload = {
        "Label": label,
        "ProgramArguments": args,
        "RunAtLoad": False,
        "StandardOutPath": str(logs_dir / f"{label}.out.log"),
        "StandardErrorPath": str(logs_dir / f"{label}.err.log"),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
    }
    if weekday is not None:
        payload["StartCalendarInterval"]["Weekday"] = weekday
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        plistlib.dump(payload, fh)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="OpenClaw workspace root.")
    parser.add_argument("--agent-id", default="main", help="OpenClaw agent id for daily transcript mirror.")
    parser.add_argument("--launchd-dir", default="", help="Optional output directory for launchd plist files.")
    args = parser.parse_args()

    scripts_dir = Path(__file__).resolve().parent
    workspace = Path(args.workspace).expanduser().resolve()
    logs_dir = workspace / "memory" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print("# crontab entries")
    for line in cron_lines(workspace, scripts_dir, agent_id=args.agent_id):
        print(line)

    if args.launchd_dir:
        out = Path(args.launchd_dir).expanduser().resolve()
        write_launchd_plist(
            out / "com.openclaw.memory.hourly.plist",
            "com.openclaw.memory.hourly",
            scripts_dir / "hourly_semantic_extract.py",
            workspace,
            logs_dir,
            hour=0,
            minute=0,
        )
        write_launchd_plist(
            out / "com.openclaw.memory.daily.plist",
            "com.openclaw.memory.daily",
            scripts_dir / "daily_consolidate.py",
            workspace,
            logs_dir,
            hour=3,
            minute=10,
            extra_args=[
                "--agent-id",
                args.agent_id,
                "--transcript-root",
                "archive/transcripts",
                "--transcript-mode",
                "sanitized",
            ],
        )
        write_launchd_plist(
            out / "com.openclaw.memory.weekly-identity.plist",
            "com.openclaw.memory.weekly-identity",
            scripts_dir / "weekly_identity_promote.py",
            workspace,
            logs_dir,
            hour=4,
            minute=10,
            weekday=0,
            extra_args=["--window-days", "30", "--min-importance", "0.85", "--min-recurrence", "3"],
        )
        write_launchd_plist(
            out / "com.openclaw.memory.weekly.plist",
            "com.openclaw.memory.weekly",
            scripts_dir / "weekly_drift_review.py",
            workspace,
            logs_dir,
            hour=4,
            minute=20,
            weekday=0,
        )
        print(f"# launchd plists generated in {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
