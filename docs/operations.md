# Operations

## Cadence Jobs

1. Hourly: `hourly_semantic_extract.py`
2. Daily: `daily_consolidate.py`
3. Weekly: `weekly_drift_review.py`

## Transcript Lookup

Use:

`transcript_lookup.py --topic "<topic>" --last-n-days 7 --max-excerpts 5`

Behavior:

1. Searches transcript mirror files only
2. Returns bounded excerpts
3. Avoids context flooding

## Confidence Gate Policy

When retrieval confidence is weak:

1. Suggest transcript lookup
2. Ask user permission before retrieval
3. Avoid guessed specifics

## Upgrade Checklist

After each OpenClaw update:

1. Re-run smoke suite
2. Confirm retrieval ordering policy still applies (`identity -> semantic -> episodic`)
3. Confirm transcript lookup still returns bounded excerpts
4. Confirm weekly drift marks superseded entries `historical`

