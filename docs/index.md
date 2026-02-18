# OpenClaw Memory Governance

This project provides a production-friendly memory governance layer for OpenClaw with a strict split:

1. Config-only runtime tuning
2. Skill-only cadence and drift logic

It is designed for teams that want long-horizon memory improvements without forking OpenClaw core.

## Critical Setup Note

ClawHub install copies skill files only.  
You must install scheduler jobs (cron/launchd) for cadence scripts to run.

Recommended activation command after install:

`python3 skills/openclaw-memory-governance/scripts/activate.py`

If qmd is installed later, rerun:

`python3 skills/openclaw-memory-governance/scripts/activate.py --force-bootstrap`

## Start Here

1. [Installation Guide](installation.md)
2. [Operations Guide](operations.md)
3. [Architecture](architecture.md)

## Core Outcomes

1. Better continuity after idle gaps
2. Less stale memory resurfacing
3. Safer recall when details are missing
4. Cleaner maintenance path across OpenClaw updates
