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
    with tempfile.TemporaryDirectory(prefix="oc-mem-smoke-") as td:
        workspace = Path(td)
        (workspace / "memory" / "episodic").mkdir(parents=True, exist_ok=True)
        (workspace / "memory" / "semantic").mkdir(parents=True, exist_ok=True)
        (workspace / "memory" / "transcripts").mkdir(parents=True, exist_ok=True)
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
        run(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--sessions-dir",
                str(sessions_dir),
                "--episodic-retention-days",
                "14",
                "--transcript-retention-days",
                "7",
            ],
            cwd=script_dir,
        )

        transcript = workspace / "memory" / "transcripts" / f"{today.isoformat()}.md"
        assert transcript.exists(), "daily transcript mirror not created"

        lookup = run(
            [
                "python3",
                str(script_dir / "transcript_lookup.py"),
                "--workspace",
                str(workspace),
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

        print("smoke_suite ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
