#!/usr/bin/env python3
"""Deterministic skill-side memory recall ordering."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List

from memory_lib import ensure_workspace_layout, parse_date_from_filename, parse_iso_date, parse_memory_file

IDENTITY_FILES = [
    "memory/identity/identity.md",
    "memory/identity/preferences.md",
    "memory/identity/decisions.md",
]


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", value.lower()))


def _excerpt(value: str, max_chars: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 3)].rstrip() + "..."


def _entry_time_iso(entry_meta: Dict[str, str]) -> str:
    parsed = parse_iso_date(entry_meta.get("time", ""))
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _score_entry(text: str, topic_tokens: set[str]) -> tuple[int, float]:
    tokens = _tokenize(text)
    hits = sum(1 for tok in topic_tokens if tok in tokens)
    if hits <= 0:
        return 0, 0.0
    score = hits / max(len(topic_tokens), 1)
    return hits, round(score, 4)


def _relative_ref(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace))
    except ValueError:
        return path.name


def _ranked_entries_for_file(
    path: Path,
    workspace: Path,
    topic_tokens: set[str],
    layer: str,
    max_chars: int,
    include_historical: bool,
) -> List[Dict[str, object]]:
    _, entries = parse_memory_file(path)
    ranked: List[Dict[str, object]] = []
    source_ref = _relative_ref(path, workspace)
    for entry in entries:
        status = entry.meta.get("status", "active").strip().lower() or "active"
        if status == "historical" and not include_historical:
            continue
        hits, score = _score_entry(entry.body, topic_tokens)
        if hits <= 0:
            continue
        ranked.append(
            {
                "layer": layer,
                "source_ref": source_ref,
                "entry_id": f"mem:{entry.entry_id}",
                "status": status,
                "time": _entry_time_iso(entry.meta),
                "token_hits": hits,
                "score": score,
                "excerpt": _excerpt(entry.body, max_chars=max_chars),
            }
        )
    ranked.sort(key=lambda x: (x["score"], x["time"]), reverse=True)
    return ranked


def _recent_semantic_files(workspace: Path, semantic_months: int) -> List[Path]:
    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    cutoff = (dt.date.today().replace(day=1) - dt.timedelta(days=max(semantic_months - 1, 0) * 31)).replace(day=1)
    keep: List[Path] = []
    for path in sorted(semantic_dir.glob("*.md")):
        stem = path.stem
        try:
            month = dt.datetime.strptime(stem, "%Y-%m").date().replace(day=1)
        except ValueError:
            continue
        if month >= cutoff:
            keep.append(path)
    return sorted(keep, reverse=True)


def _recent_episodic_files(workspace: Path, episodic_days: int) -> List[Path]:
    episodic_dir = workspace / "memory" / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    cutoff = dt.date.today() - dt.timedelta(days=max(episodic_days - 1, 0))
    keep: List[Path] = []
    for path in sorted(episodic_dir.glob("*.md")):
        file_day = parse_date_from_filename(path.name)
        if file_day is None:
            continue
        if file_day >= cutoff:
            keep.append(path)
    return sorted(keep, reverse=True)


def ordered_recall(
    workspace: Path,
    topic: str,
    max_results: int,
    max_per_layer: int,
    max_chars: int,
    episodic_days: int,
    semantic_months: int,
    include_historical: bool,
) -> Dict[str, object]:
    ensure_workspace_layout(workspace)
    topic_tokens = _tokenize(topic)
    if not topic_tokens:
        raise SystemExit("Topic must contain at least one alphanumeric token.")

    identity_hits: List[Dict[str, object]] = []
    for rel_path in IDENTITY_FILES:
        path = workspace / rel_path
        if not path.exists():
            continue
        identity_hits.extend(
            _ranked_entries_for_file(
                path=path,
                workspace=workspace,
                topic_tokens=topic_tokens,
                layer="identity",
                max_chars=max_chars,
                include_historical=include_historical,
            )
        )
    identity_hits = identity_hits[:max(max_per_layer, 0)]

    semantic_hits: List[Dict[str, object]] = []
    for path in _recent_semantic_files(workspace, semantic_months=max(semantic_months, 1)):
        semantic_hits.extend(
            _ranked_entries_for_file(
                path=path,
                workspace=workspace,
                topic_tokens=topic_tokens,
                layer="semantic",
                max_chars=max_chars,
                include_historical=include_historical,
            )
        )
    semantic_hits.sort(key=lambda x: (x["score"], x["time"]), reverse=True)
    semantic_hits = semantic_hits[:max(max_per_layer, 0)]

    episodic_hits: List[Dict[str, object]] = []
    for path in _recent_episodic_files(workspace, episodic_days=max(episodic_days, 1)):
        episodic_hits.extend(
            _ranked_entries_for_file(
                path=path,
                workspace=workspace,
                topic_tokens=topic_tokens,
                layer="episodic",
                max_chars=max_chars,
                include_historical=include_historical,
            )
        )
    episodic_hits.sort(key=lambda x: (x["score"], x["time"]), reverse=True)
    episodic_hits = episodic_hits[:max(max_per_layer, 0)]

    ordered = identity_hits + semantic_hits + episodic_hits
    ordered = ordered[:max(max_results, 0)]
    return {
        "topic": topic,
        "order": {
            "layers": ["identity", "semantic", "episodic"],
            "identity_files": IDENTITY_FILES,
        },
        "results": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--topic", required=True, help="Recall topic string.")
    parser.add_argument("--max-results", type=int, default=12, help="Global result cap.")
    parser.add_argument("--max-per-layer", type=int, default=4, help="Result cap per layer.")
    parser.add_argument("--max-chars", type=int, default=240, help="Max excerpt size per hit.")
    parser.add_argument("--episodic-days", type=int, default=30, help="Episodic lookback window in days.")
    parser.add_argument("--semantic-months", type=int, default=6, help="Semantic lookback window in months.")
    parser.add_argument("--include-historical", action="store_true", help="Include historical status entries.")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    payload = ordered_recall(
        workspace=workspace,
        topic=args.topic,
        max_results=args.max_results,
        max_per_layer=args.max_per_layer,
        max_chars=args.max_chars,
        episodic_days=args.episodic_days,
        semantic_months=args.semantic_months,
        include_historical=args.include_historical,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
