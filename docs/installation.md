# Installation

## Prerequisites

1. OpenClaw installed and running
2. Python 3.9+
3. Project venv (recommended)

## 1) Install Skill Package

Upload this bundle to ClawHub:

`skills/openclaw-memory-governance/dist/openclaw-memory-governance.zip`

If your ClawHub instance requires raw files, upload the skill directory contents instead.

## 2) Apply Config Profile (Recommended)

Choose one profile:

1. Builtin search:
   - `openclaw.memory-profile.json`
2. QMD backend:
   - `openclaw.memory-profile.qmd.json`

Merge the selected profile into your OpenClaw config (`~/.openclaw/openclaw.json`).

## 3) Configure Cadence Jobs

Generate schedule commands:

```bash
cd <repo-root>/skills/openclaw-memory-governance/scripts
python3 render_schedule.py --workspace "$HOME/.openclaw/workspace" --agent-id main
```

Install the generated cron lines in `crontab -e`, or generate launchd plists.

Notes:

1. Transcript mirror defaults to `archive/transcripts/` (outside `memory/`).
2. Transcript mirror defaults to `--transcript-mode sanitized` (secret redaction + `0600` file permissions).
3. Importance scoring defaults are included in generated schedules (`importance_score.py`).
4. Session hygiene defaults are included in generated schedules (`session_hygiene.py`).
5. Weekly cadence now includes identity promotion before drift review.

Optional high-security mode:

Set daily job to `--transcript-mode off` to disable transcript mirror files.

## 4) Validate

```bash
cd <repo-root>
source .venv/bin/activate
python3 skills/openclaw-memory-governance/scripts/smoke_suite.py
python3 skills/openclaw-memory-governance/scripts/quick_validate_local.py
```
