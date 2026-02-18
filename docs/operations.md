# Operations

## Cadence Jobs

1. Hourly: `hourly_semantic_extract.py`
2. Daily: `daily_consolidate.py`
3. Weekly: `weekly_identity_promote.py`
4. Weekly: `weekly_drift_review.py`
5. Daily: `session_hygiene.py`

Default transcript mirror root:

`archive/transcripts/`

Default transcript mode:

`sanitized`

Daily command example:

`daily_consolidate.py --workspace "<workspace>" --agent-id main --transcript-root archive/transcripts --transcript-mode sanitized`

Optional high-security mode:

`daily_consolidate.py --workspace "<workspace>" --agent-id main --transcript-root archive/transcripts --transcript-mode off`

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

## Upgrade Checklist

After each OpenClaw update:

1. Re-run smoke suite
2. Confirm retrieval ordering policy still applies (`identity -> semantic -> episodic`)
3. Confirm transcript mirror remains under `archive/transcripts/`
4. Confirm transcript lookup still returns bounded excerpts
5. Confirm weekly identity promotion routes to `identity.md`, `preferences.md`, and `decisions.md`
6. Confirm weekly drift marks superseded entries `historical`
7. Confirm `session_hygiene.py` still applies permissions and retention to session JSONL logs

## Session Hygiene (Point 3)

Use:

`session_hygiene.py --agent-id main --retention-days 30 --skip-recent-minutes 30`

Behavior:

1. Applies `0700` permissions to sessions directory
2. Applies `0600` permissions to `sessions.json` and `*.jsonl`
3. Redacts likely secrets in non-recent JSONL content
4. Prunes stale JSONL logs by retention window
5. Removes stale entries from `sessions.json` when session files no longer exist
