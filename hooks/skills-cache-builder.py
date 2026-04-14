#!/usr/bin/env python3
"""
Skills cache builder - generates a static cache of available skills.
Run during install/update to avoid filesystem scanning on session start.
"""

import json
from datetime import datetime
from pathlib import Path


def build_skills_cache():
    """Build the skills cache and save to ~/.claude/cache/skills-index.json"""

    skills_dir = Path.home() / ".claude" / "skills"
    cache_dir = Path.home() / ".claude" / "cache"
    cache_file = cache_dir / "skills-index.json"

    # Ensure cache directory exists
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Scan for skills
    skills_index = {
        "version": "1.0",
        "generated": datetime.utcnow().isoformat() + "Z",
        "skills": {}
    }

    integrations = ["jira", "bitbucket", "agentdb", "slack", "concourse", "fly", "playwright"]

    for integration in integrations:
        int_dir = skills_dir / integration
        if int_dir.exists():
            skills = []
            for ts_file in sorted(int_dir.glob("*.ts")):
                name = ts_file.stem
                # Skip client files and internal utilities
                if not name.endswith("-client") and not name.startswith("_"):
                    skills.append(name)
            if skills:
                skills_index["skills"][integration] = skills

    # Write cache file
    with open(cache_file, 'w') as f:
        json.dump(skills_index, f, indent=2)

    print(f"Skills cache built: {cache_file}")
    print(f"Found {sum(len(s) for s in skills_index['skills'].values())} skills across {len(skills_index['skills'])} integrations")

    return cache_file


def generate_skill_index_text():
    """Generate formatted skill index text from cache."""

    cache_file = Path.home() / ".claude" / "cache" / "skills-index.json"

    if not cache_file.exists():
        # Build cache if it doesn't exist
        build_skills_cache()

    try:
        with open(cache_file) as f:
            cache = json.load(f)

        lines = ["AVAILABLE SKILLS", ""]

        for integration, skills in cache.get("skills", {}).items():
            if skills:
                lines.append(f"  {integration}: {', '.join(skills)}")

        lines.append("")
        lines.append("Usage: npx tsx .claude/skills/{integration}/{skill}.ts '{...params}'")
        lines.append("")

        return "\n".join(lines)

    except Exception:
        # Fallback to empty if cache is corrupt
        return ""


if __name__ == "__main__":
    # Build the cache
    cache_file = build_skills_cache()

    # Test loading
    index = generate_skill_index_text()
    if index:
        print("\nGenerated index preview:")
        print(index)
