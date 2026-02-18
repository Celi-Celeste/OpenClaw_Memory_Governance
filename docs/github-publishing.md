# GitHub Publishing (First-Time Friendly)

## Critical for Users

If users install this skill from ClawHub, they must still install scheduler jobs (cron/launchd).  
Without scheduler activation, cadence scripts do not run.

Post-install command users should run:

`python3 skills/openclaw-memory-governance/scripts/activate.py`

This command also runs a quick governance doctor health check.

If qmd is installed later, users should rerun:

`python3 skills/openclaw-memory-governance/scripts/activate.py --force-bootstrap`

## 1) Create a GitHub Repository

In your OpenClaw GitHub account:

1. Click **New repository**
2. Name it (example: `openclaw-memory-governance`)
3. Choose Public or Private
4. Do not add a README (this repo already has one)
5. Create repository

## 2) Connect Local Repo

Use the repository URL GitHub gives you:

```bash
cd <repo-root>
git remote add origin <YOUR_GITHUB_REPO_URL>
```

If `origin` already exists:

```bash
git remote set-url origin <YOUR_GITHUB_REPO_URL>
```

## 3) Commit and Push

```bash
cd <repo-root>
git add .
git commit -m "Initial release: OpenClaw memory governance skill + docs"
git push -u origin main
```

If Git asks you to authenticate, sign in using your OpenClaw GitHub account.

## 4) Enable GitHub Pages

This repository includes:

`.github/workflows/pages.yml`

After first push:

1. Open **Settings -> Pages**
2. Set Source to **GitHub Actions**
3. Wait for the **Deploy Docs** workflow to finish

Your docs site will publish from the `docs/` folder via workflow.

## 5) Optional Release Artifact

Skill bundle path:

`skills/openclaw-memory-governance/dist/openclaw-memory-governance.zip`

You can attach this zip to a GitHub Release so users can download and upload directly to ClawHub.
