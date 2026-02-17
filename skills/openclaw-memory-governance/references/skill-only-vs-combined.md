# Skill-Only vs Combined Deployment

## What can be uploaded as a ClawHub skill

Upload the skill folder contents:

1. `SKILL.md`
2. `agents/openai.yaml`
3. `references/*`
4. `scripts/*` (optional but recommended)

The core requirement is `SKILL.md`; the rest improves repeatability.

## Skill-only mode (no config profile)

Works and remains useful. You still get:

1. layered memory schema discipline
2. cadence scripts (hourly/daily/weekly)
3. transcript mirror + bounded lookup
4. deterministic weekly identity promotion
5. drift classify + soft forgetting
6. confidence-gate response policy + executable gate script

Missing in skill-only mode:

1. OpenClaw-native memory search tuning defaults
2. compaction memory flush prompt hardening
3. session policy defaults (`dmScope`, reset policy)
4. backend profile switch (builtin vs qmd)

## Config-only mode (no skill)

Works and improves runtime defaults, but lacks advanced governance:

1. no importance-based promotions
2. no transcript mirror lifecycle
3. no weekly identity promotion
4. no weekly drift revise/forget logic
5. no confidence-gated transcript suggestion behavior

## Combined mode (recommended)

Use both:

1. Apply `openclaw.memory-profile.json` or `openclaw.memory-profile.qmd.json`.
2. Install this skill and schedule cadence jobs.

This gives stable runtime + long-horizon memory governance.

## Multi-user portability notes

For broad sharing:

1. avoid machine-specific absolute paths in skill docs
2. use `render_schedule.py` to generate local scheduler paths
3. keep scripts limited to workspace and documented OpenClaw session paths

## Packaging for ClawHub upload

Create a bundle:

```bash
./scripts/build_clawhub_bundle.sh
```

This writes `dist/openclaw-memory-governance.zip` under the skill directory.
