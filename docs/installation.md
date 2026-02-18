# Installation

## Critical: Activation Is Required

ClawHub install alone is not enough.

Cadence scripts do not run until scheduler jobs are installed (cron or launchd).  
If scheduler setup is skipped, memory governance behavior will not execute.

## Prerequisites

1. OpenClaw installed and running
2. Python 3.9+
3. Project venv (recommended)

## 1) Install Skill Package

Upload this bundle to ClawHub:

`skills/openclaw-memory-governance/dist/openclaw-memory-governance.zip`

If your ClawHub instance requires raw files, upload the skill directory contents instead.

## 2) Apply Config Profile (Recommended)

Recommended one-command activation:

```bash
cd <repo-root>/skills/openclaw-memory-governance/scripts
python3 activate.py
```

If qmd is installed after this first run, rerun activation to re-detect backend and switch profile:

```bash
python3 activate.py --force-bootstrap
```

`activate.py` will:

1. detect qmd availability and select builtin vs qmd profile
2. apply selected profile into `~/.openclaw/openclaw.json`
3. install scheduler jobs (`launchd` on macOS, `cron` elsewhere)
4. run backend bootstrap in one-time marker mode
5. support forced backend re-bootstrap via `--force-bootstrap` when qmd availability changes later
6. run `governance_doctor.py --mode quick` and report health (`ok|warn|fail`)

Optional deep post-install health audit:

```bash
python3 governance_doctor.py --mode full
```

Advanced manual profile control (optional):

1. Builtin search:
   - `openclaw.memory-profile.json`
2. QMD backend:
   - `openclaw.memory-profile.qmd.json`

Merge the selected profile into your OpenClaw config (`~/.openclaw/openclaw.json`) if not using `activate.py`.

## 3) Configure Cadence Jobs

If you used `activate.py`, scheduler setup is already handled.

Manual scheduler setup (optional/advanced):

Generate schedule commands:

```bash
cd <repo-root>/skills/openclaw-memory-governance/scripts
python3 render_schedule.py --workspace "$HOME/.openclaw/workspace" --agent-id main
```

Install the generated cron lines in `crontab -e`, or generate launchd plists.

Notes:

1. Transcript mirror defaults to `archive/transcripts/` (outside `memory/`).
2. Transcript mirror defaults to `--transcript-mode sanitized` (secret redaction + `0600` file permissions).
3. Backend bootstrap check is included in generated schedules (`bootstrap_profile_once.py`).
4. Importance scoring defaults are included in generated schedules (`importance_score.py`).
5. Session hygiene defaults are included in generated schedules (`session_hygiene.py`).
6. Weekly cadence now includes identity promotion before drift review.
7. Risky transcript overrides require `--acknowledge-transcript-risk`:
   - `--transcript-mode full`
   - `--allow-external-transcript-root`
   - `--allow-transcripts-under-memory`

Optional high-security mode:

Set daily job to `--transcript-mode off` to disable transcript mirror files.

## 4) Validate

```bash
cd <repo-root>
source .venv/bin/activate
python3 skills/openclaw-memory-governance/scripts/smoke_suite.py
python3 skills/openclaw-memory-governance/scripts/quick_validate_local.py
python3 scripts/check_docs_links.py
```
