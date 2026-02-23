#!/usr/bin/env python3
"""LLM-powered contradiction classification client for memory governance.

This module provides an LLM-based classifier for determining relationships
between memory entries: REINFORCES, REFINES, SUPERSEDES, or UNRELATED.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default configuration
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_TIMEOUT = 120  # qwen3:4b can be slow
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_RETRIES = 1  # Retry once on timeout as specified
MAX_CACHE_SIZE = 1000  # LRU eviction when cache exceeds this size
CACHE_TTL_SECONDS = 3600  # 1 hour TTL for cache entries


class LLMContradictionError(Exception):
    """Raised when LLM contradiction classification fails irrecoverably."""
    pass


class LLMUnavailableError(LLMContradictionError):
    """Raised when Ollama LLM is unavailable."""
    pass


@dataclass
class ClassificationResult:
    """Result of classifying a pair of memory entries."""
    relationship: str  # REINFORCES, REFINES, SUPERSEDES, UNRELATED
    confidence: float  # 0.0 to 1.0
    reasoning: str = ""  # Optional explanation
    cached: bool = False  # Whether result came from cache


class LLMContradictionClient:
    """Client for LLM-based contradiction classification between memory entries."""
    
    # Valid relationship types
    VALID_RELATIONSHIPS = {"REINFORCES", "REFINES", "SUPERSEDES", "UNRELATED"}
    
    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT, max_cache_size: int = MAX_CACHE_SIZE):
        """Initialize the LLM contradiction client."""
        self.model = model
        self.timeout = timeout
        self._max_cache_size = max_cache_size
        # Use OrderedDict for LRU eviction - most recently used at end
        self._cache: OrderedDict[str, tuple[ClassificationResult, float]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0
    
    def classify_pair(
        self, 
        memory_a: Dict[str, Any], 
        memory_b: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Classify the relationship between two memory entries."""
        cache_key = self._get_cache_key(memory_a, memory_b)
        
        # Check cache first (with TTL validation)
        current_time = time.time()
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            # Check if entry has expired
            if current_time - timestamp < CACHE_TTL_SECONDS:
                # Move to end (most recently used) for LRU
                self._cache.move_to_end(cache_key)
                self._cache_hits += 1
                return {
                    "relationship": result.relationship,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "cached": True
                }
            else:
                # Expired - remove it
                del self._cache[cache_key]
        
        self._cache_misses += 1
        
        # Build the classification prompt
        prompt = self._build_prompt(memory_a, memory_b)
        
        # Call LLM with retry on timeout
        try:
            response_text = self._call_llm(prompt)
        except LLMUnavailableError:
            raise
        
        # Parse the response
        result = self._parse_response(response_text)
        
        # Cache the result with timestamp and LRU eviction
        cache_result = ClassificationResult(
            relationship=result["relationship"],
            confidence=result["confidence"],
            reasoning=result.get("reasoning", ""),
            cached=False
        )
        
        # Evict oldest entries if cache is full
        while len(self._cache) >= self._max_cache_size:
            # Pop oldest (first) item
            self._cache.popitem(last=False)
            self._cache_evictions += 1
        
        # Store with timestamp for TTL
        self._cache[cache_key] = (cache_result, time.time())
        
        return result
    
    def _get_cache_key(self, memory_a: Dict[str, Any], memory_b: Dict[str, Any]) -> str:
        """Generate a cache key from two memory entry IDs."""
        id_a = memory_a.get("entry_id", "")
        id_b = memory_b.get("entry_id", "")
        combined = "".join(sorted([id_a, id_b]))
        return hashlib.sha256(combined.encode()).hexdigest()[:32]
    
    def _build_prompt(
        self, 
        entry_a: Dict[str, Any], 
        entry_b: Dict[str, Any]
    ) -> str:
        """Build a classification prompt with few-shot examples."""
        meta_a = entry_a.get("meta", {})
        meta_b = entry_b.get("meta", {})
        body_a = entry_a.get("body", "").strip()
        body_b = entry_b.get("body", "").strip()
        
        context_a = self._format_context(meta_a)
        context_b = self._format_context(meta_b)
        
        return f"""You are a memory relationship classifier.

## Categories
- REINFORCES: Second memory supports/validates first
- REFINES: Second adds detail without contradiction
- SUPERSEDES: Second contradicts/replaces first
- UNRELATED: No meaningful relationship

## Examples

REINFORCES:
A: "I prefer quiet work environments"
B: "Noise-canceling headphones help me focus"
-> {{"relationship": "REINFORCES", "confidence": 0.85, "reasoning": "Both express preference for focused work"}}

REFINES:
A: "Met the new project manager"
B: "PM is Sarah Chen, Seattle, Agile expert"
-> {{"relationship": "REFINES", "confidence": 0.92, "reasoning": "Adds specific details"}}

SUPERSEDES:
A: "Using Python 3.9"
B: "Migrated to Python 3.11, 3.9 deprecated"
-> {{"relationship": "SUPERSEDES", "confidence": 0.95, "reasoning": "Migration makes old version obsolete"}}

UNRELATED:
A: "Completed budget review"
B: "Learning guitar"
-> {{"relationship": "UNRELATED", "confidence": 0.97, "reasoning": "Work and hobby are separate domains"}}

## Task

Memory A {context_a}:
"{body_a}"

Memory B {context_b}:
"{body_b}"

Output JSON:
{{"relationship": "CATEGORY", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""
    
    def _format_context(self, meta: Dict[str, Any]) -> str:
        """Format metadata into a context string."""
        parts = []
        if "time" in meta:
            parts.append(f"time: {meta['time']}")
        if "importance" in meta:
            parts.append(f"importance: {meta['importance']}")
        if "tags" in meta:
            parts.append(f"tags: {meta['tags']}")
        if "status" in meta:
            parts.append(f"status: {meta['status']}")
        return f"({', '.join(parts)})" if parts else "(no metadata)"
    
    def _call_llm(self, prompt: str) -> str:
        """Call Ollama API with timeout handling and retry."""
        url = f"{OLLAMA_HOST}/api/chat"
        headers = {"Content-Type": "application/json"}
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a memory relationship classifier. Always respond with valid JSON containing: relationship (REINFORCES/REFINES/SUPERSEDES/UNRELATED), confidence (0.0-1.0), and reasoning (string)."},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.3
            }
        }
        
        body = json.dumps(data).encode("utf-8")
        last_error = None
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode())
                    message = result.get("message", {})
                    return message.get("content", "").strip()
                    
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise LLMUnavailableError(f"Model '{self.model}' not found in Ollama")
                last_error = f"HTTP {e.code}: {e.reason}"
                
            except urllib.error.URLError as e:
                raise LLMUnavailableError(f"Cannot connect to Ollama at {OLLAMA_HOST}: {e.reason}")
                
            except TimeoutError:
                last_error = f"Timeout after {self.timeout}s"
                if attempt < MAX_RETRIES:
                    time.sleep(1)
                    continue
                    
            except Exception as e:
                last_error = str(e)
        
        raise LLMContradictionError(f"Failed after {MAX_RETRIES} retries: {last_error}")
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON response from LLM."""
        try:
            json_match = re.search(r'\{[\s\S]*?\}', response_text)
            if json_match:
                response_text = json_match.group(0)
            
            data = json.loads(response_text)
            
            relationship = data.get("relationship", "UNRELATED").upper()
            if relationship not in self.VALID_RELATIONSHIPS:
                relationship = "UNRELATED"
            
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            
            reasoning = data.get("reasoning", "No reasoning provided")
            
            return {
                "relationship": relationship,
                "confidence": confidence,
                "reasoning": reasoning,
                "cached": False
            }
            
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            return {
                "relationship": "UNRELATED",
                "confidence": 0.3,
                "reasoning": f"Parse error, fallback to UNRELATED: {str(e)}",
                "cached": False
            }
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_size": len(self._cache),
            "cache_evictions": self._cache_evictions,
            "max_cache_size": self._max_cache_size,
            "hit_rate": self._cache_hits / (self._cache_hits + self._cache_misses) if (self._cache_hits + self._cache_misses) > 0 else 0
        }
    
    def clear_cache(self) -> None:
        """Clear the classification cache."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_evictions = 0


def main():
    """Test the LLM contradiction client with sample pairs."""
    print("=" * 60)
    print("LLM Contradiction Client - Test Suite")
    print("=" * 60)
    
    client = LLMContradictionClient(model="qwen3:4b", timeout=120)
    
    # Test cases: 5 known contradictions (SUPERSEDES pairs)
    contradictions = [
        {
            "name": "Technology Version Change",
            "a": {
                "entry_id": "mem-old-python",
                "meta": {"time": "2024-01-15T10:00:00Z", "importance": 0.8, "tags": ["decision", "python"]},
                "body": "Project is using Python 3.9 as the runtime."
            },
            "b": {
                "entry_id": "mem-new-python",
                "meta": {"time": "2024-03-01T14:00:00Z", "importance": 0.9, "tags": ["decision", "python"]},
                "body": "Migrated the project to Python 3.11. Python 3.9 is deprecated and no longer used."
            }
        },
        {
            "name": "Schedule Change",
            "a": {
                "entry_id": "mem-tuesday-meeting",
                "meta": {"time": "2024-02-01T09:00:00Z", "importance": 0.7, "tags": ["schedule", "meeting"]},
                "body": "Weekly standup meetings are held every Tuesday at 10 AM."
            },
            "b": {
                "entry_id": "mem-thursday-meeting",
                "meta": {"time": "2024-04-15T11:00:00Z", "importance": 0.8, "tags": ["schedule", "meeting"]},
                "body": "Standup meetings moved to Thursday at 2 PM. Tuesday meetings discontinued."
            }
        },
        {
            "name": "Favorite Restaurant Change",
            "a": {
                "entry_id": "mem-bella-italia",
                "meta": {"time": "2024-01-20T19:00:00Z", "importance": 0.6, "tags": ["preference"]},
                "body": "My favorite restaurant is Bella Italia on Main Street."
            },
            "b": {
                "entry_id": "mem-sakura-sushi",
                "meta": {"time": "2024-06-10T20:00:00Z", "importance": 0.7, "tags": ["preference"]},
                "body": "Bella Italia closed down. I now prefer Sakura Sushi on Oak Avenue."
            }
        },
        {
            "name": "Database Migration",
            "a": {
                "entry_id": "mem-mongodb",
                "meta": {"time": "2024-03-05T10:00:00Z", "importance": 0.85, "tags": ["database"]},
                "body": "Selected MongoDB as the primary data store."
            },
            "b": {
                "entry_id": "mem-postgres-switch",
                "meta": {"time": "2024-05-20T14:00:00Z", "importance": 0.9, "tags": ["database"]},
                "body": "Replaced MongoDB with PostgreSQL. MongoDB removed from stack."
            }
        },
        {
            "name": "Remote Work Policy Change",
            "a": {
                "entry_id": "mem-office-required",
                "meta": {"time": "2024-01-10T09:00:00Z", "importance": 0.8, "tags": ["policy"]},
                "body": "Company policy requires all employees to work from the office 5 days a week."
            },
            "b": {
                "entry_id": "mem-hybrid-policy",
                "meta": {"time": "2024-06-01T10:00:00Z", "importance": 0.9, "tags": ["policy"]},
                "body": "New hybrid work policy: employees can work remotely 3 days per week. Office requirement lifted."
            }
        }
    ]
    
    # Test cases: 5 known non-contradictions
    non_contradictions = [
        {
            "name": "Preference Reinforcement",
            "a": {
                "entry_id": "mem-quiet-work",
                "meta": {"time": "2024-02-10T09:00:00Z", "importance": 0.7, "tags": ["preference"]},
                "body": "I prefer working in quiet environments with minimal distractions."
            },
            "b": {
                "entry_id": "mem-headphones",
                "meta": {"time": "2024-03-15T10:00:00Z", "importance": 0.6, "tags": ["preference"]},
                "body": "Noise-canceling headphones help me maintain focus during deep work sessions."
            },
            "expected": "REINFORCES"
        },
        {
            "name": "Project Detail Refinement",
            "a": {
                "entry_id": "mem-new-pm",
                "meta": {"time": "2024-04-01T14:00:00Z", "importance": 0.7, "tags": ["work"]},
                "body": "Hired a new project manager for the engineering team."
            },
            "b": {
                "entry_id": "mem-pm-details",
                "meta": {"time": "2024-04-02T09:00:00Z", "importance": 0.6, "tags": ["work"]},
                "body": "The new project manager is Alex Johnson, has 10 years of Agile experience, based in Austin."
            },
            "expected": "REFINES"
        },
        {
            "name": "Decision Validation",
            "a": {
                "entry_id": "mem-react-choice",
                "meta": {"time": "2024-03-20T11:00:00Z", "importance": 0.85, "tags": ["decision"]},
                "body": "Chose React for the frontend framework."
            },
            "b": {
                "entry_id": "mem-react-success",
                "meta": {"time": "2024-05-15T16:00:00Z", "importance": 0.8, "tags": ["outcome"]},
                "body": "React implementation is performing well. Developer productivity increased by 30%."
            },
            "expected": "REINFORCES"
        },
        {
            "name": "Deadline Specification",
            "a": {
                "entry_id": "mem-q2-deadline",
                "meta": {"time": "2024-04-10T10:00:00Z", "importance": 0.75, "tags": ["deadline"]},
                "body": "The feature release is targeted for end of Q2."
            },
            "b": {
                "entry_id": "mem-june-date",
                "meta": {"time": "2024-04-12T09:00:00Z", "importance": 0.7, "tags": ["deadline"]},
                "body": "Feature release scheduled for June 27, 2024."
            },
            "expected": "REFINES"
        },
        {
            "name": "Completely Unrelated",
            "a": {
                "entry_id": "mem-budget-review",
                "meta": {"time": "2024-05-10T14:00:00Z", "importance": 0.8, "tags": ["work"]},
                "body": "Completed quarterly budget review for the engineering department."
            },
            "b": {
                "entry_id": "mem-guitar",
                "meta": {"time": "2024-05-12T18:00:00Z", "importance": 0.5, "tags": ["hobby"]},
                "body": "Started learning guitar. Practicing basic chords daily."
            },
            "expected": "UNRELATED"
        }
    ]
    
    print("\n--- Testing Contradictions (should be SUPERSEDES) ---\n")
    contradiction_results = []
    for test in contradictions:
        print(f"Test: {test['name']}")
        try:
            result = client.classify_pair(test["a"], test["b"])
            status = "✓" if result["relationship"] == "SUPERSEDES" else "✗"
            print(f"  {status} Result: {result['relationship']} (confidence: {result['confidence']:.2f})")
            print(f"    Reasoning: {result['reasoning'][:100]}...")
            contradiction_results.append(result["relationship"] == "SUPERSEDES")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            contradiction_results.append(False)
        print()
    
    print("\n--- Testing Non-Contradictions ---\n")
    non_contradiction_results = []
    for test in non_contradictions:
        print(f"Test: {test['name']} (expected: {test['expected']})")
        try:
            result = client.classify_pair(test["a"], test["b"])
            status = "✓" if result["relationship"] == test["expected"] else "✗"
            print(f"  {status} Result: {result['relationship']} (confidence: {result['confidence']:.2f})")
            print(f"    Reasoning: {result['reasoning'][:100]}...")
            non_contradiction_results.append(result["relationship"] == test["expected"])
        except Exception as e:
            print(f"  ✗ Error: {e}")
            non_contradiction_results.append(False)
        print()
    
    print("\n--- Testing Cache ---\n")
    print("Re-running first test (should hit cache)...")
    result = client.classify_pair(contradictions[0]["a"], contradictions[0]["b"])
    print(f"  Cached: {result['cached']}")
    
    stats = client.get_cache_stats()
    print(f"\nCache stats: {stats}")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Contradiction Accuracy: {sum(contradiction_results)}/{len(contradiction_results)}")
    print(f"Non-Contradiction Accuracy: {sum(non_contradiction_results)}/{len(non_contradiction_results)}")
    
    total_correct = sum(contradiction_results) + sum(non_contradiction_results)
    total_tests = len(contradiction_results) + len(non_contradiction_results)
    print(f"Overall Accuracy: {total_correct}/{total_tests} ({100*total_correct/total_tests:.1f}%)")
    
    return 0 if total_correct == total_tests else 1


if __name__ == "__main__":
    exit(main())
