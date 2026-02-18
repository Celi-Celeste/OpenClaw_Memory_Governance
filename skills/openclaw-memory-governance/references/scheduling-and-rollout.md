# Scheduling and Rollout

## Scope

This skill package supports routine cadence jobs without modifying OpenClaw core code.

## Critical Activation Requirement

ClawHub install alone does not execute cadence scripts.  
You must install generated scheduler entries (cron/launchd), or this memory governance stack will remain idle.

Recommended first action after install:

`python3 scripts/activate.py`

This single command runs backend bootstrap, installs scheduler entries, and runs a quick doctor health check.

If qmd is installed after initial activation, rerun:

`python3 scripts/activate.py --force-bootstrap`

Optional deep health audit:

`python3 scripts/governance_doctor.py --mode full`

Cadence jobs:

1. Hourly: importance scoring + concept normalization
2. Hourly: semantic extraction
3. Daily: one-time backend bootstrap check (`bootstrap_profile_once.py`)
4. Daily: consolidation + transcript mirror rotation
5. Daily: session hygiene for OpenClaw JSONL logs
6. Weekly: identity promotion
7. Weekly: drift review + soft forgetting

## Heartbeat Policy

Use heartbeat as a response policy, not as a heavy background model loop.

Recommended heartbeat behavior:

1. Before answering, retrieve memory in this order: identity -> semantic -> episodic.
2. If confidence is low, suggest transcript lookup and ask permission.
3. Do not auto-load transcript files into normal retrieval.

This keeps runtime stable and avoids context flooding.

Cadence safety:

1. Jobs use non-blocking lock files to avoid overlap.
2. If a lock is held, the script exits with `skipped=lock_held`.

## Crontab Example

Generate machine-specific lines:

```bash
python3 scripts/render_schedule.py --workspace /path/to/workspace --agent-id main
```

Example output (install with `crontab -e`):

```cron
55 2 * * * /usr/bin/env python3 /path/to/skill/scripts/bootstrap_profile_once.py --workspace /path/to/workspace >> /path/to/workspace/memory/logs/bootstrap.log 2>&1
5 * * * * /usr/bin/env python3 /path/to/skill/scripts/importance_score.py --workspace /path/to/workspace --window-days 30 --max-updates 400 >> /path/to/workspace/memory/logs/importance.log 2>&1
0 * * * * /usr/bin/env python3 /path/to/skill/scripts/hourly_semantic_extract.py --workspace /path/to/workspace >> /path/to/workspace/memory/logs/hourly.log 2>&1
10 3 * * * /usr/bin/env python3 /path/to/skill/scripts/daily_consolidate.py --workspace /path/to/workspace --agent-id main --transcript-root archive/transcripts --transcript-mode sanitized >> /path/to/workspace/memory/logs/daily.log 2>&1
40 3 * * * /usr/bin/env python3 /path/to/skill/scripts/session_hygiene.py --agent-id main --retention-days 30 --skip-recent-minutes 30 >> /path/to/workspace/memory/logs/session-hygiene.log 2>&1
10 4 * * 0 /usr/bin/env python3 /path/to/skill/scripts/weekly_identity_promote.py --workspace /path/to/workspace --window-days 30 --min-importance 0.85 --min-recurrence 3 >> /path/to/workspace/memory/logs/weekly-identity.log 2>&1
20 4 * * 0 /usr/bin/env python3 /path/to/skill/scripts/weekly_drift_review.py --workspace /path/to/workspace --window-days 7 >> /path/to/workspace/memory/logs/weekly-drift.log 2>&1
```

Optional high-security daily line:

```cron
10 3 * * * /usr/bin/env python3 /path/to/skill/scripts/daily_consolidate.py --workspace /path/to/workspace --agent-id main --transcript-root archive/transcripts --transcript-mode off >> /path/to/workspace/memory/logs/daily.log 2>&1
```

## launchd Example (macOS)

Generate plists:

```bash
python3 scripts/render_schedule.py \
  --workspace /path/to/workspace \
  --agent-id main \
  --launchd-dir /path/to/output/plists
```

Then load:

```bash
launchctl bootstrap gui/$(id -u) /path/to/output/plists/com.openclaw.memory.hourly.plist
launchctl bootstrap gui/$(id -u) /path/to/output/plists/com.openclaw.memory.bootstrap.plist
launchctl bootstrap gui/$(id -u) /path/to/output/plists/com.openclaw.memory.daily.plist
launchctl bootstrap gui/$(id -u) /path/to/output/plists/com.openclaw.memory.weekly-identity.plist
launchctl bootstrap gui/$(id -u) /path/to/output/plists/com.openclaw.memory.weekly.plist
```

To unload:

```bash
launchctl bootout gui/$(id -u) /path/to/output/plists/com.openclaw.memory.hourly.plist
launchctl bootout gui/$(id -u) /path/to/output/plists/com.openclaw.memory.bootstrap.plist
launchctl bootout gui/$(id -u) /path/to/output/plists/com.openclaw.memory.daily.plist
launchctl bootout gui/$(id -u) /path/to/output/plists/com.openclaw.memory.weekly-identity.plist
launchctl bootout gui/$(id -u) /path/to/output/plists/com.openclaw.memory.weekly.plist
```

## Upgrade-Safe Rollout Process

1. Keep OpenClaw runtime upgrades independent from this skill.
2. After OpenClaw update, run `python3 scripts/smoke_suite.py`.
3. If OpenClaw config keys changed, update only config profiles.
4. If cadence behavior tuning is needed, update only skill scripts.
