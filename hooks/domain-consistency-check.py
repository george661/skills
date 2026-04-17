#!/usr/bin/env python3
"""
PostToolUse:Write|Edit hook - domain consistency check.

Auto-triggers when design or plan docs are written to the tenant docs repo.
Checks if the edited file matches domain-relevant paths and reminds
the user to run `/domain-map validate` to verify domain model alignment.

Includes a 300-second cooldown to avoid spamming on rapid edits.
"""

import json
import os
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

# Get tenant docs repo name from environment (defaults to project-docs)
TENANT_DOCS_REPO = os.environ.get("TENANT_DOCS_REPO", "project-docs")

# Path patterns that trigger the domain consistency check
DOMAIN_PATH_PATTERNS = [
    f"*/{TENANT_DOCS_REPO}/plans/*.md",
    f"*/{TENANT_DOCS_REPO}/architecture/*.md",
    f"*/{TENANT_DOCS_REPO}/domain/*.cml",
    f"*/{TENANT_DOCS_REPO}/domain/*.md",
]

# Cooldown configuration
CACHE_DIR = Path.home() / ".cache" / "skill-hooks"
MARKER_FILE = CACHE_DIR / "domain-consistency-check.marker"
COOLDOWN_SECONDS = 300


def is_domain_relevant(file_path: str) -> bool:
    """Check if the file path matches any domain-relevant pattern."""
    for pattern in DOMAIN_PATH_PATTERNS:
        if fnmatch(file_path, pattern):
            return True
    return False


def is_within_cooldown() -> bool:
    """Check if the cooldown marker exists and is recent enough to skip."""
    if not MARKER_FILE.exists():
        return False
    try:
        marker_mtime = MARKER_FILE.stat().st_mtime
        elapsed = time.time() - marker_mtime
        return elapsed < COOLDOWN_SECONDS
    except OSError:
        return False


def update_marker() -> None:
    """Create or update the cooldown marker file."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MARKER_FILE.write_text(str(time.time()))
    except OSError:
        pass


def main():
    # Read JSON from stdin; handle missing or empty input gracefully
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        input_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Only activate for Write or Edit tool uses
    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    # Extract file_path from tool_input
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    # Check if the file path matches domain-relevant patterns
    if not is_domain_relevant(file_path):
        sys.exit(0)

    # Check cooldown
    if is_within_cooldown():
        sys.exit(0)

    # Activate: output the domain consistency check reminder
    response = {
        "decision": "approve",
        "reason": (
            "Domain consistency check triggered. "
            "Run `/domain-map validate` to verify domain model alignment."
        ),
    }
    print(json.dumps(response))

    # Update the cooldown marker
    update_marker()


if __name__ == "__main__":
    main()
