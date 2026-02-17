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
5. Weekly drift classification and soft forgetting
6. 7-day transcript mirror generation
7. On-demand transcript lookup tool behavior
8. Confidence-gated recall suggestions

## Hard boundary

Do not patch or fork OpenClaw core internals for memory cadence logic.
