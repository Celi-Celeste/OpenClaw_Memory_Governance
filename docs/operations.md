# Operations

## Cadence Jobs

1. Hourly: `hourly_semantic_extract.py`
2. Daily: `daily_consolidate.py`
3. Weekly: `weekly_identity_promote.py`
4. Weekly: `weekly_drift_review.py`

Default transcript mirror root:

`archive/transcripts/`

## Transcript Lookup

Use:

`transcript_lookup.py --transcript-root archive/transcripts --topic "<topic>" --last-n-days 7 --max-excerpts 5`

Behavior:

1. Searches transcript mirror files only
2. Returns bounded excerpts
3. Avoids context flooding

## Confidence Gate Policy

When retrieval confidence is weak:

1. Run `confidence_gate.py` with retrieval metrics
2. Return `partial_and_ask_lookup` for low-confidence cases
3. Ask user permission before transcript retrieval
4. Avoid guessed specifics

## Upgrade Checklist

After each OpenClaw update:

1. Re-run smoke suite
2. Confirm retrieval ordering policy still applies (`identity -> semantic -> episodic`)
3. Confirm transcript mirror remains under `archive/transcripts/`
4. Confirm transcript lookup still returns bounded excerpts
5. Confirm weekly identity promotion routes to `identity.md`, `preferences.md`, and `decisions.md`
6. Confirm weekly drift marks superseded entries `historical`
