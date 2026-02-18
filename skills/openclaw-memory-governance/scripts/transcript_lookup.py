#!/usr/bin/env python3
"""Search transcript mirror files and return bounded excerpts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List

from memory_lib import (
    DEFAULT_TRANSCRIPT_ROOT,
    ensure_workspace_layout,
    is_under_root,
    parse_date_from_filename,
    redact_secrets,
    resolve_transcript_root,
)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def parse_transcript_sections(path: Path) -> List[Dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: List[Dict] = []
    current = None
    for line in lines:
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = {"header": line[3:].strip(), "body_lines": []}
        elif current is not None:
            current["body_lines"].append(line)
    if current:
        sections.append(current)
    for sec in sections:
        sec["body"] = "\n".join(sec.pop("body_lines")).strip()
    return sections


def lookup_transcripts(
    workspace: Path,
    transcript_root: str,
    topic: str,
    last_n_days: int = 7,
    max_excerpts: int = 5,
    max_chars_per_excerpt: int = 1200,
    allow_external_transcript_root: bool = False,
) -> Dict[str, object]:
    ensure_workspace_layout(workspace)
    transcript_dir = resolve_transcript_root(workspace, transcript_root)
    if not is_under_root(transcript_dir, workspace) and not allow_external_transcript_root:
        raise SystemExit(
            "Refusing transcript root outside workspace. Keep transcripts under workspace/, "
            "or pass --allow-external-transcript-root to override."
        )
    transcript_dir.mkdir(parents=True, exist_ok=True)

    topic_tokens = set(tokenize(topic))
    cutoff = dt.date.today() - dt.timedelta(days=max(last_n_days - 1, 0))
    results: List[Dict] = []

    for path in sorted(transcript_dir.glob("*.md")):
        if path.is_symlink():
            continue
        resolved = path.resolve()
        if not is_under_root(resolved, transcript_dir):
            continue
        day = parse_date_from_filename(path.name)
        if not day or day < cutoff:
            continue
        for sec in parse_transcript_sections(resolved):
            haystack = f"{sec['header']} {sec['body']}".lower()
            if not haystack.strip():
                continue
            score = sum(1 for tok in topic_tokens if tok in haystack)
            if score <= 0:
                continue
            excerpt = redact_secrets(sec["body"].strip())
            if len(excerpt) > max_chars_per_excerpt:
                excerpt = excerpt[: max_chars_per_excerpt - 3].rstrip() + "..."
            results.append(
                {
                    "date": day.isoformat(),
                    "header": redact_secrets(sec["header"]),
                    "score": score,
                    "excerpt": excerpt,
                    "source_ref": str(resolved.relative_to(workspace)),
                }
            )

    results.sort(key=lambda x: (x["score"], x["date"]), reverse=True)
    return {"topic": topic, "results": results[:max_excerpts]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument(
        "--transcript-root",
        default=DEFAULT_TRANSCRIPT_ROOT,
        help="Transcript mirror root path. Relative paths are resolved from workspace root.",
    )
    parser.add_argument(
        "--allow-external-transcript-root",
        action="store_true",
        help="Allow transcript root outside workspace root. Disabled by default for safety.",
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--last-n-days", type=int, default=7)
    parser.add_argument("--max-excerpts", type=int, default=5)
    parser.add_argument("--max-chars-per-excerpt", type=int, default=1200)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    payload = lookup_transcripts(
        workspace=workspace,
        transcript_root=args.transcript_root,
        topic=args.topic,
        last_n_days=args.last_n_days,
        max_excerpts=args.max_excerpts,
        max_chars_per_excerpt=args.max_chars_per_excerpt,
        allow_external_transcript_root=args.allow_external_transcript_root,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
