#!/usr/bin/env python3
"""
PostToolUse hook: writes a minimal worklog entry on every Jira mutation.
Guarantees attribution (sessionId@hostname) without relying on explicit calls.

Allowlist: transition_issue, add_comment, update_issue only.
add_worklog is excluded to prevent infinite recursion.
"""

import json
import os
import socket
import subprocess
import sys


ALLOWLISTED_SKILLS = {"transition_issue", "add_comment", "update_issue"}


def get_identity() -> str:
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown-session")
    hostname = socket.gethostname()
    return f"{session_id}@{hostname}"


def extract_issue_key(tool_input: dict) -> str | None:
    """Extract issue key from tool input. Handles both issue_key and issue_key variants."""
    return tool_input.get("issue_key") or tool_input.get("issueKey")


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        # Malformed input — do nothing, don't block
        print(json.dumps({"continue": True}))
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only act on allowlisted Jira skills
    skill_name = tool_name.split(".")[-1] if "." in tool_name else tool_name
    if skill_name not in ALLOWLISTED_SKILLS:
        print(json.dumps({"continue": True}))
        return

    issue_key = extract_issue_key(tool_input)
    if not issue_key:
        # Can't attribute without an issue key — skip silently
        print(json.dumps({"continue": True}))
        return

    identity = get_identity()
    comment = f"[agent: {identity}]\ncalled: {skill_name} on {issue_key}"

    # Resolve skills directory
    claude_dir = os.path.expanduser("~/.claude")
    add_worklog_skill = os.path.join(claude_dir, "skills", "jira", "add_worklog.ts")

    if not os.path.exists(add_worklog_skill):
        # Skills not installed — skip silently
        print(json.dumps({"continue": True}))
        return

    # Write worklog via subprocess (not via Claude tool — avoids recursion)
    # Use a 1-minute time_spent as required by Jira API
    payload = json.dumps({
        "issue_key": issue_key,
        "time_spent": "1m",
        "comment": comment,
    })

    project_root = os.environ.get("PROJECT_ROOT", os.getcwd())

    try:
        subprocess.Popen(
            ["npx", "tsx", add_worklog_skill, payload],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Fire and forget — don't wait for completion
        )
    except (OSError, FileNotFoundError):
        # npx/tsx not available — skip silently
        pass

    # Always continue — this hook must never block the operation
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
