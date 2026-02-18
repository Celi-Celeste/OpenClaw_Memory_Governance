# Operations

## Critical: Activation Is Required

Installing from ClawHub does not execute these jobs automatically.  
If cron/launchd entries are not installed, the memory governance system remains idle.

Recommended activation command:

`activate.py --workspace "~/.openclaw/workspace" --target-config "~/.openclaw/openclaw.json"`

If qmd is installed later, rerun:

`activate.py --workspace "~/.openclaw/workspace" --target-config "~/.openclaw/openclaw.json" --force-bootstrap`

Activation runs `governance_doctor.py --mode quick` automatically.

Run full health audit:

`governance_doctor.py --workspace "~/.openclaw/workspace" --target-config "~/.openclaw/openclaw.json" --mode full`

Apply safe self-heal fixes during audit:

`governance_doctor.py --workspace "~/.openclaw/workspace" --target-config "~/.openclaw/openclaw.json" --mode full --fix`

## Cadence Jobs

1. Hourly: `hourly_semantic_extract.py`
2. Hourly: `importance_score.py`
3. Daily: `daily_consolidate.py`
4. Weekly: `weekly_identity_promote.py`
5. Weekly: `weekly_drift_review.py`
6. Daily: `session_hygiene.py`
7. Daily (one-time effect): `bootstrap_profile_once.py`

## Backend Profile Selection

Use:

`select_memory_profile.py --workspace "<workspace>" --target-config "~/.openclaw/openclaw.json" --apply`

Behavior:

1. Detects whether `qmd` is available (`qmd --version`)
2. Selects qmd profile if detected, otherwise builtin profile
3. Writes `openclaw.memory-profile.selected.json` in workspace
4. Optionally merges selected profile into target OpenClaw config

Bootstrap mode (recommended for routine rollout):

`bootstrap_profile_once.py --workspace "<workspace>" --target-config "~/.openclaw/openclaw.json"`

1. First run applies backend selection and writes `memory/state/profile-bootstrap.json`
2. Later runs exit quickly with `status=skipped` unless `--force` is provided

Default transcript mirror root:

`archive/transcripts/`

Default transcript mode:

`sanitized`

Daily command example:

`daily_consolidate.py --workspace "<workspace>" --agent-id main --transcript-root archive/transcripts --transcript-mode sanitized`

Optional high-security mode:

`daily_consolidate.py --workspace "<workspace>" --agent-id main --transcript-root archive/transcripts --transcript-mode off`

Risky override acknowledgment:

`daily_consolidate.py` requires `--acknowledge-transcript-risk` for:
1. `--transcript-mode full`
2. `--allow-external-transcript-root`
3. `--allow-transcripts-under-memory`

## Transcript Lookup

Use:

`transcript_lookup.py --transcript-root archive/transcripts --topic "<topic>" --last-n-days 7 --max-excerpts 5`

Behavior:

1. Searches transcript mirror files only
2. Ignores symlink transcript files
3. Returns bounded excerpts with secret redaction
4. Avoids context flooding

## Confidence Gate Policy

When retrieval confidence is weak:

1. Run `confidence_gate.py` with retrieval metrics
2. Return `partial_and_ask_lookup` for low-confidence cases
3. Ask user permission before transcript retrieval
4. Avoid guessed specifics

Executable flow command (recommended):

`confidence_gate_flow.py --workspace "<workspace>" --avg-similarity <v> --result-count <n> --retrieval-confidence <v> --continuation-intent true|false --lookup-approved true|false --topic "<topic>"`

Flow behavior:

1. High confidence: returns `respond_normally`
2. Low confidence + not approved: returns `partial_and_ask_lookup` with user prompt
3. Low confidence + approved: performs bounded transcript lookup and returns excerpts

## Ordered Memory Recall

Use:

`ordered_recall.py --workspace "<workspace>" --topic "<topic>" --max-results 12 --max-per-layer 4`

Behavior:

1. Enforces layer order: `identity -> semantic -> episodic`
2. Enforces identity file order: `identity.md -> preferences.md -> decisions.md`
3. Keeps transcript archives out of normal recall
4. Returns deterministic JSON excerpts for wrapper/tool usage

## Importance Scoring (Items 1 + 5)

Use:

`importance_score.py --workspace "<workspace>" --window-days 30 --max-updates 400`

Behavior:

1. Applies 5-signal weighted scoring to episodic/semantic entries
2. Canonicalizes noisy aliases via `memory/config/concept_aliases.json`
3. Updates `importance` with smoothing (`alpha`) and durability-aware recency policy
4. Caps per-run updates to avoid compute creep

Alias file example:

```json
{
  "governance thing": "openclaw memory governance",
  "the project": "openclaw memory governance"
}
```

## Identity Promotion Guardrail (Item 2)

`weekly_identity_promote.py` now avoids over-promotion by requiring:

1. recurrence and distinct-day spread
2. minimum evidence age
3. non-transient durability
4. non-expired validity window

## Upgrade Checklist

After each OpenClaw update:

1. Re-run smoke suite
2. Confirm retrieval ordering policy still applies (`identity -> semantic -> episodic`)
3. Confirm transcript mirror remains under `archive/transcripts/`
4. Confirm transcript lookup still returns bounded excerpts
5. Confirm weekly identity promotion routes to `identity.md`, `preferences.md`, and `decisions.md`
6. Confirm weekly drift marks superseded entries `historical`
7. Confirm `session_hygiene.py` still applies permissions and retention to session JSONL logs
8. Confirm `ordered_recall.py` still returns identity-first results

## Session Hygiene (Point 3)

Use:

`session_hygiene.py --agent-id main --retention-days 30 --skip-recent-minutes 30`

Behavior:

1. Applies `0700` permissions to sessions directory
2. Applies `0600` permissions to `sessions.json` and `*.jsonl`
3. Redacts likely secrets in non-recent JSONL content
4. Prunes stale JSONL logs by retention window
5. Removes stale entries from `sessions.json` when session files no longer exist

## Cadence Safety

Cadence scripts use non-blocking lock files to prevent overlap.

1. If a cadence lock is already held, the new run exits with `skipped=lock_held`
2. Memory file writes use atomic replace semantics to avoid partial file corruption

## Recency Policy (Point 2 Guardrail)

When weighted scoring is enabled:

1. `foundational` durability entries are exempt from normal recency decay
2. `project-stable` entries decay slower than transient entries
3. superseded entries still drop to `historical` regardless of durability
