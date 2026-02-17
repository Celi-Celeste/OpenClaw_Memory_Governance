#!/usr/bin/env python3
"""Shared helpers for OpenClaw memory-governance scripts."""

from __future__ import annotations

import ast
import datetime as dt
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

ENTRY_RE = re.compile(r"^###\s+mem:([a-zA-Z0-9_-]+)\s*$")
DEFAULT_TRANSCRIPT_ROOT = "archive/transcripts"
LEGACY_TRANSCRIPT_ROOT = "memory/transcripts"

DEFAULT_META_ORDER = [
    "time",
    "layer",
    "importance",
    "confidence",
    "status",
    "source",
    "tags",
    "supersedes",
]


@dataclass
class MemoryEntry:
    entry_id: str
    meta: Dict[str, str] = field(default_factory=dict)
    body: str = ""

    def get_float(self, key: str, default: float) -> float:
        val = self.meta.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except ValueError:
            return default

    def tags(self) -> List[str]:
        raw = self.meta.get("tags", "[]").strip()
        if not raw:
            return []
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except (SyntaxError, ValueError):
            pass
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        return [x.strip().strip("\"'") for x in raw.split(",") if x.strip()]

    def token_set(self) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+", self.body.lower()))


def utc_now_z() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_mem_id() -> str:
    return uuid.uuid4().hex[:12]


def ensure_workspace_layout(workspace: Path) -> None:
    for sub in [
        "memory/episodic",
        "memory/semantic",
        "memory/identity",
        DEFAULT_TRANSCRIPT_ROOT,
    ]:
        (workspace / sub).mkdir(parents=True, exist_ok=True)


def episodic_file(workspace: Path, day: dt.date) -> Path:
    return workspace / "memory" / "episodic" / f"{day.isoformat()}.md"


def semantic_file(workspace: Path, day: dt.date) -> Path:
    return workspace / "memory" / "semantic" / f"{day.strftime('%Y-%m')}.md"


def resolve_transcript_root(workspace: Path, transcript_root: str) -> Path:
    root = Path(transcript_root).expanduser()
    if not root.is_absolute():
        root = workspace / root
    return root.resolve()


def is_under_root(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def transcript_file(workspace: Path, day: dt.date, transcript_root: str = DEFAULT_TRANSCRIPT_ROOT) -> Path:
    root = resolve_transcript_root(workspace, transcript_root)
    return root / f"{day.isoformat()}.md"


def parse_memory_file(path: Path) -> Tuple[str, List[MemoryEntry]]:
    if not path.exists():
        return "", []
    lines = path.read_text(encoding="utf-8").splitlines()
    preamble: List[str] = []
    entries: List[MemoryEntry] = []
    idx = 0
    while idx < len(lines):
        m = ENTRY_RE.match(lines[idx])
        if not m:
            preamble.append(lines[idx])
            idx += 1
            continue
        entry_id = m.group(1)
        idx += 1
        meta: Dict[str, str] = {}
        while idx < len(lines):
            line = lines[idx].strip()
            if line == "---":
                idx += 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
            idx += 1
        body_lines: List[str] = []
        while idx < len(lines) and not ENTRY_RE.match(lines[idx]):
            body_lines.append(lines[idx])
            idx += 1
        body = "\n".join(body_lines).strip()
        entries.append(MemoryEntry(entry_id=entry_id, meta=meta, body=body))
    return "\n".join(preamble).strip(), entries


def render_memory_file(preamble: str, entries: List[MemoryEntry]) -> str:
    blocks: List[str] = []
    if preamble.strip():
        blocks.append(preamble.strip())
    for entry in entries:
        lines: List[str] = [f"### mem:{entry.entry_id}"]
        ordered_keys = [k for k in DEFAULT_META_ORDER if k in entry.meta]
        extra_keys = [k for k in entry.meta.keys() if k not in DEFAULT_META_ORDER]
        for key in ordered_keys + sorted(extra_keys):
            lines.append(f"{key}: {entry.meta[key]}")
        lines.append("---")
        lines.append(entry.body.strip())
        blocks.append("\n".join(lines).rstrip())
    return "\n\n".join(blocks).rstrip() + "\n"


def write_memory_file(path: Path, preamble: str, entries: List[MemoryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_memory_file(preamble, entries), encoding="utf-8")


def normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_]+", value.lower()))


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def parse_iso_date(value: str) -> dt.datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_date_from_filename(name: str) -> dt.date | None:
    base = os.path.basename(name)
    stem, _ = os.path.splitext(base)
    try:
        return dt.date.fromisoformat(stem)
    except ValueError:
        return None
