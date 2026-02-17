# Installation

## Prerequisites

1. OpenClaw installed and running
2. Python 3.9+
3. Project venv (recommended)

## 1) Install Skill Package

Upload this bundle to ClawHub:

`/Users/celeste/Documents/New project/skills/openclaw-memory-governance/dist/openclaw-memory-governance.zip`

If your ClawHub instance requires raw files, upload the skill directory contents instead.

## 2) Apply Config Profile (Recommended)

Choose one profile:

1. Builtin search:
   - `/Users/celeste/Documents/New project/openclaw.memory-profile.json`
2. QMD backend:
   - `/Users/celeste/Documents/New project/openclaw.memory-profile.qmd.json`

Merge the selected profile into your OpenClaw config (`~/.openclaw/openclaw.json`).

## 3) Configure Cadence Jobs

Generate schedule commands:

```bash
cd "/Users/celeste/Documents/New project/skills/openclaw-memory-governance/scripts"
python3 render_schedule.py --workspace "$HOME/.openclaw/workspace" --agent-id main
```

Install the generated cron lines in `crontab -e`, or generate launchd plists.

## 4) Validate

```bash
cd "/Users/celeste/Documents/New project"
source .venv/bin/activate
python3 skills/openclaw-memory-governance/scripts/smoke_suite.py
python3 skills/openclaw-memory-governance/scripts/quick_validate_local.py
```

