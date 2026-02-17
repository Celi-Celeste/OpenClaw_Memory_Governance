#!/usr/bin/env python3
"""Smoke tests for the openclaw-memory-governance scripts."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
from pathlib import Path

from memory_lib import write_memory_file


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def run_maybe_fail(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True, text=True)


def make_entry(
    entry_id: str,
    layer: str,
    body: str,
    importance: float,
    status: str = "active",
    timestamp: str | None = None,
) -> dict:
    return {
        "entry_id": entry_id,
        "meta": {
            "time": timestamp
            or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "layer": layer,
            "importance": f"{importance:.2f}",
            "confidence": "0.80",
            "status": status,
            "source": "session:test",
            "tags": "['project']",
            "supersedes": "none",
        },
        "body": body,
    }


def write_entries(path: Path, entries: list[dict]) -> None:
    from memory_lib import MemoryEntry

    mem_entries = [
        MemoryEntry(entry_id=e["entry_id"], meta=e["meta"], body=e["body"])
        for e in entries
    ]
    write_memory_file(path, "", mem_entries)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[2]
    qmd_profile = repo_root / "openclaw.memory-profile.qmd.json"
    profile_obj = json.loads(qmd_profile.read_text(encoding="utf-8"))
    qmd_cfg = profile_obj.get("memory", {}).get("qmd", {})
    paths_cfg = qmd_cfg.get("paths", [])
    assert not any(p.get("path") == "./memory" for p in paths_cfg), "qmd profile should not duplicate-index ./memory"

    with tempfile.TemporaryDirectory(prefix="oc-mem-smoke-") as td:
        workspace = Path(td)
        (workspace / "memory" / "episodic").mkdir(parents=True, exist_ok=True)
        (workspace / "memory" / "semantic").mkdir(parents=True, exist_ok=True)
        (workspace / "memory" / "transcripts").mkdir(parents=True, exist_ok=True)
        (workspace / "archive" / "transcripts").mkdir(parents=True, exist_ok=True)
        sessions_dir = workspace / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        today = dt.date.today()
        epi = workspace / "memory" / "episodic" / f"{today.isoformat()}.md"
        write_entries(
            epi,
            [
                make_entry("e1", "episodic", "User prefers local-first architecture for OpenClaw memory.", 0.82),
                make_entry("e2", "episodic", "One-off minor joke.", 0.20),
            ],
        )

        run(
            [
                "python3",
                str(script_dir / "hourly_semantic_extract.py"),
                "--workspace",
                str(workspace),
            ],
            cwd=script_dir,
        )
        sem = workspace / "memory" / "semantic" / today.strftime("%Y-%m.md")
        assert sem.exists(), "hourly job failed to create semantic file"
        sem_text = sem.read_text(encoding="utf-8")
        assert "Derived from mem:e1" in sem_text, "semantic promotion missing expected entry"

        # Add contradictory semantic entries for drift review.
        old_ts = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        write_entries(
            sem,
            [
                make_entry(
                    "old1",
                    "semantic",
                    "Use local-only model routing for all high-level reasoning.",
                    0.90,
                    timestamp=old_ts,
                ),
                make_entry("new1", "semantic", "No longer use local-only model routing; switched to hybrid cloud for high-level reasoning.", 0.92),
            ],
        )
        run(
            [
                "python3",
                str(script_dir / "weekly_drift_review.py"),
                "--workspace",
                str(workspace),
                "--window-days",
                "7",
            ],
            cwd=script_dir,
        )
        reviewed = sem.read_text(encoding="utf-8")
        assert "status: historical" in reviewed, "weekly drift review did not mark superseded entry historical"

        # Seed session transcript for daily mirror build.
        event = {
            "timestamp": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "role": "user",
            "content": "Please revisit memory cadence and transcript lookup details.",
        }
        (sessions_dir / "session-a.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        legacy_day = today - dt.timedelta(days=1)
        legacy_transcript = workspace / "memory" / "transcripts" / f"{legacy_day.isoformat()}.md"
        legacy_transcript.write_text(
            f"# {legacy_day.isoformat()}\n\n## 09:00:00 - user (legacy)\nlegacy transcript entry\n",
            encoding="utf-8",
        )

        guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "memory/transcripts",
            ],
            cwd=script_dir,
        )
        assert guard.returncode != 0, "daily transcript root guard failed to block memory/transcripts"
        run(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--sessions-dir",
                str(sessions_dir),
                "--transcript-root",
                "archive/transcripts",
                "--episodic-retention-days",
                "14",
                "--transcript-retention-days",
                "7",
            ],
            cwd=script_dir,
        )

        transcript_root = workspace / "archive" / "transcripts"
        transcript = transcript_root / f"{today.isoformat()}.md"
        assert transcript.exists(), "daily transcript mirror not created in archive/transcripts"
        assert (transcript_root / f"{legacy_day.isoformat()}.md").exists(), "legacy transcript was not migrated"
        assert not legacy_transcript.exists(), "legacy transcript file was not moved"

        lookup = run(
            [
                "python3",
                str(script_dir / "transcript_lookup.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "archive/transcripts",
                "--topic",
                "memory cadence",
                "--last-n-days",
                "7",
                "--max-excerpts",
                "5",
            ],
            cwd=script_dir,
        )
        parsed = json.loads(lookup.stdout)
        assert parsed["results"], "transcript lookup returned no results"

        low_conf = run(
            [
                "python3",
                str(script_dir / "confidence_gate.py"),
                "--avg-similarity",
                "0.55",
                "--result-count",
                "2",
                "--retrieval-confidence",
                "0.58",
                "--continuation-intent",
                "true",
            ],
            cwd=script_dir,
        )
        low_payload = json.loads(low_conf.stdout)
        assert low_payload["action"] == "partial_and_ask_lookup", "confidence gate low-signal action mismatch"

        high_conf = run(
            [
                "python3",
                str(script_dir / "confidence_gate.py"),
                "--avg-similarity",
                "0.89",
                "--result-count",
                "10",
                "--retrieval-confidence",
                "0.86",
                "--continuation-intent",
                "false",
            ],
            cwd=script_dir,
        )
        high_payload = json.loads(high_conf.stdout)
        assert high_payload["action"] == "respond_normally", "confidence gate high-signal action mismatch"

        # Seed recurring semantic entries for identity promotion.
        sem_promote = workspace / "memory" / "semantic" / today.strftime("%Y-%m.md")
        base_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
        promote_entries = []
        for idx in range(3):
            ts = (base_ts + dt.timedelta(hours=idx)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            promote_entries.append(make_entry(f"pref{idx}", "semantic", "User prefers concise status updates for memory review.", 0.92, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['preference']"
            promote_entries.append(make_entry(f"dec{idx}", "semantic", "Decision: keep OpenClaw memory governance skill-first and avoid core patching.", 0.94, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['decision']"
            promote_entries.append(make_entry(f"id{idx}", "semantic", "Core identity truth: project focus is reliable OpenClaw memory continuity.", 0.91, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['project']"
        write_entries(sem_promote, promote_entries)

        run(
            [
                "python3",
                str(script_dir / "weekly_identity_promote.py"),
                "--workspace",
                str(workspace),
                "--window-days",
                "30",
                "--min-importance",
                "0.85",
                "--min-recurrence",
                "3",
            ],
            cwd=script_dir,
        )
        identity_text = (workspace / "memory" / "identity" / "identity.md").read_text(encoding="utf-8")
        preferences_text = (workspace / "memory" / "identity" / "preferences.md").read_text(encoding="utf-8")
        decisions_text = (workspace / "memory" / "identity" / "decisions.md").read_text(encoding="utf-8")
        assert "Core identity truth" in identity_text, "identity promotion missing identity entry"
        assert "prefers concise status updates" in preferences_text, "identity promotion missing preferences entry"
        assert "Decision: keep OpenClaw memory governance skill-first" in decisions_text, "identity promotion missing decisions entry"

        print("smoke_suite ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
