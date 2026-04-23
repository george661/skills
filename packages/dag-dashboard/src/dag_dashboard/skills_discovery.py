"""Skills discovery module for scanning and parsing skill files."""
from __future__ import annotations

from pathlib import Path
import yaml


def list_skills(skills_dirs: list[Path]) -> list[dict]:
    """
    Scan directories for skill files and return their metadata.
    
    Supports two conventions:
    - *.skill.md files
    - <dir>/SKILL.md files
    
    Each file must have YAML frontmatter with at least a 'name' field.
    
    Args:
        skills_dirs: List of directory paths to scan
        
    Returns:
        List of dicts with keys: name, description (optional), path
    """
    skills = []
    
    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            continue
            
        # Find *.skill.md files
        for skill_file in skills_dir.glob("**/*.skill.md"):
            skill_data = _parse_skill_file(skill_file)
            if skill_data:
                skills.append(skill_data)
        
        # Find <dir>/SKILL.md files
        for skill_file in skills_dir.glob("**/SKILL.md"):
            skill_data = _parse_skill_file(skill_file)
            if skill_data:
                skills.append(skill_data)
    
    return skills


def _parse_skill_file(skill_file: Path) -> dict | None:
    """
    Parse a skill file and extract metadata from YAML frontmatter.
    
    Args:
        skill_file: Path to the skill file
        
    Returns:
        Dict with name, description, path if valid; None if invalid
    """
    try:
        content = skill_file.read_text()
        
        # Check for YAML frontmatter (--- at start and end)
        if not content.startswith("---\n"):
            return None
        
        # Find the end of frontmatter
        end_idx = content.find("\n---\n", 4)
        if end_idx == -1:
            return None
        
        # Extract and parse frontmatter
        frontmatter = content[4:end_idx]
        metadata = yaml.safe_load(frontmatter)
        
        if not metadata or not isinstance(metadata, dict):
            return None
        
        # Name is required
        name = metadata.get("name")
        if not name:
            return None
        
        return {
            "name": name,
            "description": metadata.get("description", ""),
            "path": str(skill_file)
        }
    except Exception:
        # Silently skip files that can't be parsed
        return None
