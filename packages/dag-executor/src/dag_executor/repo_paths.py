"""Repository path resolution for out-of-tree checkouts.

Resolves repository paths using a prioritized search order:
1. Explicit config file ($HOME/.claude/config/repo-paths.json or custom path)
2. Environment variable REPO_PATH_<SLUG_UPPER>
3. $PROJECT_ROOT/<slug>
4. $HOME/dev/<slug>
5. Filesystem probe (disabled by default via REPO_PATH_ENABLE_PROBE)

This module has zero dependency on gw-agents and can resolve paths for any
repository checkout, including out-of-tree layouts like skills at ~/dev/skills.

Note on slug normalization: Non-alphanumeric characters in slugs are converted
to underscores for environment variable lookup (e.g., 'gw-foo' → REPO_PATH_GW_FOO).
This means slugs 'gw-foo' and 'gw_foo' would collide, but this is not a concern
for current repository naming conventions.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


class RepoPathError(Exception):
    """Raised when a repository path cannot be resolved.
    
    Attributes:
        message: Human-readable error message
        slug: The repository slug that failed to resolve
        search_paths: List of paths that were checked
    """
    
    def __init__(self, message: str, slug: str, search_paths: list[tuple[str, str]]):
        super().__init__(message)
        self.slug = slug
        self.search_paths = search_paths


def _normalize_slug(slug: str) -> str:
    """Normalize a repository slug for environment variable lookup.
    
    Converts to uppercase and replaces non-alphanumeric chars with underscores.
    
    Args:
        slug: Repository slug (e.g., 'gw-skills', 'skills')
    
    Returns:
        Normalized slug for env var lookup (e.g., 'GW_SKILLS', 'SKILLS')
    """
    return "".join(c.upper() if c.isalnum() else "_" for c in slug)


def _try_config_file(slug: str, config_path: Optional[str] = None) -> Optional[str]:
    """Try to resolve repo path from explicit config file.
    
    Args:
        slug: Repository slug
        config_path: Optional explicit config file path
    
    Returns:
        Resolved path if found and exists, None otherwise
    
    Raises:
        RepoPathError: If config file is malformed
    """
    if config_path:
        config_paths = [Path(config_path)]
    else:
        # Default locations (PROJECT_ROOT has priority over HOME)
        config_paths = []
        project_root = os.getenv("PROJECT_ROOT")
        if project_root:
            config_paths.append(Path(project_root) / ".claude" / "config" / "repo-paths.json")
        home = Path.home()
        config_paths.append(home / ".claude" / "config" / "repo-paths.json")
    
    for config_file in config_paths:
        if not config_file.exists():
            continue
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise RepoPathError(
                f"Malformed JSON in config file {config_file}: {e}",
                slug,
                [(str(config_file), "malformed")]
            )
        
        if slug in config:
            path = Path(config[slug])
            if path.exists():
                return str(path.resolve())
    
    return None


def _try_env_var(slug: str) -> Optional[str]:
    """Try to resolve repo path from environment variable.
    
    Args:
        slug: Repository slug
    
    Returns:
        Resolved path if env var set and path exists, None otherwise
    """
    normalized = _normalize_slug(slug)
    env_var = f"REPO_PATH_{normalized}"
    path_str = os.getenv(env_var)
    
    if path_str:
        path = Path(path_str)
        if path.exists():
            return str(path.resolve())
    
    return None


def _try_project_root(slug: str) -> Optional[str]:
    """Try to resolve repo path under $PROJECT_ROOT/<slug>.
    
    Args:
        slug: Repository slug
    
    Returns:
        Resolved path if found and exists, None otherwise
    """
    project_root = os.getenv("PROJECT_ROOT")
    if not project_root:
        return None
    
    # Try exact slug match
    path = Path(project_root) / slug
    if path.exists():
        return str(path.resolve())

    return None


def _try_home_dev(slug: str) -> Optional[str]:
    """Try to resolve repo path under $HOME/dev/<slug>.
    
    Args:
        slug: Repository slug
    
    Returns:
        Resolved path if found and exists, None otherwise
    """
    home = Path.home()
    dev_dir = home / "dev"
    
    if not dev_dir.exists():
        return None
    
    # Try exact slug match
    path = dev_dir / slug
    if path.exists():
        return str(path.resolve())

    return None


def _try_filesystem_probe(slug: str) -> Optional[str]:
    """Try to find repo using filesystem probe (last resort).
    
    This is disabled by default (requires REPO_PATH_ENABLE_PROBE=1) because
    'find' operations can be slow on large filesystems.
    
    Args:
        slug: Repository slug
    
    Returns:
        Resolved path if found, None otherwise
    """
    if os.getenv("REPO_PATH_ENABLE_PROBE") != "1":
        return None
    
    home = Path.home()
    dev_dir = home / "dev"
    
    if not dev_dir.exists():
        return None
    
    try:
        # Try exact slug match
        result = subprocess.run(
            ["find", str(dev_dir), "-maxdepth", "3", "-type", "d", "-name", slug],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            first_match = result.stdout.strip().split('\n')[0]
            path = Path(first_match)
            if path.exists():
                return str(path.resolve())
    
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass
    
    return None


def resolve_repo_path(slug: str, config_path: Optional[str] = None) -> str:
    """Resolve the filesystem path for a repository.

    Search order:
    1. Explicit config file (default: $PROJECT_ROOT/.claude/config/repo-paths.json, then $HOME/.claude/config/repo-paths.json)
    2. Environment variable REPO_PATH_<SLUG_UPPER>
    3. $PROJECT_ROOT/<slug>
    4. $HOME/dev/<slug>
    5. Filesystem probe (requires REPO_PATH_ENABLE_PROBE=1)
    
    Args:
        slug: Repository slug (e.g., 'skills', 'gw-skills')
        config_path: Optional explicit config file path
    
    Returns:
        Absolute resolved path to the repository
    
    Raises:
        RepoPathError: If the repository cannot be found
    
    Examples:
        >>> resolve_repo_path("skills")
        '/Users/alice/dev/skills'
        
        >>> resolve_repo_path("gw-skills", config_path="/custom/repo-paths.json")
        '/Users/alice/projects/skills'
    """
    search_paths: list[tuple[str, str]] = []
    
    # 1. Explicit config file
    try:
        result = _try_config_file(slug, config_path)
        if result:
            return result
        
        if config_path:
            search_paths.append((config_path, "config file (not found)"))
        else:
            default_config = Path.home() / ".claude" / "config" / "repo-paths.json"
            search_paths.append((str(default_config), "default config (not found)"))
    except RepoPathError:
        # Malformed config - propagate immediately
        raise
    
    # 2. Environment variable
    result = _try_env_var(slug)
    if result:
        return result
    normalized = _normalize_slug(slug)
    search_paths.append((f"$REPO_PATH_{normalized}", "env var (not set or not found)"))
    
    # 3. $PROJECT_ROOT/<slug>
    result = _try_project_root(slug)
    if result:
        return result
    project_root = os.getenv("PROJECT_ROOT", "<not set>")
    search_paths.append((f"{project_root}/{slug}", "PROJECT_ROOT (not found)"))
    
    # 4. $HOME/dev/<slug>
    result = _try_home_dev(slug)
    if result:
        return result
    home_dev = Path.home() / "dev" / slug
    search_paths.append((str(home_dev), "HOME/dev (not found)"))
    
    # 5. Filesystem probe (last resort, disabled by default)
    result = _try_filesystem_probe(slug)
    if result:
        return result
    if os.getenv("REPO_PATH_ENABLE_PROBE") == "1":
        search_paths.append(("filesystem probe", "enabled but not found"))
    else:
        search_paths.append(("filesystem probe", "disabled (set REPO_PATH_ENABLE_PROBE=1)"))
    
    # Not found anywhere
    search_list = "\n".join(f"  - {path}: {reason}" for path, reason in search_paths)
    raise RepoPathError(
        f"Cannot resolve repository path for '{slug}'.\n"
        f"Searched:\n{search_list}\n\n"
        f"To fix:\n"
        f"  1. Set REPO_PATH_{normalized}=/path/to/{slug}\n"
        f"  2. Add to $HOME/.claude/config/repo-paths.json: {{\"{slug}\": \"/path/to/{slug}\"}}\n"
        f"  3. Clone to $HOME/dev/{slug}",
        slug,
        search_paths
    )
