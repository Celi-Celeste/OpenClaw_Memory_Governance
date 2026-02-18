#!/usr/bin/env python3
"""Re-score episodic/semantic memory importance with bounded incremental work."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from memory_lib import (
    MemoryEntry,
    atomic_write_text,
    ensure_workspace_layout,
    file_lock,
    is_under_root,
    normalize_text,
    parse_date_from_filename,
    parse_iso_date,
    parse_memory_file,
    write_memory_file,
)

PREFERENCE_TAGS = {"preference", "style", "workflow", "tooling"}
PROJECT_TAGS = {"project", "openclaw", "memory", "architecture", "decision", "policy", "constraint"}
UTILITY_TAGS = {"architecture", "policy", "constraint", "workflow", "decision", "preference", "process"}
DURABILITY_ORDER = {"transient": 0, "project-stable": 1, "foundational": 2}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def parse_aliases(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    aliases: Dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        aliases[normalize_text(key)] = normalize_text(value)
    return {k: v for k, v in aliases.items() if k and v}


def canonicalize_text(value: str, aliases: Dict[str, str]) -> str:
    out = normalize_text(value)
    for alias, canonical in sorted(aliases.items(), key=lambda x: len(x[0]), reverse=True):
        if not alias:
            continue
        out = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", canonical, out)
    return normalize_text(out)


def canonicalize_tags(tags: List[str], aliases: Dict[str, str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in tags:
        norm = canonicalize_text(raw, aliases).replace(" ", "_")
        if not norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def infer_scope(tags: List[str], body: str, existing: str) -> str:
    if existing in {"project", "global", "personal"}:
        return existing
    lowered = set(tags)
    body_lower = body.lower()
    if lowered & PREFERENCE_TAGS or "prefer" in body_lower:
        return "personal"
    if lowered & PROJECT_TAGS or "openclaw" in body_lower:
        return "project"
    return "global"


def infer_durability(tags: List[str], body: str, existing: str) -> str:
    if existing in DURABILITY_ORDER:
        return existing
    lowered = set(tags)
    body_lower = body.lower()
    if lowered & {"identity", "principle", "foundational"} or "core identity" in body_lower:
        return "foundational"
    if lowered & (UTILITY_TAGS | PROJECT_TAGS):
        return "project-stable"
    return "transient"


def concept_key(entry: MemoryEntry, aliases: Dict[str, str]) -> str:
    canon_body = canonicalize_text(entry.body, aliases)
    tags = canonicalize_tags(entry.tags(), aliases)
    if tags:
        return f"{canon_body} :: {' '.join(tags)}"
    return canon_body


def parse_month_stem(name: str) -> dt.date | None:
    stem = Path(name).stem
    try:
        return dt.datetime.strptime(stem, "%Y-%m").date()
    except ValueError:
        return None


def load_candidate_entries(
    workspace: Path,
    now: dt.datetime,
    window_days: int,
) -> List[Tuple[Path, str, List[MemoryEntry]]]:
    cutoff_day = (now - dt.timedelta(days=window_days)).date()
    bundles: List[Tuple[Path, str, List[MemoryEntry]]] = []

    episodic_dir = workspace / "memory" / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(episodic_dir.glob("*.md")):
        day = parse_date_from_filename(path.name)
        if day and day < cutoff_day:
            continue
        preamble, entries = parse_memory_file(path)
        bundles.append((path, preamble, entries))

    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    cutoff_month = dt.date(cutoff_day.year, cutoff_day.month, 1)
    for path in sorted(semantic_dir.glob("*.md")):
        month = parse_month_stem(path.name)
        if month and month < cutoff_month:
            continue
        preamble, entries = parse_memory_file(path)
        bundles.append((path, preamble, entries))

    return bundles


def compute_score(
    entry: MemoryEntry,
    concept_counts: Dict[str, int],
    concept_first_seen: Dict[str, dt.datetime],
    aliases: Dict[str, str],
    now: dt.datetime,
    half_life_days: int,
    alpha: float,
) -> Tuple[float, Dict[str, float], List[str], str, str]:
    tags = canonicalize_tags(entry.tags(), aliases)
    body = entry.body
    key = concept_key(entry, aliases)
    recurrence_count = concept_counts.get(key, 1)
    first_seen = concept_first_seen.get(key, now)

    goal_relevance = 0.78 if (set(tags) & PROJECT_TAGS or "openclaw" in body.lower()) else 0.45
    recurrence = clamp((recurrence_count - 1) / 4.0)
    future_utility = 0.8 if (set(tags) & UTILITY_TAGS) else 0.45
    preference_signal = 0.85 if (set(tags) & PREFERENCE_TAGS or "prefer" in body.lower()) else 0.2
    novelty = 0.95 if recurrence_count <= 1 else clamp(1.0 - ((recurrence_count - 1) / 6.0), 0.15, 1.0)

    raw = (
        0.35 * goal_relevance
        + 0.20 * recurrence
        + 0.20 * future_utility
        + 0.15 * preference_signal
        + 0.10 * novelty
    )

    scope = infer_scope(tags, body, entry.meta.get("scope", "").strip().lower())
    durability = infer_durability(tags, body, entry.meta.get("durability", "").strip().lower())

    age_days = max((now - first_seen).total_seconds() / 86400.0, 0.0)
    if durability == "foundational":
        decay = 1.0
    elif durability == "project-stable":
        decay = 0.5 ** (age_days / max(half_life_days * 2, 1))
    else:
        decay = 0.5 ** (age_days / max(half_life_days, 1))

    target = clamp(raw * decay)
    old_importance = entry.get_float("importance", target)
    new_importance = clamp((1.0 - alpha) * old_importance + alpha * target)
    if entry.meta.get("status", "active") == "historical":
        new_importance = clamp(new_importance * 0.65)

    signals = {
        "goal_relevance": round(goal_relevance, 4),
        "recurrence": round(recurrence, 4),
        "future_utility": round(future_utility, 4),
        "preference_signal": round(preference_signal, 4),
        "novelty": round(novelty, 4),
        "raw_score": round(raw, 4),
        "decay": round(decay, 4),
        "target": round(target, 4),
    }
    return new_importance, signals, tags, scope, durability


def should_rescore(entry: MemoryEntry, now: dt.datetime) -> bool:
    last_scored = parse_iso_date(entry.meta.get("last_scored_at", ""))
    if last_scored is None:
        return True
    if last_scored.tzinfo is None:
        last_scored = last_scored.replace(tzinfo=dt.timezone.utc)
    durability = entry.meta.get("durability", "").strip().lower()
    interval_days = {"transient": 1, "project-stable": 3, "foundational": 7}.get(durability, 2)
    return (now - last_scored) >= dt.timedelta(days=interval_days)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--half-life-days", type=int, default=30)
    parser.add_argument("--alpha", type=float, default=0.30, help="Smoothing factor for importance updates.")
    parser.add_argument("--max-updates", type=int, default=400, help="Bounded updates per run to avoid compute creep.")
    parser.add_argument(
        "--alias-file",
        default="memory/config/concept_aliases.json",
        help="Alias map for concept/tag canonicalization.",
    )
    parser.add_argument(
        "--checkpoint-file",
        default="memory/state/importance-score.json",
        help="Checkpoint metadata file path.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("importance_score skipped=lock_held")
            return 0

        now = dt.datetime.now(dt.timezone.utc)
        alias_path = (workspace / args.alias_file).resolve()
        if not is_under_root(alias_path, workspace):
            raise SystemExit(
                "Refusing alias file outside workspace. Keep alias file under workspace/, "
                "or run from a workspace-local alias path."
            )
        aliases = parse_aliases(alias_path)
        checkpoint_path = (workspace / args.checkpoint_file).resolve()
        if not is_under_root(checkpoint_path, workspace):
            raise SystemExit(
                "Refusing checkpoint file outside workspace. Keep checkpoint file under workspace/, "
                "or run from a workspace-local checkpoint path."
            )

        bundles = load_candidate_entries(workspace, now=now, window_days=args.window_days)
        all_entries: List[Tuple[Path, str, List[MemoryEntry], int, MemoryEntry]] = []
        concept_counts: Dict[str, int] = {}
        concept_first_seen: Dict[str, dt.datetime] = {}
        for path, preamble, entries in bundles:
            for idx, entry in enumerate(entries):
                key = concept_key(entry, aliases)
                if not key:
                    continue
                ts = parse_iso_date(entry.meta.get("time", "")) or now
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
                concept_counts[key] = concept_counts.get(key, 0) + 1
                first = concept_first_seen.get(key)
                if first is None or ts < first:
                    concept_first_seen[key] = ts
                all_entries.append((path, preamble, entries, idx, entry))

        candidates = [item for item in all_entries if should_rescore(item[4], now=now)]
        candidates.sort(
            key=lambda x: (
                parse_iso_date(x[4].meta.get("last_scored_at", "")) or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
                parse_iso_date(x[4].meta.get("time", "")) or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc),
            )
        )
        candidates = candidates[: max(args.max_updates, 0)]

        changed_paths: Dict[Path, Tuple[str, List[MemoryEntry]]] = {path: (preamble, entries) for path, preamble, entries in bundles}
        updated = 0
        for path, _, entries, idx, entry in candidates:
            new_importance, signals, tags, scope, durability = compute_score(
                entry=entry,
                concept_counts=concept_counts,
                concept_first_seen=concept_first_seen,
                aliases=aliases,
                now=now,
                half_life_days=max(args.half_life_days, 1),
                alpha=clamp(args.alpha, 0.01, 1.0),
            )
            target = entries[idx]
            target.meta["importance"] = f"{new_importance:.2f}"
            target.meta["tags"] = str(tags)
            target.meta["scope"] = scope
            target.meta["durability"] = durability
            target.meta["last_scored_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if "valid_until" not in target.meta:
                target.meta["valid_until"] = "none"
            target.meta["score_goal"] = f"{signals['goal_relevance']:.4f}"
            target.meta["score_recurrence"] = f"{signals['recurrence']:.4f}"
            target.meta["score_future"] = f"{signals['future_utility']:.4f}"
            target.meta["score_preference"] = f"{signals['preference_signal']:.4f}"
            target.meta["score_novelty"] = f"{signals['novelty']:.4f}"
            updated += 1

        if not args.dry_run:
            for path, (preamble, entries) in changed_paths.items():
                write_memory_file(path, preamble, entries)
            checkpoint_payload = {
                "last_run_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "updated": updated,
                "max_updates": args.max_updates,
                "window_days": args.window_days,
                "alias_file": str(alias_path),
            }
            atomic_write_text(checkpoint_path, json.dumps(checkpoint_payload, indent=2) + "\n", encoding="utf-8")

        print(
            "importance_score "
            f"window_days={args.window_days} "
            f"max_updates={args.max_updates} "
            f"candidates={len(candidates)} "
            f"updated={updated}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
