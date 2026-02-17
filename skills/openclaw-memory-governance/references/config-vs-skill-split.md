# Config vs Skill Split

## Config-only

Use OpenClaw documented configuration only:

1. Memory backend selection (`memory.backend`, `memory.qmd.*`)
2. Memory search tuning (`agents.defaults.memorySearch.*`)
3. Compaction memory flush (`agents.defaults.compaction.memoryFlush`)
4. Session isolation and reset policy (`session.*`)
5. Citation behavior (`memory.citations`)
6. Memory index path scope (`memorySearch.extraPaths`, `memory.qmd.paths`)

## Needs-skill logic

Implement as scripts and prompts in this skill package:

1. Layered entry schema enforcement
2. Importance scoring and routing
3. Hourly semantic extraction
4. Daily consolidation and pruning
5. Weekly identity promotion
6. Weekly drift classification and soft forgetting
7. 7-day transcript mirror generation in archive root
8. On-demand transcript lookup tool behavior
9. Confidence-gated recall suggestions
10. Transcript privacy controls (`--transcript-mode sanitized|full|off`, lookup redaction)

## Hard boundary

Do not patch or fork OpenClaw core internals for memory cadence logic.
