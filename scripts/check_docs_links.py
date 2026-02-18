#!/usr/bin/env python3
"""Fail on broken local markdown links and likely file-path references in docs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FILE_HINT_RE = re.compile(r"[A-Za-z0-9._/-]+\.(md|json|py|yml|yaml|zip|sh)$")
INLINE_SKIP_PREFIXES = (
    "memory/",
    "archive/",
    "~",
    "/",
    "$",
    "<",
)


def _iter_markdown_files(repo_root: Path) -> list[Path]:
    files = [repo_root / "README.md"]
    files.extend(sorted((repo_root / "docs").rglob("*.md")))
    files.extend(sorted((repo_root / "skills").rglob("*.md")))
    return [p for p in files if p.exists()]


def _resolve_candidate(source: Path, value: str, repo_root: Path) -> Path | None:
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if "://" in candidate:
        return None
    candidate = candidate.split("#", 1)[0].split("?", 1)[0].strip()
    if not candidate:
        return None
    if candidate.startswith("/"):
        return (repo_root / candidate.lstrip("/")).resolve()
    for parent in [source.parent, *source.parents]:
        try:
            parent.relative_to(repo_root)
        except ValueError:
            continue
        scoped = (parent / candidate).resolve()
        if scoped.exists():
            return scoped
    return (repo_root / candidate).resolve()


def _is_inline_path_candidate(value: str) -> bool:
    if "/" not in value:
        return False
    if " " in value:
        return False
    if any(ch in value for ch in "<>|$*{}()"):
        return False
    if value.startswith(INLINE_SKIP_PREFIXES):
        return False
    if value.startswith(("-", "./", "../")):
        return FILE_HINT_RE.search(value) is not None
    return FILE_HINT_RE.search(value) is not None


def main() -> int:
    failures: list[str] = []
    for md_file in _iter_markdown_files(REPO_ROOT):
        text = md_file.read_text(encoding="utf-8")

        for match in MD_LINK_RE.finditer(text):
            target = match.group(1).strip()
            resolved = _resolve_candidate(md_file, target, REPO_ROOT)
            if resolved is None:
                continue
            if not resolved.exists():
                failures.append(f"{md_file}: broken markdown link target `{target}`")

        for match in INLINE_CODE_RE.finditer(text):
            target = match.group(1).strip()
            if not _is_inline_path_candidate(target):
                continue
            resolved = _resolve_candidate(md_file, target, REPO_ROOT)
            if resolved is None:
                continue
            if not resolved.exists():
                failures.append(f"{md_file}: broken inline path reference `{target}`")

    if failures:
        print("docs_link_check failed")
        for item in failures:
            print(item)
        return 1

    print("docs_link_check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
