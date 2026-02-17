# OpenClaw Memory Governance Skill

Upgrade-safe memory governance for OpenClaw, built as a **skill + config profile split** so you can keep using upstream OpenClaw updates without maintaining a core fork.

## What This Project Does

This project adds operational memory governance on top of OpenClaw:

1. Layered memory workflow: `identity -> semantic -> episodic`
2. Cadence jobs:
   - Hourly semantic extraction
   - Daily consolidation + transcript mirror rotation
   - Weekly identity promotion
   - Weekly drift review with soft supersede (`historical` status)
3. On-demand transcript recall (bounded excerpts, not full transcript dumps)
4. Confidence-gated behavior for weak recall scenarios

## Why This Is Upgrade-Safe

It keeps a strict boundary:

1. **Config-only** behavior stays in OpenClaw documented keys.
2. **Skill logic** (cadence, drift, transcript tooling) stays in scripts.
3. No patching OpenClaw compaction, pruning, or memory internals.

## Repository Layout

```text
openclaw.memory-profile.json
openclaw.memory-profile.qmd.json
skills/openclaw-memory-governance/
  SKILL.md
  agents/openai.yaml
  references/
  scripts/
  dist/openclaw-memory-governance.zip
docs/
  index.md
  installation.md
  operations.md
  architecture.md
  github-publishing.md
```

## Install Modes

### 1) Skill-only (works)

Install the skill package and run cadence scripts.  
You get memory governance features without changing OpenClaw config defaults.

### 2) Config-only (works)

Apply config profile only.  
You get runtime tuning defaults, but no cadence governance automation.

### 3) Combined (recommended)

Apply one config profile **and** install the skill package.

## Quick Start

### A) Validate locally

```bash
cd <repo-root>
source .venv/bin/activate
python3 skills/openclaw-memory-governance/scripts/smoke_suite.py
python3 skills/openclaw-memory-governance/scripts/quick_validate_local.py
```

### B) Build upload bundle for ClawHub

```bash
cd <repo-root>/skills/openclaw-memory-governance
./scripts/build_clawhub_bundle.sh
```

Bundle output:

`skills/openclaw-memory-governance/dist/openclaw-memory-governance.zip`

### C) Generate scheduler commands

```bash
cd <repo-root>/skills/openclaw-memory-governance/scripts
python3 render_schedule.py --workspace "$HOME/.openclaw/workspace" --agent-id main
```

Default transcript mirror root is `archive/transcripts/` so transcript precision recall stays outside default memory indexing.

Optional macOS launchd plist generation:

```bash
python3 render_schedule.py \
  --workspace "$HOME/.openclaw/workspace" \
  --agent-id main \
  --launchd-dir "$HOME/.openclaw/memory-plists"
```

## GitHub Publishing

This repo is ready for GitHub publishing. If your GitHub repo already exists:

```bash
cd <repo-root>
git add .
git commit -m "Initial release: OpenClaw memory governance skill + docs"
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

If `origin` already exists, use:

```bash
git remote set-url origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

Detailed first-time publishing steps:

`docs/github-publishing.md`

## Documentation Site (GitHub Pages)

A Pages workflow is included at:

`.github/workflows/pages.yml`

After pushing to GitHub:

1. Open repo **Settings -> Pages**
2. Set Source to **GitHub Actions**
3. Push to `main` (or rerun the Pages workflow)

Docs entrypoint:

`docs/index.md`

## License

This repository currently uses the MIT license (`LICENSE`).
