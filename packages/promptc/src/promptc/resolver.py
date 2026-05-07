"""Reference target resolution helpers for promptc (GW-5476)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from promptc.config import ParserConfig


def resolve_command(
    name: str, config: ParserConfig, base_path: Optional[Path] = None
) -> Optional[Path]:
    """Resolve a command name to its file path.

    Args:
        name: Command name, with or without leading slash
        config: Parser config with optional command_search_paths
        base_path: Optional base path for resolving relative paths

    Returns:
        Absolute Path to the command file if found, None otherwise
    """
    # Normalize: strip leading slash if present
    normalized = name.lstrip("/")

    # Determine search paths
    search_paths = config.command_search_paths
    if search_paths is None:
        # Default: $PROJECT_ROOT/.claude/commands/ then ~/.claude/commands/
        search_paths = []
        project_root = os.environ.get("PROJECT_ROOT")
        if project_root:
            search_paths.append(os.path.join(project_root, ".claude", "commands"))
        home = os.path.expanduser("~")
        search_paths.append(os.path.join(home, ".claude", "commands"))

    # Try each search path
    for search_dir in search_paths:
        search_path = Path(search_dir)
        if not search_path.exists():
            continue

        # Try exact match with .md extension
        candidate = search_path / f"{normalized}.md"
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    return None


def resolve_skill(
    name: str, config: ParserConfig, base_path: Optional[Path] = None
) -> Optional[Path]:
    """Resolve a skill name to its file path.

    Args:
        name: Skill name (e.g., "foo")
        config: Parser config with optional skill_search_paths
        base_path: Optional base path for resolving relative paths

    Returns:
        Absolute Path to the skill file if found, None otherwise
    """
    # Determine search paths
    search_paths = config.skill_search_paths
    if search_paths is None:
        # Default: search in project and home
        search_paths = []
        project_root = os.environ.get("PROJECT_ROOT")
        if project_root:
            search_paths.append(os.path.join(project_root, ".claude", "skills"))
        home = os.path.expanduser("~")
        search_paths.append(os.path.join(home, ".claude", "skills"))

    # Try each search path
    for search_dir in search_paths:
        search_path = Path(search_dir)
        if not search_path.exists():
            continue

        # Try multiple patterns:
        # 1. <name>/SKILL.md
        # 2. <name>.skill.md
        # 3. <name>.md
        candidates = [
            search_path / name / "SKILL.md",
            search_path / f"{name}.skill.md",
            search_path / f"{name}.md",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()

    return None


def resolve_file(spec: str, base_path: Optional[Path] = None) -> Optional[Path]:
    """Resolve a file reference to its path.

    Args:
        spec: File specification (relative or absolute path)
        base_path: Optional base path for resolving relative paths

    Returns:
        Absolute Path to the file if found, None otherwise

    Raises:
        ValueError: If an absolute path is outside the project root boundary
    """
    path = Path(spec)

    # Determine project root boundary
    project_root_str = os.environ.get("PROJECT_ROOT")
    if project_root_str:
        project_root = Path(project_root_str).resolve()
    else:
        project_root = Path.cwd().resolve()

    # If absolute, check boundary and return if valid
    if path.is_absolute():
        if not path.exists() or not path.is_file():
            return None
        resolved = path.resolve()
        # Validate that absolute path is within project root
        try:
            resolved.relative_to(project_root)
        except ValueError:
            # Path is outside project root
            raise ValueError(
                f"Absolute file path outside project root: {resolved} "
                f"(project root: {project_root})"
            )
        return resolved

    # If relative, resolve against base_path
    if base_path is not None:
        resolved = (base_path / path).resolve()
        if resolved.exists() and resolved.is_file():
            return resolved

    # Try relative to current directory
    if path.exists() and path.is_file():
        return path.resolve()

    return None
