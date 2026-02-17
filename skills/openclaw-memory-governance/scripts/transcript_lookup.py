#!/usr/bin/env python3
"""Search transcript mirror files and return bounded excerpts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List

from memory_lib import DEFAULT_TRANSCRIPT_ROOT, ensure_workspace_layout, parse_date_from_filename, resolve_transcript_root


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument(
        "--transcript-root",
        default=DEFAULT_TRANSCRIPT_ROOT,
        help="Transcript mirror root path. Relative paths are resolved from workspace root.",
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--last-n-days", type=int, default=7)
    parser.add_argument("--max-excerpts", type=int, default=5)
    parser.add_argument("--max-chars-per-excerpt", type=int, default=1200)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    transcript_dir = resolve_transcript_root(workspace, args.transcript_root)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    topic_tokens = set(tokenize(args.topic))
    cutoff = dt.date.today() - dt.timedelta(days=max(args.last_n_days - 1, 0))
    results: List[Dict] = []

    for path in sorted(transcript_dir.glob("*.md")):
        day = parse_date_from_filename(path.name)
        if not day or day < cutoff:
            continue
        for sec in parse_transcript_sections(path):
            haystack = f"{sec['header']} {sec['body']}".lower()
            if not haystack.strip():
                continue
            score = sum(1 for tok in topic_tokens if tok in haystack)
            if score <= 0:
                continue
            excerpt = sec["body"].strip()
            if len(excerpt) > args.max_chars_per_excerpt:
                excerpt = excerpt[: args.max_chars_per_excerpt - 3].rstrip() + "..."
            results.append(
                {
                    "date": day.isoformat(),
                    "header": sec["header"],
                    "score": score,
                    "excerpt": excerpt,
                    "source_ref": str(path.relative_to(workspace)),
                }
            )

    results.sort(key=lambda x: (x["score"], x["date"]), reverse=True)
    payload = {"topic": args.topic, "results": results[: args.max_excerpts]}
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
