---
name: openclaw-memory-governance
description: Enforce upgrade-safe OpenClaw memory operations with a strict config-vs-skill split. Use when setting up or running layered memory (identity/semantic/episodic), transcript lookup, confidence-gated recall suggestions, and weekly drift revise/forget workflows without patching OpenClaw core internals.
---

# OpenClaw Memory Governance

Keep OpenClaw runtime behavior in config and implement cadence logic in this skill package.

## Apply Config-Only Profile

1. Use `openclaw.memory-profile.json` in your OpenClaw workspace root for builtin memory search.
2. Use `openclaw.memory-profile.qmd.json` in your OpenClaw workspace root when `memory.backend = "qmd"` is required.
3. Keep config-only scope limited to documented keys:
- `agents.defaults.compaction.memoryFlush`
- `agents.defaults.memorySearch.*`
- `memory.citations`, `memory.backend`, `memory.qmd.*`
- `session.*`

Never move cadence logic into OpenClaw core config keys that do not exist upstream.

## Required Memory Layout

Enforce this workspace layout:

1. `memory/episodic/YYYY-MM-DD.md`
2. `memory/semantic/YYYY-MM.md`
3. `memory/identity/identity.md`
4. `memory/identity/preferences.md`
5. `memory/identity/decisions.md`
6. `archive/transcripts/YYYY-MM-DD.md`
7. `memory/drift-log.md`

Keep transcript files out of default semantic retrieval. Use transcript lookup only on demand.

## Entry Schema

Write entries using this contract:

```md
### mem:<uuid>
time: <ISO-8601>
layer: identity|semantic|episodic
importance: <0.00-1.00>
confidence: <0.00-1.00>
status: active|refined|historical
source: session:<key>|job:<name>
tags: [tag1, tag2]
supersedes: mem:<uuid>|none
---
<memory statement>
```

## Cadence Operations

Run these scripts from `scripts/` with `--workspace <path>`:

1. `importance_score.py`
- Re-score episodic/semantic memories using 5 signals:
  - goal relevance
  - recurrence
  - future utility
  - preference signal
  - novelty
- Canonicalize noisy concept/tag aliases from `memory/config/concept_aliases.json`.
- Bound per-run workload with `--max-updates` to avoid compute creep.

2. `hourly_semantic_extract.py`
- Promote episodic entries with `importance >= 0.60` into semantic candidates.
- Do not modify OpenClaw indexes directly.

3. `daily_consolidate.py`
- Consolidate duplicate semantic entries.
- Prune episodic files older than retention.
- Build and rotate 7-day transcript mirror at `archive/transcripts`.
- Default transcript mode is `sanitized`:
  - redact likely secrets before write
  - set transcript file permissions to `0600`
- Refuse transcript roots under `memory/` unless explicitly overridden.
- Refuse transcript roots outside workspace unless explicitly overridden.
- Optional high-security mode: `--transcript-mode off` removes mirror files.

4. `weekly_identity_promote.py`
- Promote recurring semantic facts into identity files.
- Route using fixed taxonomy:
  - `preferences.md` for preference/style tags
  - `decisions.md` for decision/policy tags
  - `identity.md` for all other durable truths
- Default thresholds: `importance >= 0.85` and `recurrence >= 3` in 30 days.
- Guard against over-promotion:
  - require recurrence across multiple days
  - require minimum evidence age
  - skip transient/expired memories
  - bound processed groups with `--max-groups`

5. `weekly_drift_review.py`
- Classify new-vs-existing semantic memories as `REINFORCES`, `REFINES`, `SUPERSEDES`, `UNRELATED`.
- Mark superseded entries `historical` without deletion.
- Append actions to `memory/drift-log.md`.

6. `transcript_lookup.py`
- Return bounded transcript excerpts for user-approved lookups.
- Never inject full transcript files.
- Redact likely secrets in lookup output.
- Ignore symlink transcript files.

7. `confidence_gate.py`
- Evaluate retrieval confidence before final answer.
- Return JSON action:
  - `respond_normally`
  - `partial_and_ask_lookup`

8. `confidence_gate_flow.py`
- Execute confidence gate + lookup decision path in one step.
- If confidence is weak and lookup is not approved, returns ask-lookup action.
- If lookup is approved, performs bounded `transcript_lookup` and returns excerpts.

9. `render_schedule.py`
- Print crontab entries and optionally generate launchd plists.
- Use this to install routine hourly/daily/weekly cadence jobs.

10. `session_hygiene.py`
- Harden OpenClaw session storage (`~/.openclaw/agents/<id>/sessions` by default).
- Apply permissions (`0700` dir, `0600` files).
- Redact likely secrets in stale JSONL transcript lines.
- Prune old JSONL files by retention window and clean stale `sessions.json` entries.

Cadence safety:

1. Cadence jobs use non-blocking lock files to avoid overlap.
2. If a lock is held, scripts exit with `skipped=lock_held`.
3. Memory writes use atomic replace operations.

## Confidence Gate Behavior

When recall is weak, suggest transcript lookup instead of guessing.

Use thresholds:

1. weak similarity: `< 0.72`
2. sparse retrieval: `< 5` matches
3. low confidence: `< 0.65`

When low confidence is detected, ask permission:
"I may be missing specifics. Want me to check transcripts for the last 7 days?"

Executable flow command:

`confidence_gate_flow.py --workspace "<workspace>" --avg-similarity <v> --result-count <n> --retrieval-confidence <v> --continuation-intent true|false --lookup-approved true|false --topic "<topic>"`

Identity recall priority within identity layer:

1. `identity.md`
2. `preferences.md`
3. `decisions.md`

## Hard Boundary

Do not:

1. patch OpenClaw compaction/pruning/index internals
2. alter gateway session store formats
3. fork memory plugins for cadence logic
4. auto-mix transcript mirror into normal retrieval

## Recency Guardrail

When applying recency decay in any scorer/ranker:

1. treat `durability: foundational` memories as decay-exempt
2. apply slower decay to `durability: project-stable`
3. keep `status: historical` down-ranked even when durability is high

## Validation

Run:

1. `python3 scripts/smoke_suite.py`
2. `python3 scripts/quick_validate_local.py`
3. Optional (if `pyyaml` is installed): `python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py <path-to-skill-dir>`

Use smoke results to verify:

1. identity -> semantic -> episodic retrieval ordering remains possible
2. transcript mirror lives under `archive/transcripts`
3. transcript lookup is bounded and redacted
4. superseded memories are down-ranked to `historical`
5. identity promotion writes to the correct destination files

## References

Read:

1. `references/scheduling-and-rollout.md` for cron/launchd setup and heartbeat policy.
2. `references/skill-only-vs-combined.md` for what the skill includes, excludes, and how to combine with config profiles.
