#!/usr/bin/env python3
"""One-shot activation for OpenClaw Memory Governance."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import List

from render_schedule import cron_lines, write_launchd_plist

CRON_BEGIN = "# >>> OPENCLAW_MEMORY_GOVERNANCE_BEGIN >>>"
CRON_END = "# <<< OPENCLAW_MEMORY_GOVERNANCE_END <<<"


def _run(cmd: List[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc


def _run_bootstrap(
    script_dir: Path,
    workspace: Path,
    target_config: Path,
    qmd_command: str,
    qmd_timeout_seconds: int,
    force_bootstrap: bool,
    dry_run: bool,
) -> dict:
    cmd = [
        sys.executable,
        str(script_dir / "bootstrap_profile_once.py"),
        "--workspace",
        str(workspace),
        "--target-config",
        str(target_config),
        "--qmd-command",
        qmd_command,
        "--qmd-timeout-seconds",
        str(qmd_timeout_seconds),
    ]
    if force_bootstrap:
        cmd.append("--force")
    if dry_run:
        cmd.append("--dry-run")
    proc = _run(cmd, check=True)
    payload = json.loads(proc.stdout)
    return payload


def _run_doctor(
    script_dir: Path,
    workspace: Path,
    target_config: Path,
    agent_id: str,
    launchd_dir: Path,
    qmd_command: str,
    qmd_timeout_seconds: int,
) -> dict:
    cmd = [
        sys.executable,
        str(script_dir / "governance_doctor.py"),
        "--workspace",
        str(workspace),
        "--target-config",
        str(target_config),
        "--agent-id",
        agent_id,
        "--launchd-dir",
        str(launchd_dir),
        "--qmd-command",
        qmd_command,
        "--qmd-timeout-seconds",
        str(qmd_timeout_seconds),
        "--mode",
        "quick",
        "--json",
    ]
    proc = _run(cmd, check=False)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        payload = {
            "status": "fail",
            "error": f"doctor_json_decode_failed:{exc.__class__.__name__}",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    payload["returncode"] = proc.returncode
    return payload


def _install_cron(lines: List[str], dry_run: bool) -> dict:
    existing_proc = _run(["crontab", "-l"], check=False)
    if existing_proc.returncode == 0:
        existing = existing_proc.stdout
    else:
        stderr = (existing_proc.stderr or "").lower()
        if "no crontab" in stderr:
            existing = ""
        else:
            raise RuntimeError(f"unable to read existing crontab: {existing_proc.stderr.strip()}")

    block = "\n".join([CRON_BEGIN, *lines, CRON_END]) + "\n"
    pattern = re.compile(rf"{re.escape(CRON_BEGIN)}[\s\S]*?{re.escape(CRON_END)}\n?", re.MULTILINE)
    without_old = re.sub(pattern, "", existing).rstrip()
    if without_old:
        new_crontab = without_old + "\n\n" + block
    else:
        new_crontab = block

    if not dry_run:
        _run(["crontab", "-"], check=True, input_text=new_crontab)

    return {
        "installed": not dry_run,
        "line_count": len(lines),
        "managed_block": True,
    }


def _generate_launchd(
    workspace: Path,
    scripts_dir: Path,
    launchd_dir: Path,
    agent_id: str,
) -> list[Path]:
    logs_dir = workspace / "memory" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    launchd_dir.mkdir(parents=True, exist_ok=True)

    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.bootstrap.plist",
        "com.openclaw.memory.bootstrap",
        scripts_dir / "bootstrap_profile_once.py",
        workspace,
        logs_dir,
        hour=2,
        minute=55,
        run_at_load=True,
    )
    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.importance.plist",
        "com.openclaw.memory.importance",
        scripts_dir / "importance_score.py",
        workspace,
        logs_dir,
        hour=0,
        minute=5,
        extra_args=["--window-days", "30", "--max-updates", "400"],
    )
    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.hourly.plist",
        "com.openclaw.memory.hourly",
        scripts_dir / "hourly_semantic_extract.py",
        workspace,
        logs_dir,
        hour=0,
        minute=0,
    )
    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.daily.plist",
        "com.openclaw.memory.daily",
        scripts_dir / "daily_consolidate.py",
        workspace,
        logs_dir,
        hour=3,
        minute=10,
        extra_args=[
            "--agent-id",
            agent_id,
            "--transcript-root",
            "archive/transcripts",
            "--transcript-mode",
            "sanitized",
        ],
    )
    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.weekly-identity.plist",
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
        launchd_dir / "com.openclaw.memory.weekly.plist",
        "com.openclaw.memory.weekly",
        scripts_dir / "weekly_drift_review.py",
        workspace,
        logs_dir,
        hour=4,
        minute=20,
        weekday=0,
    )
    write_launchd_plist(
        launchd_dir / "com.openclaw.memory.session-hygiene.plist",
        "com.openclaw.memory.session-hygiene",
        scripts_dir / "session_hygiene.py",
        workspace,
        logs_dir,
        hour=3,
        minute=40,
        extra_args=["--agent-id", agent_id, "--retention-days", "30", "--skip-recent-minutes", "30"],
    )

    return sorted(launchd_dir.glob("com.openclaw.memory*.plist"))


def _install_launchd(plist_paths: list[Path], dry_run: bool) -> dict:
    if platform.system().lower() != "darwin":
        raise RuntimeError("launchd installation is only supported on macOS.")

    domain = f"gui/{os.getuid()}"
    installed = 0
    for plist in plist_paths:
        if not dry_run:
            _run(["launchctl", "bootout", domain, str(plist)], check=False)
            _run(["launchctl", "bootstrap", domain, str(plist)], check=True)
        installed += 1
    return {
        "installed": not dry_run,
        "plist_count": installed,
        "domain": domain,
    }


def _resolve_scheduler(mode: str) -> str:
    if mode != "auto":
        return mode
    if platform.system().lower() == "darwin":
        return "launchd"
    return "cron"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(Path.home() / ".openclaw" / "workspace"))
    parser.add_argument("--agent-id", default="main")
    parser.add_argument("--target-config", default=str(Path.home() / ".openclaw" / "openclaw.json"))
    parser.add_argument("--scheduler", choices=["auto", "cron", "launchd", "none"], default="auto")
    parser.add_argument("--launchd-dir", default=str(Path.home() / ".openclaw" / "memory-plists"))
    parser.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Skip post-activation governance doctor check.",
    )
    parser.add_argument("--qmd-command", default="qmd")
    parser.add_argument("--qmd-timeout-seconds", type=int, default=4)
    parser.add_argument(
        "--force-bootstrap",
        action="store_true",
        help="Force backend re-detection/profile apply even if one-time marker exists.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    workspace = Path(args.workspace).expanduser().resolve()
    target_config = Path(args.target_config).expanduser().resolve()
    launchd_dir = Path(args.launchd_dir).expanduser().resolve()
    scheduler = _resolve_scheduler(args.scheduler)

    bootstrap = _run_bootstrap(
        script_dir=script_dir,
        workspace=workspace,
        target_config=target_config,
        qmd_command=args.qmd_command,
        qmd_timeout_seconds=args.qmd_timeout_seconds,
        force_bootstrap=bool(args.force_bootstrap),
        dry_run=args.dry_run,
    )

    schedule_result: dict = {"scheduler": scheduler, "status": "skipped"}
    lines = cron_lines(workspace=workspace, scripts_dir=script_dir, agent_id=args.agent_id)
    if scheduler == "none":
        schedule_result = {"scheduler": "none", "status": "skipped"}
    elif scheduler == "cron":
        cron_result = _install_cron(lines=lines, dry_run=args.dry_run)
        schedule_result = {"scheduler": "cron", "status": "installed", **cron_result}
    else:
        plists = _generate_launchd(workspace=workspace, scripts_dir=script_dir, launchd_dir=launchd_dir, agent_id=args.agent_id)
        launchd_result = _install_launchd(plist_paths=plists, dry_run=args.dry_run)
        schedule_result = {
            "scheduler": "launchd",
            "status": "installed",
            "launchd_dir": str(launchd_dir),
            **launchd_result,
        }

    doctor_result: dict
    if args.skip_doctor:
        doctor_result = {"status": "skipped", "reason": "skip_doctor"}
    elif args.dry_run:
        doctor_result = {"status": "skipped", "reason": "dry_run"}
    else:
        doctor_result = _run_doctor(
            script_dir=script_dir,
            workspace=workspace,
            target_config=target_config,
            agent_id=args.agent_id,
            launchd_dir=launchd_dir,
            qmd_command=args.qmd_command,
            qmd_timeout_seconds=args.qmd_timeout_seconds,
        )

    overall_status = "ok"
    if doctor_result.get("status") == "fail":
        overall_status = "fail"

    payload = {
        "status": overall_status,
        "workspace": str(workspace),
        "target_config": str(target_config),
        "bootstrap": bootstrap,
        "force_bootstrap": bool(args.force_bootstrap),
        "scheduler": schedule_result,
        "doctor": doctor_result,
        "dry_run": bool(args.dry_run),
    }
    print(json.dumps(payload, indent=2))
    if overall_status == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
