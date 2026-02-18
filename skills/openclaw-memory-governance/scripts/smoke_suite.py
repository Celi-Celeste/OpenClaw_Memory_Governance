#!/usr/bin/env python3
"""Smoke tests for the openclaw-memory-governance scripts."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from memory_lib import redact_secrets, write_memory_file


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


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
    redaction_fixture = (
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 "
        "SeCrEt: fixture-secret-value "
        "api_key=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 "
        "-----BEGIN PRIVATE KEY-----\\nABCDEF\\n-----END PRIVATE KEY-----"
    )
    redacted_fixture = redact_secrets(redaction_fixture)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted_fixture, "redaction fixture leaked bearer token"
    assert "fixture-secret-value" not in redacted_fixture, "redaction fixture leaked mixed-case secret assignment"
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in redacted_fixture, "redaction fixture leaked API key"
    assert "BEGIN PRIVATE KEY" not in redacted_fixture, "redaction fixture leaked private key block"
    assert "<REDACTED>" in redacted_fixture, "redaction fixture should include redaction marker"

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

        # Importance scoring should canonicalize tag aliases and cap per-run updates.
        alias_dir = workspace / "memory" / "config"
        alias_dir.mkdir(parents=True, exist_ok=True)
        (alias_dir / "concept_aliases.json").write_text(
            json.dumps(
                {
                    "governance thing": "openclaw memory governance",
                    "the project": "openclaw memory governance",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        write_entries(
            sem,
            [
                make_entry(
                    "s1",
                    "semantic",
                    "Governance thing remains important for the project.",
                    0.88,
                    timestamp=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                ),
                make_entry(
                    "s2",
                    "semantic",
                    "OpenClaw Memory Governance Skill is the baseline policy.",
                    0.90,
                    timestamp=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=9)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                ),
                make_entry(
                    "s3",
                    "semantic",
                    "The project focus may shift after rollout.",
                    0.75,
                    timestamp=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                ),
            ],
        )
        # Explicitly set noisy tags to ensure canonicalization behavior.
        sem_seed = sem.read_text(encoding="utf-8")
        sem_seed = sem_seed.replace("tags: ['project']", "tags: ['governance thing', 'decision']", 1)
        sem_seed = sem_seed.replace("tags: ['project']", "tags: ['OpenClaw Memory Governance Skill', 'policy']", 1)
        sem_seed = sem_seed.replace("tags: ['project']", "tags: ['the project']", 1)
        sem.write_text(sem_seed, encoding="utf-8")
        score_run = run(
            [
                "python3",
                str(script_dir / "importance_score.py"),
                "--workspace",
                str(workspace),
                "--window-days",
                "30",
                "--max-updates",
                "2",
            ],
            cwd=script_dir,
        )
        assert "updated=2" in score_run.stdout, "importance score max-updates cap not enforced"
        scored_text = sem.read_text(encoding="utf-8")
        assert "openclaw_memory_governance" in scored_text, "importance score failed to canonicalize alias tags"
        assert scored_text.count("last_scored_at:") == 2, "importance score unexpectedly updated beyond cap"
        score_path_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "importance_score.py"),
                "--workspace",
                str(workspace),
                "--checkpoint-file",
                "../outside-checkpoint.json",
            ],
            cwd=script_dir,
        )
        assert score_path_guard.returncode != 0, "importance score should block checkpoint paths outside workspace"

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
        event_ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        transcript_bearer = "zxywvutsrqponmlkjihgfedcba987654"
        transcript_secret_value = "transcript-secret-value"
        transcript_private_key = "TRANSCRIPT-PRIVATE-KEY"
        events = [
            {
                "timestamp": event_ts,
                "role": "user",
                "content": (
                    "Please revisit memory cadence and transcript lookup details. "
                    "api_key=sk-1234567890ABCDEFGHIJKLMNOP "
                    f"Authorization: Bearer {transcript_bearer} "
                    f"SeCrEt: {transcript_secret_value}"
                ),
            },
            {
                "timestamp": event_ts,
                "role": "assistant",
                "content": (
                    "Key material sample "
                    "-----BEGIN PRIVATE KEY----- "
                    f"{transcript_private_key} "
                    "-----END PRIVATE KEY-----"
                ),
                "internal_payload": {
                    "debug_token": "Bearer abcdefghijklmnopqrstuvwxyz123456",
                },
            },
        ]
        (sessions_dir / "session-a.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )
        legacy_day = today - dt.timedelta(days=1)
        legacy_transcript = workspace / "memory" / "transcripts" / f"{legacy_day.isoformat()}.md"
        legacy_transcript.write_text(
            f"# {legacy_day.isoformat()}\n\n## 09:00:00 - user (legacy)\nlegacy transcript entry\n",
            encoding="utf-8",
        )
        os.chmod(legacy_transcript, 0o644)
        external_session_phrase = "this phrase must never be ingested from session symlink"
        if hasattr(os, "symlink"):
            outside_session_file = workspace.parent / "outside-session-event.jsonl"
            outside_session_file.write_text(
                json.dumps(
                    {
                        "timestamp": event_ts,
                        "role": "user",
                        "content": external_session_phrase,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            session_symlink = sessions_dir / "session-link.jsonl"
            if session_symlink.exists() or session_symlink.is_symlink():
                session_symlink.unlink()
            os.symlink(outside_session_file, session_symlink)

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

        full_mode_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "archive/transcripts",
                "--transcript-mode",
                "full",
            ],
            cwd=script_dir,
        )
        assert full_mode_guard.returncode != 0, "daily consolidate should require explicit ack for transcript-mode full"

        full_mode_ack = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "archive/transcripts",
                "--transcript-mode",
                "full",
                "--acknowledge-transcript-risk",
                "--dry-run",
            ],
            cwd=script_dir,
        )
        assert full_mode_ack.returncode == 0, "daily consolidate should allow transcript-mode full with explicit ack"

        memory_override_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "memory/transcripts",
                "--allow-transcripts-under-memory",
                "--dry-run",
            ],
            cwd=script_dir,
        )
        assert memory_override_guard.returncode != 0, "daily consolidate should require explicit ack for memory-root override"

        memory_override_ack = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "memory/transcripts",
                "--allow-transcripts-under-memory",
                "--acknowledge-transcript-risk",
                "--dry-run",
            ],
            cwd=script_dir,
        )
        assert memory_override_ack.returncode == 0, "daily consolidate should allow memory-root override with explicit ack"

        external_root = workspace.parent / "outside-transcripts"
        external_root.mkdir(parents=True, exist_ok=True)
        external_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                str(external_root),
            ],
            cwd=script_dir,
        )
        assert external_guard.returncode != 0, "daily transcript root guard failed to block external transcript root"
        external_lookup_day = today
        external_lookup_phrase = "external allowed lookup phrase"
        (external_root / f"{external_lookup_day.isoformat()}.md").write_text(
            f"# {external_lookup_day.isoformat()}\n\n## 07:30:00 - user (external)\n{external_lookup_phrase}\n",
            encoding="utf-8",
        )
        external_lookup_allowed = run(
            [
                "python3",
                str(script_dir / "transcript_lookup.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                str(external_root),
                "--allow-external-transcript-root",
                "--topic",
                external_lookup_phrase,
                "--last-n-days",
                "7",
                "--max-excerpts",
                "5",
            ],
            cwd=script_dir,
        )
        external_lookup_payload = json.loads(external_lookup_allowed.stdout)
        assert external_lookup_payload["results"], "transcript lookup should return results when external root is explicitly allowed"
        first_external = external_lookup_payload["results"][0]
        assert not first_external["source_ref"].startswith("/"), "transcript lookup source_ref should not expose absolute paths"
        assert first_external["source_ref"].endswith(f"{external_lookup_day.isoformat()}.md"), "transcript lookup source_ref mismatch for external root"

        external_override_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                str(external_root),
                "--allow-external-transcript-root",
                "--dry-run",
            ],
            cwd=script_dir,
        )
        assert external_override_guard.returncode != 0, "daily consolidate should require explicit ack for external-root override"

        external_override_ack = run_maybe_fail(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                str(external_root),
                "--allow-external-transcript-root",
                "--acknowledge-transcript-risk",
                "--dry-run",
            ],
            cwd=script_dir,
        )
        assert external_override_ack.returncode == 0, "daily consolidate should allow external-root override with explicit ack"

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
                "--transcript-mode",
                "sanitized",
                "--episodic-retention-days",
                "14",
                "--transcript-retention-days",
                "7",
            ],
            cwd=script_dir,
        )

        transcript_root = workspace / "archive" / "transcripts"
        transcripts = sorted(transcript_root.glob("*.md"))
        assert transcripts, "daily transcript mirror not created in archive/transcripts"
        transcript = None
        for candidate in transcripts:
            txt = candidate.read_text(encoding="utf-8")
            if "Please revisit memory cadence and transcript lookup details" in txt:
                transcript = candidate
                break
        assert transcript is not None, "daily transcript mirror missing expected session content"
        migrated_legacy = transcript_root / f"{legacy_day.isoformat()}.md"
        assert migrated_legacy.exists(), "legacy transcript was not migrated"
        assert not legacy_transcript.exists(), "legacy transcript file was not moved"
        transcript_text = transcript.read_text(encoding="utf-8")
        assert "<REDACTED>" in transcript_text, "daily transcript mirror did not redact sensitive content"
        assert "sk-1234567890ABCDEFGHIJKLMNOP" not in transcript_text, "daily transcript mirror leaked raw API key"
        assert transcript_bearer not in transcript_text, "daily transcript mirror leaked bearer token content"
        assert transcript_secret_value not in transcript_text, "daily transcript mirror leaked mixed-case secret assignment"
        assert transcript_private_key not in transcript_text, "daily transcript mirror leaked private key material"
        assert "internal_payload" not in transcript_text, "daily transcript mirror should skip non-text session payloads"
        assert external_session_phrase not in transcript_text, "daily transcript mirror should skip session symlink inputs"
        mode = stat.S_IMODE(transcript.stat().st_mode)
        assert mode == 0o600, f"daily transcript mirror permissions should be 0600, got {oct(mode)}"
        transcript_dir_mode = stat.S_IMODE(transcript_root.stat().st_mode)
        assert transcript_dir_mode == 0o700, f"transcript mirror directory permissions should be 0700, got {oct(transcript_dir_mode)}"
        migrated_mode = stat.S_IMODE(migrated_legacy.stat().st_mode)
        assert migrated_mode == 0o600, f"migrated legacy transcript should be chmod 0600, got {oct(migrated_mode)}"

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

        if hasattr(os, "symlink"):
            symlink_day = today - dt.timedelta(days=2)
            symlink_target = workspace / "outside-target.md"
            symlink_target.write_text(
                f"# {symlink_day.isoformat()}\n\n## 08:00:00 - user (external)\nunique external phrase\n",
                encoding="utf-8",
            )
            symlink_path = transcript_root / f"{symlink_day.isoformat()}.md"
            if symlink_path.exists():
                symlink_path.unlink()
            os.symlink(symlink_target, symlink_path)
            symlink_lookup = run(
                [
                    "python3",
                    str(script_dir / "transcript_lookup.py"),
                    "--workspace",
                    str(workspace),
                    "--transcript-root",
                    "archive/transcripts",
                    "--topic",
                    "unique external phrase",
                    "--last-n-days",
                    "7",
                    "--max-excerpts",
                    "5",
                ],
                cwd=script_dir,
            )
            symlink_results = json.loads(symlink_lookup.stdout)
            assert not symlink_results["results"], "transcript lookup should ignore symlink transcript files"

        lookup_external_guard = run_maybe_fail(
            [
                "python3",
                str(script_dir / "transcript_lookup.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                str(external_root),
                "--topic",
                "memory cadence",
            ],
            cwd=script_dir,
        )
        assert lookup_external_guard.returncode != 0, "transcript lookup root guard failed to block external path"

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

        flow_hold = run(
            [
                "python3",
                str(script_dir / "confidence_gate_flow.py"),
                "--workspace",
                str(workspace),
                "--avg-similarity",
                "0.55",
                "--result-count",
                "2",
                "--retrieval-confidence",
                "0.58",
                "--continuation-intent",
                "true",
                "--lookup-approved",
                "false",
            ],
            cwd=script_dir,
        )
        flow_hold_payload = json.loads(flow_hold.stdout)
        assert flow_hold_payload["decision"] == "partial_and_ask_lookup", "confidence flow should request lookup before approval"
        assert not flow_hold_payload["lookup_performed"], "confidence flow should not perform lookup without approval"

        flow_lookup = run(
            [
                "python3",
                str(script_dir / "confidence_gate_flow.py"),
                "--workspace",
                str(workspace),
                "--avg-similarity",
                "0.55",
                "--result-count",
                "2",
                "--retrieval-confidence",
                "0.58",
                "--continuation-intent",
                "true",
                "--lookup-approved",
                "true",
                "--topic",
                "memory cadence",
            ],
            cwd=script_dir,
        )
        flow_lookup_payload = json.loads(flow_lookup.stdout)
        assert flow_lookup_payload["decision"] == "lookup_performed", "confidence flow should perform lookup after approval"
        assert flow_lookup_payload["lookup_performed"], "confidence flow lookup flag mismatch"
        assert flow_lookup_payload["lookup"]["results"], "confidence flow lookup returned no excerpts"

        flow_normal = run(
            [
                "python3",
                str(script_dir / "confidence_gate_flow.py"),
                "--workspace",
                str(workspace),
                "--avg-similarity",
                "0.89",
                "--result-count",
                "10",
                "--retrieval-confidence",
                "0.86",
                "--continuation-intent",
                "false",
                "--lookup-approved",
                "true",
                "--topic",
                "memory cadence",
            ],
            cwd=script_dir,
        )
        flow_normal_payload = json.loads(flow_normal.stdout)
        assert flow_normal_payload["decision"] == "respond_normally", "confidence flow should respond normally for high signal"
        assert not flow_normal_payload["lookup_performed"], "confidence flow should skip lookup when confidence is high"

        # Validate session hygiene controls for upstream session JSONL risk.
        stale_file = sessions_dir / "stale-session.jsonl"
        stale_nested_token = "nested-array-token-value"
        stale_nested_secret = "nested-secret-value"
        stale_nested_bearer = "nestedbearertokenabcdefghijklmnopqrstuvwxyz987654"
        stale_file.write_text(
            json.dumps(
                {
                    "timestamp": event_ts,
                    "role": "user",
                    "content": "token=supersecretvalue and api_key=sk-ABCDEF1234567890ZXCV",
                    "password": "plain-password-value",
                    "metadata": {"api_key": "plain-structured-api-key"},
                    "history": [{"access-token": stale_nested_token}, {"note": f"Bearer {stale_nested_bearer}"}],
                    "nested": {"seCrEt": stale_nested_secret},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        old_mtime = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).timestamp()
        os.utime(stale_file, (old_mtime, old_mtime))

        prune_file = sessions_dir / "prune-session.jsonl"
        prune_file.write_text(json.dumps({"role": "user", "content": "older than retention"}) + "\n", encoding="utf-8")
        prune_mtime = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).timestamp()
        os.utime(prune_file, (prune_mtime, prune_mtime))

        sessions_store = sessions_dir / "sessions.json"
        sessions_store.write_text(
            json.dumps(
                {
                    "keep": {"sessionId": "stale-session"},
                    "drop": {"sessionId": "prune-session"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        symlink_target_secret = "outside-target-secret-for-hygiene"
        symlink_target_file = workspace.parent / "outside-session-hygiene.jsonl"
        symlink_target_file.write_text(
            json.dumps({"role": "user", "content": f"token={symlink_target_secret}"}) + "\n",
            encoding="utf-8",
        )
        symlink_path = sessions_dir / "linked-outside-session.jsonl"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        os.symlink(symlink_target_file, symlink_path)

        run(
            [
                "python3",
                str(script_dir / "session_hygiene.py"),
                "--sessions-dir",
                str(sessions_dir),
                "--retention-days",
                "30",
                "--skip-recent-minutes",
                "0",
            ],
            cwd=script_dir,
        )
        assert not prune_file.exists(), "session hygiene failed to prune stale JSONL session file"
        stale_text = stale_file.read_text(encoding="utf-8")
        assert "supersecretvalue" not in stale_text, "session hygiene failed to redact token value"
        assert "plain-password-value" not in stale_text, "session hygiene failed to redact structured password fields"
        assert "plain-structured-api-key" not in stale_text, "session hygiene failed to redact nested structured API keys"
        assert stale_nested_token not in stale_text, "session hygiene failed to redact nested array token fields"
        assert stale_nested_secret not in stale_text, "session hygiene failed to redact mixed-case nested secret fields"
        assert stale_nested_bearer not in stale_text, "session hygiene failed to redact bearer token patterns in nested text"
        assert "<REDACTED>" in stale_text, "session hygiene did not insert redaction markers"
        assert symlink_path.is_symlink(), "session hygiene should ignore symlink JSONL files"
        target_text = symlink_target_file.read_text(encoding="utf-8")
        assert symlink_target_secret in target_text, "session hygiene should not rewrite symlink target files outside sessions dir"
        sessions_store_payload = json.loads(sessions_store.read_text(encoding="utf-8"))
        assert "drop" not in sessions_store_payload, "session hygiene failed to prune stale sessions.json entry"
        assert "keep" in sessions_store_payload, "session hygiene removed valid sessions.json entry"

        sessions_dir_mode = stat.S_IMODE(sessions_dir.stat().st_mode)
        stale_mode = stat.S_IMODE(stale_file.stat().st_mode)
        store_mode = stat.S_IMODE(sessions_store.stat().st_mode)
        assert sessions_dir_mode == 0o700, f"session hygiene dir permissions should be 0700, got {oct(sessions_dir_mode)}"
        assert stale_mode == 0o600, f"session hygiene JSONL permissions should be 0600, got {oct(stale_mode)}"
        assert store_mode == 0o600, f"session hygiene sessions.json permissions should be 0600, got {oct(store_mode)}"

        run(
            [
                "python3",
                str(script_dir / "daily_consolidate.py"),
                "--workspace",
                str(workspace),
                "--transcript-root",
                "archive/transcripts",
                "--transcript-mode",
                "off",
            ],
            cwd=script_dir,
        )
        assert not list(transcript_root.glob("*.md")), "transcript-mode off should remove transcript mirror files"

        # Seed recurring semantic entries for identity promotion.
        sem_promote = workspace / "memory" / "semantic" / today.strftime("%Y-%m.md")
        base_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=12)
        promote_entries = []
        for idx in range(3):
            ts = (base_ts + dt.timedelta(days=idx)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            promote_entries.append(make_entry(f"pref{idx}", "semantic", "User prefers concise status updates for memory review.", 0.92, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['preference']"
            promote_entries.append(make_entry(f"dec{idx}", "semantic", "Decision: keep OpenClaw memory governance skill-first and avoid core patching.", 0.94, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['decision']"
            promote_entries.append(make_entry(f"id{idx}", "semantic", "Core identity truth: project focus is reliable OpenClaw memory continuity.", 0.91, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['identity']"
            promote_entries.append(make_entry(f"tmp{idx}", "semantic", "Project burst topic this week only.", 0.96, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['project']"
            promote_entries.append(make_entry(f"exp{idx}", "semantic", "Expired decision candidate should never be promoted.", 0.97, timestamp=ts))
            promote_entries[-1]["meta"]["tags"] = "['decision']"
            promote_entries[-1]["meta"]["valid_until"] = (
                dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
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
        assert "Project burst topic this week only." not in identity_text, "identity promotion should skip transient project bursts"
        assert "Expired decision candidate should never be promoted." not in decisions_text, "identity promotion should skip expired candidates"

        ordered_recall = run(
            [
                "python3",
                str(script_dir / "ordered_recall.py"),
                "--workspace",
                str(workspace),
                "--topic",
                "core identity truth project focus reliable openclaw memory continuity",
                "--max-results",
                "9",
                "--max-per-layer",
                "3",
            ],
            cwd=script_dir,
        )
        ordered_payload = json.loads(ordered_recall.stdout)
        assert ordered_payload["results"], "ordered recall returned no results for known identity topic"
        first_result = ordered_payload["results"][0]
        assert first_result["layer"] == "identity", "ordered recall should prioritize identity layer first"
        assert first_result["source_ref"] == "memory/identity/identity.md", "ordered recall should prioritize identity.md first"
        assert not any(
            "archive/transcripts" in item["source_ref"] for item in ordered_payload["results"]
        ), "ordered recall should not include transcript mirror files"

        print("smoke_suite ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
