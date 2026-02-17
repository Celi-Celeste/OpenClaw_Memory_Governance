# Memory Entry Schema

All cadence scripts in this skill assume this markdown format:

```md
### mem:<uuid>
time: 2026-02-17T18:40:00Z
layer: episodic|semantic|identity
importance: 0.00-1.00
confidence: 0.00-1.00
status: active|refined|historical
source: session:<key>|job:<name>
tags: [project, preference]
supersedes: mem:<uuid>|none
---
Concise memory statement.
```

## Required metadata keys

1. `time`
2. `layer`
3. `importance`
4. `confidence`
5. `status`
6. `source`
7. `tags`
8. `supersedes`

Unknown metadata keys are preserved by scripts.
