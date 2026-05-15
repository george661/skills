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

    The PreToolUse hook is the authoritative enforcement layer — it
    resolves paths and inspects bash command semantics. The deny rules
    here are belt-and-suspenders for cases the hook can't reach (egress
    bash patterns are explicit so they show up in `claude --debug`
    output without invoking the hook).

    Path-based deny rules are intentionally NOT included: Claude Code's
    permission rules treat `Read(/path)` as project-root-relative (where
    project root resolves to the workspace), which would block legitimate
    workspace reads. Filesystem-absolute denial requires the hook.

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

    # Build settings.
    #
    # `hooks.PreToolUse` schema is a list of matcher blocks, each with an
    # inner `hooks` array of `{type, command}` entries — see
    # https://code.claude.com/docs/en/hooks. A flat `{matcher, command}`
    # object is silently ignored by Claude Code.
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
                "WebFetch",
                "Bash(curl:*)",
                "Bash(wget:*)",
                "Bash(ssh:*)",
                "Bash(nc:*)",
                "Bash(scp:*)",
            ],
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                f"{sys.executable} -m "
                                "dag_dashboard.orchestrator_hooks.pretool_guard"
                            ),
                        }
                    ],
                }
            ],
        },
    }

    # Write settings.json
    settings_path = claude_dir / "settings.json"
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    return settings_path.resolve()
