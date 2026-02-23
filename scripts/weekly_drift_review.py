#!/usr/bin/env python3
"""Run weekly semantic drift review and soft-forgetting transitions.

This script uses an LLM-based approach for contradiction detection with
fallback to heuristic classification when LLM is unavailable.

Feature flags:
- --use-llm: Enable LLM-based classification (default: True)
- --fallback-on-error: Use heuristic fallback if LLM fails (default: True)
- --min-confidence: Minimum confidence threshold for actions (default: 0.5)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from memory_lib import (
    MemoryEntry,
    atomic_write_text,
    ensure_workspace_layout,
    file_lock,
    parse_iso_date,
    parse_memory_file,
    write_memory_file,
)

# Import new LLM-based components
try:
    from candidate_generator import (
        ContradictionCandidateGenerator,
        CandidatePair,
        SemanticEntry,
    )
    from llm_contradiction_client import (
        LLMContradictionClient,
        ContradictionResult,
        RelationType,
    )
    from classification_engine import (
        ClassificationEngine,
        ClassificationAction,
        create_default_engine,
    )
    NEW_COMPONENTS_AVAILABLE = True
    IMPORT_ERROR = None
except ImportError as e:
    NEW_COMPONENTS_AVAILABLE = False
    IMPORT_ERROR = str(e)


# Legacy heuristic classification (kept for backward compatibility)
SUPERSEDE_HINTS = [
    "no longer",
    "replaced",
    "supersede",
    "superseded",
    "instead",
    "changed to",
    "moved from",
    "switched to",
    "switched from",
    "switched",
    "changed",
    "moved",
    "updated",
    "migrated",
    "deprecated",
    "outdated",
    "obsolete",
]


def classify_relation_heuristic(newer: MemoryEntry, older: MemoryEntry) -> str:
    """
    Classify the relationship between a newer and older memory entry.
    
    Uses Jaccard similarity on token sets combined with hint word detection.
    Lowered SUPERSEDES threshold from 0.20 to 0.05 because contradictions
    naturally have low token overlap (they express different information).
    
    This is the legacy heuristic method kept for backward compatibility.
    """
    from memory_lib import jaccard_similarity
    
    sim = jaccard_similarity(newer.token_set(), older.token_set())
    body = newer.body.lower()
    
    # SUPERSEDES: Contradiction/overrides - lowered threshold from 0.20 to 0.05
    # because contradictions naturally have low token overlap
    if sim >= 0.05 and any(hint in body for hint in SUPERSEDE_HINTS):
        return "SUPERSEDES"
    if sim >= 0.85:
        return "REINFORCES"
    if sim >= 0.55:
        return "REFINES"
    return "UNRELATED"


def load_semantic_entries(workspace: Path) -> List[Tuple[Path, str, List[MemoryEntry]]]:
    """Load all semantic memory entries from the workspace."""
    semantic_dir = workspace / "memory" / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    items: List[Tuple[Path, str, List[MemoryEntry]]] = []
    for path in sorted(semantic_dir.glob("*.md")):
        preamble, entries = parse_memory_file(path)
        items.append((path, preamble, entries))
    return items


def append_drift_log(workspace: Path, lines: List[str], dry_run: bool) -> None:
    """Append actions to the drift log."""
    if not lines:
        return
    path = workspace / "memory" / "drift-log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip() + "\n\n"
    payload = existing + "\n".join(lines).rstrip() + "\n"
    if not dry_run:
        atomic_write_text(path, payload, encoding="utf-8")


def update_checkpoint(workspace: Path, timestamp: str, dry_run: bool) -> None:
    """Update the checkpoint file with the last run timestamp."""
    checkpoint_path = workspace / "memory" / "state" / "drift-review-checkpoint.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    
    checkpoint = {
        "last_run": timestamp,
        "version": "2.0",  # LLM-based version
    }
    
    if not dry_run:
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2),
            encoding="utf-8"
        )


def run_llm_based_review(
    workspace: Path,
    window_days: int,
    dry_run: bool,
    verbose: bool,
    min_confidence: float,
    llm_timeout: float,
    fallback_on_error: bool,
    max_candidates: int = 200,
) -> Tuple[int, Dict[str, int], List[str]]:
    """
    Run the LLM-based drift review.
    
    Args:
        workspace: Path to workspace
        window_days: Days to look back for "recent" entries
        dry_run: If True, don't write changes
        verbose: If True, print detailed output
        min_confidence: Minimum confidence for classification
        llm_timeout: Timeout for LLM requests
        fallback_on_error: Use heuristic fallback on LLM error
        max_candidates: Maximum candidate pairs to evaluate
        
    Returns:
        Tuple of (changed_count, relation_counts, log_lines)
    """
    now = dt.datetime.now(dt.timezone.utc)
    
    # Initialize components
    generator = ContradictionCandidateGenerator(
        workspace_path=workspace,
        recent_days=window_days,
        max_candidates=max_candidates,
    )
    
    client = LLMContradictionClient(timeout=llm_timeout)
    engine = create_default_engine(
        workspace=workspace,
        dry_run=dry_run,
        verbose=verbose,
    )
    engine.min_confidence = min_confidence
    
    # Generate candidates
    candidates = generator.generate_candidates(days_back=window_days * 2)
    
    if verbose:
        print(f"Generated {len(candidates)} candidate pairs for review")
    
    if not candidates:
        # Empty candidate list - skip gracefully
        if verbose:
            print("No candidates to evaluate, skipping")
        return 0, {"UNRELATED": 0}, []
    
    # Check LLM availability
    llm_available = client.is_available()
    if verbose:
        print(f"LLM available: {llm_available}")
    
    if not llm_available and not fallback_on_error:
        print("ERROR: LLM unavailable and fallback disabled")
        return 0, {}, ["ERROR: LLM unavailable"]
    
    # Classify each candidate
    classifications: List[Tuple[CandidatePair, ContradictionResult]] = []
    
    for i, candidate in enumerate(candidates):
        try:
            # Determine which entry is newer
            if candidate.entry_a.timestamp >= candidate.entry_b.timestamp:
                newer = candidate.entry_a
                older = candidate.entry_b
            else:
                newer = candidate.entry_b
                older = candidate.entry_a
            
            result = client.detect_contradiction(
                newer_body=newer.content,
                older_body=older.content,
                newer_tags=newer.tags,
                older_tags=older.tags,
            )
            
            # Handle parse errors - log and continue
            if result.error and not result.success:
                if verbose:
                    print(f"Warning: Parse error for candidate {i}: {result.error}")
                # Still use the result if we got one
            
            classifications.append((candidate, result))
            
        except Exception as e:
            # Timeout or other error - mark for retry next run
            if verbose:
                print(f"Error classifying candidate {i}: {e}")
            
            if fallback_on_error:
                # Create a fallback result
                fallback_result = ContradictionResult(
                    relation=RelationType.UNRELATED,
                    confidence=0.0,
                    reasoning=f"Fallback due to error: {e}",
                    error=str(e),
                )
                classifications.append((candidate, fallback_result))
    
    # Process classifications
    report = engine.process_batch(classifications, now)
    
    # Generate log lines
    log_lines = report.to_log_lines()
    
    # Count relations
    relation_counts = report.by_relation.copy()
    
    # Count actual changes (SUPERSEDES actions applied)
    changed = sum(1 for a in report.actions if a.action_type == "SUPERSEDES" and a.applied)
    
    if verbose:
        print(f"Classification complete: {report.summary()}")
        if report.errors:
            print(f"Errors: {len(report.errors)}")
            for err in report.errors[:5]:  # Show first 5
                print(f"  - {err}")
    
    return changed, relation_counts, log_lines


def run_legacy_review(
    workspace: Path,
    window_days: int,
    dry_run: bool,
    verbose: bool,
) -> Tuple[int, Dict[str, int], List[str]]:
    """
    Run the legacy heuristic-based drift review.
    
    This maintains backward compatibility with the old system.
    """
    bundles = load_semantic_entries(workspace)
    
    all_entries: List[Tuple[Path, MemoryEntry]] = []
    for path, _, entries in bundles:
        for e in entries:
            all_entries.append((path, e))
    
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=window_days)
    recent: List[Tuple[Path, MemoryEntry]] = []
    older: List[Tuple[Path, MemoryEntry]] = []
    
    for path, entry in all_entries:
        ts = parse_iso_date(entry.meta.get("time", "")) or now
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        if entry.meta.get("status", "active") == "historical":
            continue
        if ts >= cutoff:
            recent.append((path, entry))
        else:
            older.append((path, entry))
    
    by_file: Dict[Path, Tuple[str, List[MemoryEntry]]] = {}
    for path, preamble, entries in bundles:
        by_file[path] = (preamble, entries)
    
    actions: List[str] = []
    changed = 0
    relation_counts = defaultdict(int)
    
    for _, new_entry in recent:
        new_tags = set(new_entry.tags())
        for _, old_entry in older:
            if old_entry.meta.get("status", "active") == "historical":
                continue
            old_tags = set(old_entry.tags())
            if new_tags and old_tags and not (new_tags & old_tags):
                continue
            relation = classify_relation_heuristic(new_entry, old_entry)
            relation_counts[relation] += 1
            if relation == "SUPERSEDES":
                old_entry.meta["status"] = "historical"
                new_entry.meta["supersedes"] = f"mem:{old_entry.entry_id}"
                changed += 1
                actions.append(
                    f"- {now.date().isoformat()} SUPERSEDES new=mem:{new_entry.entry_id} "
                    f"old=mem:{old_entry.entry_id}"
                )
    
    if changed and not dry_run:
        for path, (preamble, entries) in by_file.items():
            write_memory_file(path, preamble, entries)
    
    return changed, dict(relation_counts), actions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weekly semantic drift review and soft-forgetting transitions."
    )
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--window-days", type=int, default=7, help="Days to look back for recent entries")
    parser.add_argument("--dry-run", action="store_true", help="Don't write any changes")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--log-model", default="", help="Model identifier used for this run (for audit trail)")
    
    # New LLM-based options
    parser.add_argument("--use-llm", dest="use_llm", action="store_true", default=True, help="Use LLM-based classification (default: True)")
    parser.add_argument("--no-use-llm", dest="use_llm", action="store_false", help="Disable LLM, use legacy heuristics")
    parser.add_argument("--fallback-on-error", dest="fallback_on_error", action="store_true", default=True, help="Fallback to heuristics on LLM error")
    parser.add_argument("--no-fallback", dest="fallback_on_error", action="store_false", help="Disable fallback on error")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold (0.0-1.0)")
    parser.add_argument("--llm-timeout", type=float, default=30.0, help="LLM request timeout in seconds")
    parser.add_argument("--max-candidates", type=int, default=200, help="Maximum candidate pairs to evaluate")
    
    args = parser.parse_args()
    
    workspace = Path(args.workspace).resolve()
    ensure_workspace_layout(workspace)
    
    lock_path = workspace / "memory" / "locks" / "cadence-memory.lock"
    with file_lock(lock_path) as locked:
        if not locked:
            print("weekly_drift_review skipped=lock_held")
            return 0
        
        # Determine which mode to use
        use_legacy = not args.use_llm or not NEW_COMPONENTS_AVAILABLE
        
        if use_legacy:
            if args.verbose:
                if not args.use_llm:
                    print("Using legacy heuristic classification (--use-llm disabled)")
                elif not NEW_COMPONENTS_AVAILABLE:
                    print(f"Using legacy heuristic classification (components unavailable: {IMPORT_ERROR})")
            
            changed, relation_counts, log_lines = run_legacy_review(
                workspace=workspace,
                window_days=args.window_days,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            model_str = "mode=legacy"
        else:
            if args.verbose:
                print("Using LLM-based classification")
            
            changed, relation_counts, log_lines = run_llm_based_review(
                workspace=workspace,
                window_days=args.window_days,
                dry_run=args.dry_run,
                verbose=args.verbose,
                min_confidence=args.min_confidence,
                llm_timeout=args.llm_timeout,
                fallback_on_error=args.fallback_on_error,
                max_candidates=args.max_candidates,
            )
            model_str = f"mode=llm model={args.log_model}" if args.log_model else "mode=llm"
        
        # Append to drift log
        append_drift_log(workspace, log_lines, dry_run=args.dry_run)
        
        # Update checkpoint
        now = dt.datetime.now(dt.timezone.utc)
        update_checkpoint(workspace, now.isoformat(), dry_run=args.dry_run)
        
        # Print summary
        relation_parts = []
        for relation in ["SUPERSEDES", "REFINES", "REINFORCES", "UNRELATED"]:
            count = relation_counts.get(relation, 0)
            relation_parts.append(f"{relation.lower()}={count}")
        
        print(
            "weekly_drift_review "
            f"{' '.join(relation_parts)} "
            f"changed={changed} "
            f"{model_str}"
        )
        
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
