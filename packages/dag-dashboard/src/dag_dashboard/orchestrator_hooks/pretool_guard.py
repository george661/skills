"""PreToolUse hook for enforcing workspace boundaries.

This hook is registered in .claude/settings.json and called by Claude Code
before executing Read, Write, Edit, MultiEdit, and Bash tools. It denies
operations that would escape the workspace boundary.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# Egress patterns that are always denied in Bash commands
EGRESS_PATTERNS = [
    r"\bcurl\b",
    r"\bwget\b",
    r"\bssh\b",
    r"\bnc\b",
    r"\bscp\b",
    r"\brsync\b.*\w+@",  # rsync to remote (user@host pattern)
    r"\bftp\b",
]


def check_permission(
    tool_name: str,
    tool_input: Dict[str, Any],
    workspace: Optional[str],
    home_override: Optional[str] = None,
) -> Optional[str]:
    """
    Check if a tool use is permitted within the workspace boundary.

    Args:
        tool_name: The name of the tool being invoked
        tool_input: The input parameters to the tool
        workspace: The workspace directory path (from DAG_ORCHESTRATOR_WORKSPACE env)
        home_override: Override for home directory expansion (for testing)

    Returns:
        None if allowed, or a denial reason string if denied
    """
    # Fail closed - if workspace is not set, deny everything
    if workspace is None:
        return "Fail closed: DAG_ORCHESTRATOR_WORKSPACE not set"

    workspace_path = Path(workspace).resolve()

    # Handle file-based tools
    if tool_name in ("Read", "Write", "Edit", "MultiEdit"):
        file_path = tool_input.get("file_path")
        if not file_path:
            return None  # No file_path, let it through (will fail naturally)

        # Expand tilde
        if file_path.startswith("~"):
            home = home_override or os.path.expanduser("~")
            file_path = file_path.replace("~", home, 1)

        # Resolve to absolute path
        resolved_path = Path(file_path).resolve()

        # Check if it's inside workspace
        try:
            resolved_path.relative_to(workspace_path)
            return None  # Inside workspace, allow
        except ValueError:
            return f"File path {file_path} is outside workspace {workspace}"

    # Handle Bash commands
    if tool_name == "Bash":
        command = tool_input.get("command", "")

        # Check for egress patterns
        for pattern in EGRESS_PATTERNS:
            if re.search(pattern, command):
                return f"Bash command contains forbidden egress pattern: {pattern}"

        # Check for cd/pushd escapes
        # Extract cd/pushd targets and check if they would escape
        cd_pattern = r"(?:cd|pushd)\s+([^\s;&|]+)"
        for match in re.finditer(cd_pattern, command):
            target = match.group(1)
            # Resolve cd target relative to workspace
            try:
                target_path = (workspace_path / target).resolve()
                target_path.relative_to(workspace_path)
            except (ValueError, Exception):
                return f"Bash command would escape workspace via cd/pushd to {target}"

        return None  # Allowed

    # Unknown tool name - allow (let Claude Code handle it)
    return None


def format_deny_payload(reason: str) -> Dict[str, Any]:
    """
    Format a denial payload in Claude Code's expected format.

    Args:
        reason: The human-readable denial reason

    Returns:
        The formatted denial payload
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def append_denied_event(
    sentinel_file: Path,
    tool_name: str,
    tool_input: Dict[str, Any],
    reason: str,
) -> None:
    """
    Append a denied event to the sentinel JSONL file.

    Args:
        sentinel_file: Path to the denied-events.jsonl file
        tool_name: The tool that was denied
        tool_input: The input that was denied
        reason: The denial reason
    """
    event = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Append as JSONL
    with open(sentinel_file, "a") as f:
        f.write(json.dumps(event) + "\n")


def main() -> None:
    """
    Main entry point for the hook script.

    Reads tool invocation from stdin, checks permission, and either:
    - Exits 0 with empty stdout (allow)
    - Exits 0 with deny payload on stdout (deny)
    """
    # Read stdin
    try:
        payload = json.loads(sys.stdin.read())
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
    except (json.JSONDecodeError, Exception) as e:
        # Malformed input - deny and log
        print(json.dumps(format_deny_payload(f"Hook input error: {e}")))
        sys.exit(0)

    # Get workspace from env
    workspace = os.environ.get("DAG_ORCHESTRATOR_WORKSPACE")

    # Check permission
    denial_reason = check_permission(tool_name, tool_input, workspace)

    if denial_reason:
        # Denied - write to sentinel file if workspace is set
        if workspace:
            sentinel_file = Path(workspace) / ".claude" / "denied-events.jsonl"
            try:
                append_denied_event(sentinel_file, tool_name, tool_input, denial_reason)
            except Exception:
                pass  # Don't fail the hook if sentinel write fails

        # Output deny payload
        print(json.dumps(format_deny_payload(denial_reason)))

    # Exit 0 (allow if empty stdout, deny if payload on stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
