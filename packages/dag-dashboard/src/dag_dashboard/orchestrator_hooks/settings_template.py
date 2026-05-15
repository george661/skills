"""Settings.json template seeding for orchestrator workspaces.

This module creates .claude/settings.json with permission rules and hook
configuration to enforce the workspace boundary.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict


def seed_settings_json(workspace: Path) -> Path:
    """
    Create .claude/settings.json and .claude/denied-events.jsonl in workspace.

    The settings.json includes:
    - Allow list: workspace-relative file operations and safe bash commands
    - Deny list: absolute paths, home paths, egress commands (defense in depth)
    - PreToolUse hook: python -m dag_dashboard.orchestrator_hooks.pretool_guard

    Note: The deny rules here are defense-in-depth only. The PreToolUse hook
    is the primary enforcement mechanism, as it can resolve paths and check
    bash command semantics.

    Args:
        workspace: The workspace directory path

    Returns:
        Path to the created settings.json file
    """
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # Create sentinel file for denied events
    sentinel_file = claude_dir / "denied-events.jsonl"
    sentinel_file.touch(exist_ok=True)

    # Build settings
    settings: Dict[str, Any] = {
        "permissions": {
            "allow": [
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Bash(git status:*)",
                "Bash(git diff:*)",
                "Bash(git log:*)",
                "Bash(rg:*)",
                "Bash(ls:*)",
                "Bash(cat:*)",
            ],
            "deny": [
                "Read(/**)",
                "Read(~/**)",
                "Write(/**)",
                "WebFetch",
                "Bash(curl:*)",
                "Bash(wget:*)",
                "Bash(ssh:*)",
                "Bash(nc:*)",
                "Bash(scp:*)",
            ],
        },
        "hooks": {
            "PreToolUse": {
                "matcher": "*",
                "command": f"{sys.executable} -m dag_dashboard.orchestrator_hooks.pretool_guard",
            }
        },
    }

    # Write settings.json
    settings_path = claude_dir / "settings.json"
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    return settings_path.resolve()
