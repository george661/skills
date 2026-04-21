"""Artifact detection from runner output text.

Scans text for PR URLs, commit SHAs, branch names, and file paths and
returns a list of artifact dicts suitable for use as metadata on an
ARTIFACT_CREATED WorkflowEvent.

Each artifact dict has at least: name, artifact_type.
Optional: url, path.
"""
import re
from typing import Any, Dict, List, Set, Tuple

# GitHub / Bitbucket PR URLs (no trailing slash, no fragment)
_PR_RE = re.compile(
    r"https?://(?:github\.com|bitbucket\.org)/"
    r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/"
    r"(?:pull|pull-requests)/(\d+)"
)

# "[main 1a2b3c4d]" style commit lines from `git commit` output
_COMMIT_RE = re.compile(r"\[[^\]]+ ([0-9a-f]{7,40})\]")

# "* [new branch]      BRANCH_NAME -> BRANCH_NAME" from `git push`
_BRANCH_RE = re.compile(r"\[new branch\]\s+(\S+)\s+->")

# "Created: path/to/file.ext" marker emitted by agents or scripts.
# Deliberately conservative — only matches when explicitly announced,
# to avoid flooding the table with incidental paths.
_FILE_RE = re.compile(r"(?m)^\s*Created:\s+([^\s]+)\s*$")


def detect_artifacts(text: str) -> List[Dict[str, Any]]:
    """Scan ``text`` for artifact markers and return a list of artifact dicts.

    Returns at most one entry per unique (artifact_type, name) pair.
    """
    if not text:
        return []

    seen: Set[Tuple[str, str]] = set()
    artifacts: List[Dict[str, Any]] = []

    for match in _PR_RE.finditer(text):
        url = match.group(0)
        number = match.group(1)
        key = ("pr", url)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append({
            "name": f"PR #{number}",
            "artifact_type": "pr",
            "url": url,
        })

    for match in _COMMIT_RE.finditer(text):
        sha = match.group(1)
        key = ("commit", sha)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append({
            "name": sha,
            "artifact_type": "commit",
        })

    for match in _BRANCH_RE.finditer(text):
        branch = match.group(1)
        key = ("branch", branch)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append({
            "name": branch,
            "artifact_type": "branch",
        })

    for match in _FILE_RE.finditer(text):
        path = match.group(1)
        key = ("file", path)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append({
            "name": path.rsplit("/", 1)[-1],
            "artifact_type": "file",
            "path": path,
        })

    return artifacts
