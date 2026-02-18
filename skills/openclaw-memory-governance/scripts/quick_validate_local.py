#!/usr/bin/env python3
"""Local fallback validator when skill-creator validator dependencies are unavailable."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def fail(msg: str) -> int:
    print(f"validation_error: {msg}")
    return 1


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return fail("SKILL.md missing")

    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if not m:
        return fail("frontmatter missing or malformed")

    frontmatter = m.group(1).strip().splitlines()
    keys = {}
    for line in frontmatter:
        if ":" not in line:
            return fail(f"invalid frontmatter line: {line}")
        k, v = line.split(":", 1)
        keys[k.strip()] = v.strip()

    expected_name = skill_dir.name
    if keys.get("name") != expected_name:
        return fail(f"name must equal folder name ({expected_name})")
    if "description" not in keys or not keys["description"]:
        return fail("description missing")
    if set(keys.keys()) != {"name", "description"}:
        return fail("frontmatter must contain only name and description")
    if not re.match(r"^[a-z0-9-]{1,64}$", keys["name"]):
        return fail("name must match lowercase-hyphen convention")

    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not openai_yaml.exists():
        return fail("agents/openai.yaml missing")
    openai_text = openai_yaml.read_text(encoding="utf-8")
    if f"${expected_name}" not in openai_text:
        return fail("default_prompt in openai.yaml must reference $<skill-name>")

    required_scripts = [
        "memory_lib.py",
        "hourly_semantic_extract.py",
        "importance_score.py",
        "daily_consolidate.py",
        "confidence_gate.py",
        "confidence_gate_flow.py",
        "weekly_identity_promote.py",
        "weekly_drift_review.py",
        "transcript_lookup.py",
        "session_hygiene.py",
        "render_schedule.py",
        "smoke_suite.py",
    ]
    for script in required_scripts:
        if not (skill_dir / "scripts" / script).exists():
            return fail(f"required script missing: {script}")

    print("quick_validate_local ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
