"""Classification engine for applying drift detection results.

Processes classification results and applies them to memory entries,
updating statuses and creating relationship metadata.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_lib import MemoryEntry, write_memory_file
from candidate_generator import CandidatePair, SemanticEntry
from llm_contradiction_client import ContradictionResult, RelationType


@dataclass
class ClassificationAction:
    """An action to be taken based on classification."""
    timestamp: str
    action_type: str  # SUPERSEDES, REFINES, REINFORCES, UNRELATED
    newer_id: str
    older_id: str
    newer_content: str
    older_content: str
    confidence: float
    reasoning: str
    applied: bool = False
    error: Optional[str] = None


@dataclass
class ClassificationReport:
    """Report of classification results."""
    total_evaluated: int = 0
    actions: List[ClassificationAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    by_relation: Dict[str, int] = field(default_factory=dict)
    files_modified: Set[Path] = field(default_factory=set)
    
    def record_relation(self, relation: str) -> None:
        """Record occurrence of a relation type."""
        self.by_relation[relation] = self.by_relation.get(relation, 0) + 1
    
    def to_log_lines(self) -> List[str]:
        """Convert actions to log lines for drift-log.md."""
        lines = []
        for action in self.actions:
            if action.action_type == "SUPERSEDES":
                lines.append(
                    f"- {action.timestamp} SUPERSEDES new=mem:{action.newer_id} "
                    f"old=mem:{action.older_id} conf={action.confidence:.2f}"
                )
            elif action.action_type in ("REFINES", "REINFORCES"):
                lines.append(
                    f"- {action.timestamp} {action.action_type} "
                    f"new=mem:{action.newer_id} old=mem:{action.older_id} "
                    f"conf={action.confidence:.2f}"
                )
        return lines
    
    def summary(self) -> str:
        """Generate a summary string."""
        parts = [
            f"evaluated={self.total_evaluated}",
            f"actions={len(self.actions)}",
            f"errors={len(self.errors)}",
        ]
        for relation, count in sorted(self.by_relation.items()):
            parts.append(f"{relation.lower()}={count}")
        return " ".join(parts)


class ClassificationEngine:
    """Engine for processing classification results and applying changes.
    
    Handles:
    - Applying SUPERSEDES relations (mark old as historical, link new to old)
    - Tracking REFINES and REINFORCES (logging only)
    - Batch updating memory files
    - Generating drift log entries
    """
    
    def __init__(
        self,
        workspace: Path,
        min_confidence: float = 0.5,
        dry_run: bool = False,
        verbose: bool = False,
    ):
        self.workspace = workspace
        self.min_confidence = min_confidence
        self.dry_run = dry_run
        self.verbose = verbose
        self.report = ClassificationReport()
    
    def classify_pair(
        self,
        candidate: CandidatePair,
        result: ContradictionResult,
        now: dt.datetime | None = None,
    ) -> Optional[ClassificationAction]:
        """Classify a candidate pair and create an action.
        
        Args:
            candidate: The candidate pair being evaluated
            result: The contradiction detection result
            now: Current timestamp
            
        Returns:
            ClassificationAction or None if below confidence threshold
        """
        if now is None:
            now = dt.datetime.now(dt.timezone.utc)
        
        self.report.total_evaluated += 1
        
        # Record the relation type
        relation_name = result.relation.value
        self.report.record_relation(relation_name)
        
        # Skip if confidence is too low
        if result.confidence < self.min_confidence:
            if self.verbose:
                self.report.errors.append(
                    f"Low confidence for {candidate.entry_a.entry_id}:{candidate.entry_b.entry_id}: {result.confidence:.2f}"
                )
            return None
        
        # Determine which entry is newer
        if candidate.entry_a.timestamp >= candidate.entry_b.timestamp:
            newer = candidate.entry_a
            older = candidate.entry_b
        else:
            newer = candidate.entry_b
            older = candidate.entry_a
        
        # Create action
        action = ClassificationAction(
            timestamp=now.date().isoformat(),
            action_type=relation_name,
            newer_id=newer.entry_id,
            older_id=older.entry_id,
            newer_content=newer.content,
            older_content=older.content,
            confidence=result.confidence,
            reasoning=result.reasoning,
        )
        
        return action
    
    def find_and_update_entry(
        self,
        entry_id: str,
        file_path: Path,
        updates: Dict[str, str],
    ) -> bool:
        """Find an entry in a file and apply updates to its metadata.
        
        Args:
            entry_id: The ID of the entry to find
            file_path: Path to the memory file
            updates: Dict of metadata fields to update
            
        Returns:
            True if entry was found and updated
        """
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from memory_lib import parse_memory_file, write_memory_file
        
        if not file_path.exists():
            return False
        
        try:
            preamble, entries = parse_memory_file(file_path)
            found = False
            
            for entry in entries:
                if entry.entry_id == entry_id:
                    entry.meta.update(updates)
                    found = True
                    break
            
            if found and not self.dry_run:
                write_memory_file(file_path, preamble, entries)
                self.report.files_modified.add(file_path)
            
            return found
            
        except Exception as e:
            if self.verbose:
                print(f"Error updating {file_path}: {e}")
            return False
    
    def apply_supersedes(
        self,
        action: ClassificationAction,
    ) -> bool:
        """Apply a SUPERSEDES relationship to memory files.
        
        Marks the older entry as historical and links the newer entry to it.
        
        Args:
            action: The SUPERSEDES action to apply
            
        Returns:
            True if successfully applied
        """
        if self.dry_run:
            action.applied = True
            return True
        
        try:
            # Scan semantic files to find entries
            semantic_dir = self.workspace / "memory" / "semantic"
            older_file: Optional[Path] = None
            newer_file: Optional[Path] = None
            
            for md_file in semantic_dir.glob("*.md"):
                preamble, entries = parse_memory_file(md_file)
                for entry in entries:
                    if entry.entry_id == action.older_id:
                        older_file = md_file
                    elif entry.entry_id == action.newer_id:
                        newer_file = md_file
                    
                    if older_file and newer_file:
                        break
                if older_file and newer_file:
                    break
            
            success = True
            
            # Update older entry to historical
            if older_file:
                if not self.find_and_update_entry(
                    action.older_id,
                    older_file,
                    {"status": "historical"}
                ):
                    success = False
                    action.error = f"Could not find older entry {action.older_id}"
            else:
                success = False
                action.error = f"Could not locate file for older entry {action.older_id}"
            
            # Update newer entry with supersedes link
            if newer_file:
                if not self.find_and_update_entry(
                    action.newer_id,
                    newer_file,
                    {"supersedes": f"mem:{action.older_id}"}
                ):
                    success = False
                    if action.error:
                        action.error += f"; could not update newer entry {action.newer_id}"
                    else:
                        action.error = f"Could not find newer entry {action.newer_id}"
            else:
                success = False
                if action.error:
                    action.error += f"; could not locate file for newer entry {action.newer_id}"
                else:
                    action.error = f"Could not locate file for newer entry {action.newer_id}"
            
            action.applied = success
            return success
            
        except Exception as e:
            action.error = str(e)
            return False
    
    def apply_action(self, action: ClassificationAction) -> bool:
        """Apply a classification action.
        
        Args:
            action: The action to apply
            
        Returns:
            True if successfully applied
        """
        if action.action_type == "SUPERSEDES":
            return self.apply_supersedes(action)
        elif action.action_type in ("REFINES", "REINFORCES"):
            # These are tracked but don't modify entries
            action.applied = True
            return True
        else:
            # UNRELATED - no action needed
            action.applied = True
            return True
    
    def process_batch(
        self,
        classifications: List[Tuple[CandidatePair, ContradictionResult]],
        now: dt.datetime | None = None,
    ) -> ClassificationReport:
        """Process a batch of classifications.
        
        Args:
            classifications: List of (candidate, result) tuples
            now: Current timestamp
            
        Returns:
            ClassificationReport with results
        """
        if now is None:
            now = dt.datetime.now(dt.timezone.utc)
        
        # Reset report
        self.report = ClassificationReport()
        
        # Process each classification
        for candidate, result in classifications:
            action = self.classify_pair(candidate, result, now)
            
            if action:
                self.report.actions.append(action)
                
                # Apply the action
                success = self.apply_action(action)
                
                if not success and action.error:
                    self.report.errors.append(
                        f"Failed to apply {action.action_type} for {action.newer_id}:{action.older_id}: {action.error}"
                    )
        
        return self.report


def create_default_engine(
    workspace: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> ClassificationEngine:
    """Create an engine with sensible defaults."""
    return ClassificationEngine(
        workspace=workspace,
        min_confidence=0.5,
        dry_run=dry_run,
        verbose=verbose,
    )
