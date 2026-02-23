#!/usr/bin/env python3
"""Candidate pair generation for contradiction detection.

This module efficiently reduces the O(n²) search space for contradiction detection
by using smart filtering: semantic similarity, temporal windows, tag overlap,
and diversity enhancement.

Target: Reduce ~20,000 pairs to ~200 candidates (99% reduction)
        while maintaining >95% recall of true contradictions.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

# Import memory_lib for entry parsing
import sys
sys.path.insert(0, str(Path(__file__).parent))
from memory_lib import MemoryEntry, parse_memory_file, parse_iso_date, jaccard_similarity, normalize_text


def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute simple token-based similarity between two texts."""
    tokens_a = set(normalize_text(text_a).split())
    tokens_b = set(normalize_text(text_b).split())
    return jaccard_similarity(tokens_a, tokens_b)


@dataclass
class SemanticEntry:
    """Normalized semantic entry for contradiction detection."""
    entry_id: str
    content: str
    timestamp: dt.datetime
    tags: List[str]
    meta: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def date(self) -> dt.date:
        return self.timestamp.date()
    
    def tag_set(self) -> Set[str]:
        return set(t.lower() for t in self.tags)


@dataclass  
class CandidatePair:
    """A candidate pair for contradiction detection."""
    entry_a: SemanticEntry
    entry_b: SemanticEntry
    prefilter_score: float
    match_reasons: List[str] = field(default_factory=list)


class ContradictionCandidateGenerator:
    """Generate candidate pairs for contradiction detection using smart filtering.
    
    Filtering pipeline:
    1. Temporal window filter - only compare recent vs older entries
    2. Tag overlap filter - entries must share at least 1 tag
    3. Semantic prefilter - use qmd to find similar entries (similarity > 0.3)
    4. Diversity enhancement - ensure variety in candidates
    """
    
    def __init__(
        self,
        workspace_path: Optional[Path] = None,
        similarity_threshold: float = 0.0,
        max_candidates: int = 400,
        recent_days: int = 7,
        older_days: int = 30
    ):
        self.workspace = workspace_path or Path(os.environ.get("OPENCLAW_WORKSPACE", "/Users/celeste/.openclaw/workspace"))
        self.similarity_threshold = similarity_threshold
        self.max_candidates = max_candidates
        self.recent_days = recent_days
        self.older_days = older_days
        self._qmd_cache_max_size = 500  # LRU eviction limit
        
        # Cache for qmd results to avoid repeated queries (LRU with size limit)
        self._qmd_cache: OrderedDict[str, List[Tuple[str, float]]] = OrderedDict()
        
    def generate_candidates(
        self,
        semantic_entries: Optional[List[SemanticEntry]] = None,
        days_back: int = 30,
        reference_date: Optional[dt.datetime] = None,
        sliding_window: bool = False
    ) -> List[CandidatePair]:
        """Generate candidate pairs for contradiction detection.
        
        Args:
            semantic_entries: List of semantic entries (or None to load from files)
            days_back: How many days back to look for older entries
            reference_date: Date to use as "now" (defaults to actual current time)
                           Useful for testing with historical data
            sliding_window: If True, compare all pairs where newer is after older
                           (for comprehensive historical analysis)
            
        Returns:
            List of candidate pairs sorted by prefilter_score (highest first)
        """
        self._sliding_window = sliding_window
        """Generate candidate pairs for contradiction detection.
        
        Args:
            semantic_entries: List of semantic entries (or None to load from files)
            days_back: How many days back to look for older entries
            reference_date: Date to use as "now" (defaults to actual current time)
                           Useful for testing with historical data
            
        Returns:
            List of candidate pairs sorted by prefilter_score (highest first)
        """
        start_time = time.time()
        
        # Load entries if not provided
        if semantic_entries is None:
            semantic_entries = self._load_semantic_entries()
        
        print(f"Loaded {len(semantic_entries)} semantic entries")
        
        # Determine reference date for temporal filtering
        if reference_date is None:
            if semantic_entries:
                most_recent = max(e.timestamp for e in semantic_entries)
                now = dt.datetime.now(dt.timezone.utc)
                age_days = (now - most_recent).days
                
                if age_days > 30:
                    # Historical data: most recent is old, use it as reference
                    reference_date = most_recent + dt.timedelta(days=1)
                    print(f"Using historical reference date: {reference_date.date()}")
                elif age_days < -1:
                    # Future data: most recent is in the future, use it as reference
                    reference_date = most_recent + dt.timedelta(days=1)
                    print(f"Using future-test reference date: {reference_date.date()}")
                else:
                    reference_date = now
            else:
                reference_date = dt.datetime.now(dt.timezone.utc)
        
        # Calculate what O(n²) would be
        n = len(semantic_entries)
        all_pairs_count = (n * (n - 1)) // 2
        print(f"O(n²) would require {all_pairs_count:,} comparisons")
        
        # Store reference date for temporal filtering
        self._reference_date = reference_date
        
        # Step 1: Temporal window filter
        recent_entries, older_entries = self._temporal_window_filter(semantic_entries, days_back)
        print(f"Temporal filter: {len(recent_entries)} recent, {len(older_entries)} older entries")
        
        # Step 2: Tag overlap filter - find potential pairs
        tag_filtered_pairs = self._tag_overlap_filter(recent_entries, older_entries)
        print(f"Tag overlap filter: {len(tag_filtered_pairs)} potential pairs")
        
        # Step 3: Semantic prefilter using qmd
        semantic_pairs = self._semantic_prefilter(tag_filtered_pairs)
        print(f"Semantic prefilter: {len(semantic_pairs)} pairs with similarity >= {self.similarity_threshold}")
        
        # Step 4: Diversity enhancement
        diverse_candidates = self._diversity_enhancement(semantic_pairs)
        print(f"Diversity enhancement: {len(diverse_candidates)} final candidates")
        
        # Sort by prefilter score (highest first)
        diverse_candidates.sort(key=lambda x: x.prefilter_score, reverse=True)
        
        elapsed = time.time() - start_time
        print(f"\nPerformance: {elapsed:.2f}s to generate {len(diverse_candidates)} candidates")
        print(f"Reduction: {all_pairs_count:,} → {len(diverse_candidates)} ({100*(1-len(diverse_candidates)/max(all_pairs_count,1)):.1f}% reduction)")
        
        return diverse_candidates
    
    def _load_semantic_entries(self) -> List[SemanticEntry]:
        """Load semantic entries from memory files."""
        entries = []
        semantic_dir = self.workspace / "memory" / "semantic"
        
        if not semantic_dir.exists():
            print(f"Warning: Semantic directory not found: {semantic_dir}")
            return entries
        
        for md_file in semantic_dir.glob("*.md"):
            try:
                preamble, mem_entries = parse_memory_file(md_file)
                for mem_entry in mem_entries:
                    # Parse timestamp
                    ts = parse_iso_date(mem_entry.meta.get("time", ""))
                    if ts is None:
                        continue
                    
                    # Parse tags
                    tags = mem_entry.tags()
                    
                    entry = SemanticEntry(
                        entry_id=mem_entry.entry_id,
                        content=mem_entry.body,
                        timestamp=ts,
                        tags=tags,
                        meta=dict(mem_entry.meta)
                    )
                    entries.append(entry)
            except Exception as e:
                print(f"Warning: Failed to parse {md_file}: {e}")
        
        return entries
    
    def _temporal_window_filter(
        self,
        entries: List[SemanticEntry],
        days_back: int
    ) -> Tuple[List[SemanticEntry], List[SemanticEntry]]:
        """Split entries into recent and older based on temporal windows.
        
        Recent: Last `self.recent_days` days (or all entries if sliding_window=True)
        Older: From `self.recent_days` to `days_back` days ago
        
        In sliding_window mode, returns (all_entries, all_entries) to compare all pairs.
        """
        # Use reference date if set, otherwise use current time
        reference = getattr(self, '_reference_date', None) or dt.datetime.now(dt.timezone.utc)
        
        # Sliding window mode: compare all pairs
        if getattr(self, '_sliding_window', False):
            return entries, entries
        
        # Standard mode: recent vs older
        recent_cutoff = reference - dt.timedelta(days=self.recent_days)
        older_cutoff = reference - dt.timedelta(days=days_back)
        
        recent_entries = []
        older_entries = []
        
        for entry in entries:
            if entry.timestamp >= recent_cutoff:
                recent_entries.append(entry)
            elif entry.timestamp >= older_cutoff:
                older_entries.append(entry)
        
        return recent_entries, older_entries
    
    # Domain keywords for catching related entries without exact tag overlap
    DOMAIN_KEYWORDS = {
        'editor': ['editor', 'ide', 'vscode', 'vs code', 'sublime', 'vim', 'neovim', 'emacs', 'cursor', 'nano'],
        'terminal': ['terminal', 'shell', 'iterm', 'warp', 'alacritty', 'tmux', 'zsh', 'bash'],
        'language': ['python', 'typescript', 'javascript', 'rust', 'go', 'java', 'cpp', 'c++', 'language'],
        'cloud': ['aws', 'gcp', 'azure', 'cloud', 'hosting', 'serverless', 'lambda'],
        'task_management': ['todoist', 'obsidian', 'notion', 'task', 'todo', 'reminder'],
        'communication': ['slack', 'discord', 'email', 'async', 'chat', 'message', 'communication'],
        'desk': ['desk', 'standing', 'sitting', 'ergonomic', 'chair', 'workspace'],
        'music': ['music', 'spotify', 'silence', 'headphones', 'audio', 'sound', 'quiet'],
        'schedule': ['morning', 'evening', 'night', 'schedule', 'routine', 'time', 'wake'],
    }
    
    def _detect_domains(self, entry: SemanticEntry) -> Set[str]:
        """Detect domains from entry content and tags."""
        domains = set()
        content_lower = entry.content.lower()
        all_tags = ' '.join(entry.tags).lower()
        
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content_lower or keyword in all_tags:
                    domains.add(domain)
                    break
        
        return domains
    
    def _tag_overlap_filter(
        self,
        recent_entries: List[SemanticEntry],
        older_entries: List[SemanticEntry]
    ) -> List[Tuple[SemanticEntry, SemanticEntry, float]]:
        """Filter pairs that share at least one tag OR domain.
        
        Returns list of (entry_a, entry_b, base_score) tuples where entry_a is newer than entry_b.
        """
        pairs = []
        
        # Check if we're in sliding window mode (same lists)
        sliding_mode = recent_entries is older_entries
        
        if sliding_mode:
            # In sliding window mode, we need to compare all pairs where a is newer than b
            all_entries = recent_entries
            
            # Build tag index for all entries
            tag_to_entries: Dict[str, List[SemanticEntry]] = {}
            for entry in all_entries:
                for tag in entry.tag_set():
                    tag_to_entries.setdefault(tag, []).append(entry)
            
            # Build domain index
            domain_to_entries: Dict[str, List[SemanticEntry]] = {}
            for entry in all_entries:
                domains = self._detect_domains(entry)
                for domain in domains:
                    domain_to_entries.setdefault(domain, []).append(entry)
            
            # For each entry, find older entries with overlapping tags or domains
            for entry_a in all_entries:
                entry_a_tags = entry_a.tag_set()
                entry_a_domains = self._detect_domains(entry_a)
                
                candidates: Dict[str, Tuple[SemanticEntry, Set[str], Set[str]]] = {}
                
                # Tag-based matches
                for tag in entry_a_tags:
                    for entry_b in tag_to_entries.get(tag, []):
                        # Only include if entry_a is newer than entry_b
                        if entry_a.timestamp > entry_b.timestamp:
                            if entry_b.entry_id not in candidates:
                                candidates[entry_b.entry_id] = (entry_b, set(), set())
                            candidates[entry_b.entry_id][1].add(tag)
                
                # Domain-based matches
                for domain in entry_a_domains:
                    for entry_b in domain_to_entries.get(domain, []):
                        if entry_a.timestamp > entry_b.timestamp:
                            if entry_b.entry_id not in candidates:
                                candidates[entry_b.entry_id] = (entry_b, set(), set())
                            candidates[entry_b.entry_id][2].add(domain)
                
                for entry_b, shared_tags, shared_domains in candidates.values():
                    all_tags = entry_a_tags | entry_b.tag_set()
                    if shared_tags:
                        overlap_score = 0.5 + 0.5 * (len(shared_tags) / max(len(all_tags), 1))
                    elif shared_domains:
                        overlap_score = 0.3 * (len(shared_domains) / max(len(entry_a_domains | self._detect_domains(entry_b)), 1))
                    else:
                        overlap_score = 0.0
                    
                    if overlap_score > 0:
                        pairs.append((entry_a, entry_b, overlap_score))
        
        else:
            # Standard mode: recent vs older
            # Build tag index for older entries
            tag_to_older: Dict[str, List[SemanticEntry]] = {}
            for entry in older_entries:
                for tag in entry.tag_set():
                    tag_to_older.setdefault(tag, []).append(entry)
            
            # Build domain index for older entries
            domain_to_older: Dict[str, List[SemanticEntry]] = {}
            for entry in older_entries:
                domains = self._detect_domains(entry)
                for domain in domains:
                    domain_to_older.setdefault(domain, []).append(entry)
            
            # For each recent entry, find older entries with overlapping tags or domains
            for recent in recent_entries:
                recent_tags = recent.tag_set()
                recent_domains = self._detect_domains(recent)
                
                candidates: Dict[str, Tuple[SemanticEntry, Set[str], Set[str]]] = {}
                
                # Tag-based matches
                for tag in recent_tags:
                    for older in tag_to_older.get(tag, []):
                        if older.entry_id not in candidates:
                            candidates[older.entry_id] = (older, set(), set())
                        candidates[older.entry_id][1].add(tag)
                
                # Domain-based matches
                for domain in recent_domains:
                    for older in domain_to_older.get(domain, []):
                        if older.entry_id not in candidates:
                            candidates[older.entry_id] = (older, set(), set())
                        candidates[older.entry_id][2].add(domain)
                
                for older, shared_tags, shared_domains in candidates.values():
                    all_tags = recent_tags | older.tag_set()
                    if shared_tags:
                        overlap_score = 0.5 + 0.5 * (len(shared_tags) / max(len(all_tags), 1))
                    elif shared_domains:
                        overlap_score = 0.3 * (len(shared_domains) / max(len(recent_domains | self._detect_domains(older)), 1))
                    else:
                        overlap_score = 0.0
                    
                    if overlap_score > 0:
                        pairs.append((recent, older, overlap_score))
        
        return pairs
    
    def _semantic_prefilter(
        self,
        candidate_pairs: List[Tuple[SemanticEntry, SemanticEntry, float]]
    ) -> List[CandidatePair]:
        """Find semantically similar entries using qmd or local fallback.
        
        Only keeps pairs with similarity >= self.similarity_threshold.
        Optimized version that pre-filters and uses efficient similarity computation.
        """
        results = []
        
        # Pre-filter: if threshold is 0, we can skip individual similarity checks
        # and just use tag score as the prefilter score
        if self.similarity_threshold <= 0:
            for recent, older, tag_score in candidate_pairs:
                combined_score = 0.3 * tag_score  # No semantic bonus when threshold is 0
                
                results.append(CandidatePair(
                    entry_a=recent,
                    entry_b=older,
                    prefilter_score=combined_score,
                    match_reasons=[f"tag_overlap:{tag_score:.3f}", "no_semantic_filter"]
                ))
            return results
        
        # Group by recent entry to batch qmd queries
        by_recent: Dict[str, List[Tuple[SemanticEntry, SemanticEntry, float]]] = {}
        for recent, older, tag_score in candidate_pairs:
            by_recent.setdefault(recent.entry_id, []).append((recent, older, tag_score))
        
        for recent_id, pairs in by_recent.items():
            recent = pairs[0][0]
            
            # Try qmd first for semantic similarity
            similar = self._qmd_find_similar(recent.content, limit=50)
            similar_map = {entry_id: score for entry_id, score in similar}
            
            # If qmd returns no results, use local similarity fallback
            use_local_fallback = len(similar) == 0
            
            for recent, older, tag_score in pairs:
                if use_local_fallback:
                    # Compute local token-based similarity
                    semantic_score = compute_similarity(recent.content, older.content)
                else:
                    semantic_score = similar_map.get(older.entry_id, 0.0)
                
                if semantic_score >= self.similarity_threshold:
                    # Combined score: weighted average of semantic and tag scores
                    combined_score = 0.7 * semantic_score + 0.3 * tag_score
                    
                    reasons = [
                        f"semantic_similarity:{semantic_score:.3f}",
                        f"tag_overlap:{tag_score:.3f}"
                    ]
                    if use_local_fallback:
                        reasons.append("local_fallback")
                    
                    results.append(CandidatePair(
                        entry_a=recent,
                        entry_b=older,
                        prefilter_score=combined_score,
                        match_reasons=reasons
                    ))
        
        return results
    
    def _qmd_find_similar(self, query: str, limit: int = 20) -> List[Tuple[str, float]]:
        """Use qmd to find entries semantically similar to query.
        
        Returns list of (entry_id, similarity_score) tuples.
        """
        # Use SHA256 for stable, collision-resistant cache key
        cache_key = hashlib.sha256(query.encode()).hexdigest()[:32]
        if cache_key in self._qmd_cache:
            # Move to end (most recently used) for LRU
            self._qmd_cache.move_to_end(cache_key)
            return self._qmd_cache[cache_key]
        
        try:
            # Use qmd search command
            cmd = [
                "qmd", "search", query,
                "-c", "openclaw-memory",
                "--limit", str(limit),
                "--json"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                print(f"qmd search failed: {result.stderr}")
                return []
            
            # Parse JSON results - qmd returns an array of results
            matches = []
            try:
                results_array = json.loads(result.stdout)
                if not isinstance(results_array, list):
                    results_array = [results_array]
                
                for data in results_array:
                    if not isinstance(data, dict):
                        continue
                    
                    # Extract score (already 0-1 in qmd)
                    score = data.get("score", 0.0)
                    
                    # Try to find entry_id in file path or snippet content
                    entry_id = self._extract_entry_id(data)
                    
                    if entry_id and score > 0:
                        matches.append((entry_id, score))
            except json.JSONDecodeError as e:
                print(f"JSON parse error: {e}")
            
            # LRU eviction: remove oldest entries if cache is full
            while len(self._qmd_cache) >= self._qmd_cache_max_size:
                self._qmd_cache.popitem(last=False)
            
            self._qmd_cache[cache_key] = matches
            return matches
            
        except subprocess.TimeoutExpired:
            print("qmd search timed out")
            return []
        except FileNotFoundError:
            print("qmd not found in PATH")
            return []
        except Exception as e:
            print(f"qmd search error: {e}")
            return []
    
    def _extract_entry_id(self, data: Dict) -> Optional[str]:
        """Extract entry ID from qmd result data."""
        # Try snippet first (most reliable)
        snippet = data.get("snippet", "")
        match = re.search(r"mem:([a-zA-Z0-9_-]+)", snippet)
        if match:
            return match.group(1)
        
        # Try file path
        file_path = data.get("file", "")
        match = re.search(r"mem:([a-zA-Z0-9_-]+)", file_path)
        if match:
            return match.group(1)
        
        # Try metadata
        if "metadata" in data and "entry_id" in data["metadata"]:
            return data["metadata"]["entry_id"]
        
        return None
    
    def _diversity_enhancement(self, candidates: List[CandidatePair]) -> List[CandidatePair]:
        """Ensure diversity in candidate selection.
        
        Strategies:
        1. Cap candidates per tag pair to avoid over-representing popular domains
        2. Ensure temporal diversity (candidates from different time periods)
        3. Prioritize higher scores when making selections
        """
        if len(candidates) <= self.max_candidates:
            return candidates
        
        # Group by shared tags
        by_tag_combo: Dict[str, List[CandidatePair]] = {}
        for cand in candidates:
            shared_tags = sorted(cand.entry_a.tag_set() & cand.entry_b.tag_set())
            tag_key = "|".join(shared_tags) if shared_tags else "none"
            by_tag_combo.setdefault(tag_key, []).append(cand)
        
        # Select candidates with diversity
        selected = []
        
        # First pass: take top candidates from each tag combo (diversity)
        max_per_combo = max(3, self.max_candidates // len(by_tag_combo))
        for tag_combo, cands in by_tag_combo.items():
            cands.sort(key=lambda x: x.prefilter_score, reverse=True)
            selected.extend(cands[:max_per_combo])
        
        # If still under limit, add more by score
        if len(selected) < self.max_candidates:
            remaining = [c for c in candidates if c not in selected]
            remaining.sort(key=lambda x: x.prefilter_score, reverse=True)
            needed = self.max_candidates - len(selected)
            selected.extend(remaining[:needed])
        
        # If over limit, trim by score
        if len(selected) > self.max_candidates:
            selected.sort(key=lambda x: x.prefilter_score, reverse=True)
            selected = selected[:self.max_candidates]
        
        return selected
    
    def check_known_contradictions(
        self,
        candidates: List[CandidatePair],
        known_pairs: List[Tuple[str, str]]
    ) -> Dict[str, Any]:
        """Check if known contradiction pairs are present in candidates.
        
        Args:
            candidates: Generated candidate pairs
            known_pairs: List of (entry_id_a, entry_id_b) known contradictions
            
        Returns:
            Stats about recall of known contradictions
        """
        candidate_ids = set()
        for cand in candidates:
            pair = tuple(sorted([cand.entry_a.entry_id, cand.entry_b.entry_id]))
            candidate_ids.add(pair)
        
        found = []
        missed = []
        
        for a, b in known_pairs:
            pair = tuple(sorted([a, b]))
            if pair in candidate_ids:
                found.append((a, b))
            else:
                missed.append((a, b))
        
        return {
            "total_known": len(known_pairs),
            "found": len(found),
            "missed": len(missed),
            "recall": len(found) / len(known_pairs) if known_pairs else 0.0,
            "found_pairs": found,
            "missed_pairs": missed
        }


def load_test_data(test_data_path: Path) -> Tuple[List[SemanticEntry], List[Tuple[str, str]]]:
    """Load test data with known contradictions."""
    with open(test_data_path) as f:
        data = json.load(f)
    
    entries = []
    for entry_data in data.get("entries", []):
        # Parse date
        date_str = entry_data.get("date", "")
        try:
            entry_date = dt.date.fromisoformat(date_str)
            timestamp = dt.datetime.combine(entry_date, dt.time.min, dt.timezone.utc)
        except ValueError:
            continue
        
        entry = SemanticEntry(
            entry_id=entry_data.get("id", "").replace("mem:", ""),
            content=entry_data.get("content", ""),
            timestamp=timestamp,
            tags=entry_data.get("tags", []),
            meta=entry_data
        )
        entries.append(entry)
    
    # Extract known contradictions from simulation results if available
    known_pairs = []
    sim_path = test_data_path.parent / "drift_simulation_fixed.json"
    if sim_path.exists():
        with open(sim_path) as f:
            sim_data = json.load(f)
        # contradiction_tracking is a list of contradiction objects
        for ct in sim_data.get("contradiction_tracking", []):
            old_id = ct.get("old_entry_id", "").replace("mem:", "")
            new_id = ct.get("new_entry_id", "").replace("mem:", "")
            if old_id and new_id:
                known_pairs.append((old_id, new_id))
    
    return entries, known_pairs


def main():
    """CLI for testing candidate generation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate contradiction candidates")
    parser.add_argument("--test-data", type=Path, help="Path to test data JSON")
    parser.add_argument("--days-back", type=int, default=30, help="Days back to look")
    parser.add_argument("--max-candidates", type=int, default=400, help="Max candidates")
    parser.add_argument("--similarity-threshold", type=float, default=0.0, help="Semantic similarity threshold")
    parser.add_argument("--sliding-window", action="store_true", help="Use sliding window (all pairs)")
    parser.add_argument("--output", type=Path, help="Output JSON file")
    parser.add_argument("--benchmark", action="store_true", help="Run benchmark mode")
    parser.add_argument("--check-recall", action="store_true", help="Check recall of known contradictions")
    
    args = parser.parse_args()
    
    # Initialize generator
    generator = ContradictionCandidateGenerator(
        similarity_threshold=args.similarity_threshold,
        max_candidates=args.max_candidates
    )
    
    # Load entries
    if args.test_data:
        entries, known_pairs = load_test_data(args.test_data)
        print(f"Loaded {len(entries)} entries from test data")
        print(f"Known contradictions: {len(known_pairs)}")
    else:
        entries = None
        known_pairs = []
    
    # Generate candidates
    candidates = generator.generate_candidates(
        entries, 
        days_back=args.days_back,
        sliding_window=args.sliding_window
    )
    
    # Print summary
    print("\n" + "="*60)
    print("CANDIDATE GENERATION SUMMARY")
    print("="*60)
    print(f"Total candidates: {len(candidates)}")
    
    if candidates:
        scores = [c.prefilter_score for c in candidates]
        print(f"Score range: {min(scores):.3f} - {max(scores):.3f}")
        print(f"Avg score: {sum(scores)/len(scores):.3f}")
        
        # Show top 5
        print("\nTop 5 candidates:")
        for i, cand in enumerate(candidates[:5], 1):
            print(f"  {i}. {cand.entry_a.entry_id[:8]}... vs {cand.entry_b.entry_id[:8]}... "
                  f"(score: {cand.prefilter_score:.3f})")
            shared = cand.entry_a.tag_set() & cand.entry_b.tag_set()
            print(f"     Shared tags: {', '.join(shared) if shared else 'none'}")
            print(f"     A: {cand.entry_a.content[:60]}...")
            print(f"     B: {cand.entry_b.content[:60]}...")
    
    # Check known contradictions
    if known_pairs and (args.check_recall or args.benchmark):
        stats = generator.check_known_contradictions(candidates, known_pairs)
        print(f"\nRecall of known contradictions: {stats['recall']*100:.1f}%")
        print(f"  Found: {stats['found']}/{stats['total_known']}")
        if stats['missed'] > 0:
            print(f"  Missed: {stats['missed']}")
            if len(stats['missed_pairs']) <= 5:
                print("  Missed pairs:")
                for a, b in stats['missed_pairs']:
                    print(f"    {a[:12]}... -> {b[:12]}...")
    
    # Save output if requested
    if args.output:
        output_data = {
            "candidates": [
                {
                    "entry_a": {
                        "id": c.entry_a.entry_id,
                        "content": c.entry_a.content,
                        "date": c.entry_a.date.isoformat(),
                        "tags": c.entry_a.tags
                    },
                    "entry_b": {
                        "id": c.entry_b.entry_id,
                        "content": c.entry_b.content,
                        "date": c.entry_b.date.isoformat(),
                        "tags": c.entry_b.tags
                    },
                    "prefilter_score": c.prefilter_score,
                    "match_reasons": c.match_reasons
                }
                for c in candidates
            ],
            "stats": {
                "total_candidates": len(candidates),
                "similarity_threshold": args.similarity_threshold,
                "max_candidates": args.max_candidates,
                "days_back": args.days_back,
                "sliding_window": args.sliding_window
            }
        }
        
        if known_pairs:
            output_data["stats"]["known_contradictions"] = generator.check_known_contradictions(candidates, known_pairs)
        
        with open(args.output, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nOutput saved to: {args.output}")
    
    # Benchmark mode
    if args.benchmark:
        print("\n" + "="*60)
        print("BENCHMARK MODE")
        print("="*60)
        
        # Run multiple times to get average
        times = []
        for run in range(3):
            start = time.time()
            _ = generator.generate_candidates(entries, days_back=args.days_back, sliding_window=args.sliding_window)
            elapsed = time.time() - start
            times.append(elapsed)
            print(f"Run {run+1}: {elapsed:.3f}s")
        
        print(f"\nAverage time: {sum(times)/len(times):.3f}s")
        print(f"Min: {min(times):.3f}s, Max: {max(times):.3f}s")
        
        # Target checks
        print("\n" + "-"*40)
        print("TARGET VERIFICATION")
        print("-"*40)
        
        # Candidate count
        if len(candidates) <= 300:
            print(f"✓ Candidate count: {len(candidates)} ≤ 300")
        else:
            print(f"✗ Candidate count: {len(candidates)} > 300 (target: ~200)")
        
        # Performance
        avg_time = sum(times)/len(times)
        if avg_time < 5.0:
            print(f"✓ Performance: {avg_time:.3f}s < 5s")
        else:
            print(f"✗ Performance: {avg_time:.3f}s ≥ 5s")
        
        # Reduction rate
        n = len(entries) if entries else 42  # approximate
        all_pairs = (n * (n - 1)) // 2
        reduction = 100 * (1 - len(candidates) / max(all_pairs, 1))
        if reduction >= 95:
            print(f"✓ Reduction: {all_pairs:,} → {len(candidates)} ({reduction:.1f}%)")
        else:
            print(f"✗ Reduction: {reduction:.1f}% (< 95%)")
        
        # Recall
        if known_pairs:
            stats = generator.check_known_contradictions(candidates, known_pairs)
            if stats['recall'] >= 0.95:
                print(f"✓ Recall: {stats['recall']*100:.1f}% ≥ 95%")
            else:
                print(f"✗ Recall: {stats['recall']*100:.1f}% < 95%")
        
        print("-"*40)


if __name__ == "__main__":
    exit(main())
