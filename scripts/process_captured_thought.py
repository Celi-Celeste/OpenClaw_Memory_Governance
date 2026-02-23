#!/usr/bin/env python3
"""Process captured thoughts from Telegram/Obsidian into structured memory."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path
from typing import List, Optional

def parse_thought(text: str, source: str = "unknown") -> dict:
    """Parse raw thought text into structured format."""
    
    # Extract hashtags as tags
    tags = re.findall(r'#(\w+)', text)
    
    # Detect if it's a question
    is_question = bool(re.search(r'\?\s*$', text.strip()))
    
    # Detect urgency keywords
    urgency_keywords = ['urgent', 'important', 'critical', 'asap', 'now']
    urgency = any(kw in text.lower() for kw in urgency_keywords)
    
    # Detect if it's an idea vs task vs question
    if is_question:
        thought_type = "question"
    elif any(kw in text.lower() for kw in ['should', 'need to', 'must', 'todo']):
        thought_type = "task"
    else:
        thought_type = "idea"
    
    return {
        "raw_text": text,
        "source": source,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tags": tags,
        "type": thought_type,
        "urgency": urgency,
        "is_question": is_question,
        "word_count": len(text.split()),
    }

def store_in_episodic(thought: dict, workspace: Path) -> Path:
    """Store processed thought in episodic memory."""
    
    today = dt.date.today().isoformat()
    episodic_dir = workspace / "memory" / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{today}-thoughts.md"
    filepath = episodic_dir / filename
    
    # Build entry
    entry_lines = [
        f"### thought:{thought['timestamp']}",
        f"time: {thought['timestamp']}",
        f"layer: episodic",
        f"importance: 0.70",  # Default, will be scored later
        f"confidence: 0.80",
        f"status: active",
        f"source: {thought['source']}",
        f"type: {thought['type']}",
        f"urgency: {'high' if thought['urgency'] else 'normal'}",
        f"tags: {thought['tags']}",
        f"---",
        f"",
        thought['raw_text'],
        f"",
    ]
    
    entry = "\n".join(entry_lines)
    
    # Append to file
    if filepath.exists():
        with open(filepath, "a") as f:
            f.write("\n" + entry + "\n")
    else:
        with open(filepath, "w") as f:
            f.write(f"# Thoughts - {today}\n\n" + entry + "\n")
    
    return filepath

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True, help="Captured thought text")
    parser.add_argument("--source", default="telegram", help="Source of capture")
    parser.add_argument("--workspace", default=".", help="Workspace path")
    args = parser.parse_args()
    
    workspace = Path(args.workspace).resolve()
    
    # Process
    thought = parse_thought(args.text, args.source)
    
    # Store
    filepath = store_in_episodic(thought, workspace)
    
    # Report
    print(f"Thought captured: {thought['type']} ({thought['word_count']} words)")
    print(f"Tags: {thought['tags']}")
    print(f"Stored: {filepath}")
    
    return 0

if __name__ == "__main__":
    exit(main())
