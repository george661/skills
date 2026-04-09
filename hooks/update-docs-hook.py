#!/usr/bin/env python3
"""
Update Docs Hook

Auto-triggers /update-docs after specific workflow commands complete.
Includes duplicate prevention with 5-minute cooldown per issue/command.

Usage:
  - Runs automatically via PostToolUse hook on SlashCommand
  - Set UPDATE_DOCS_DISABLED=1 to disable

Triggered Commands:
  - plan, groom, create-implementation-plan, validate-prp
  - validate-groom, validate, implement
"""

import json
import sys
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Configuration
CACHE_DIR = Path.home() / ".cache" / "agents" / "update-docs-hook"
LOG_FILE = CACHE_DIR / "activity.jsonl"
MARKER_DIR = CACHE_DIR / "markers"
COOLDOWN_MINUTES = 5

# Commands that trigger /update-docs with their scope and priority
TRIGGER_COMMANDS = {
    "plan": {"scope": "planning", "priority": "high"},
    "groom": {"scope": "grooming", "priority": "high"},
    "create-implementation-plan": {"scope": "implementation", "priority": "medium"},
    "validate-prp": {"scope": "planning", "priority": "medium"},
    "validate-groom": {"scope": "grooming", "priority": "medium"},
    "validate": {"scope": "validation", "priority": "high"},
    "implement": {"scope": "implementation", "priority": "medium"},
}


def ensure_dirs():
    """Ensure cache and marker directories exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MARKER_DIR.mkdir(parents=True, exist_ok=True)


def log_hook_activity(command: str, status: str, details: dict):
    """Log hook activity to JSONL file."""
    ensure_dirs()

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "command": command,
        "status": status,
        "details": details
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Failed to write log: {e}", file=sys.stderr)


def extract_issue_key(hook_input: dict) -> Optional[str]:
    """Extract issue key (PROJ-\\d+) from hook input."""
    # Try to extract from tool_input command args
    tool_input = hook_input.get("tool_input", {})
    command_str = tool_input.get("command", "")

    # Pattern to match PROJ-### issue keys
    pattern = r"\b(PROJ-\d+)\b"

    # Search in command string
    match = re.search(pattern, command_str, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # Search in tool_input arguments if present
    args = tool_input.get("arguments", "")
    if isinstance(args, str):
        match = re.search(pattern, args, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    # Search in conversation context if available
    conversation = hook_input.get("conversation", [])
    if isinstance(conversation, list):
        for msg in reversed(conversation[-5:]):  # Check last 5 messages
            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).upper()

    return None


def extract_command_name(hook_input: dict) -> Optional[str]:
    """Extract command name from hook input."""
    tool_input = hook_input.get("tool_input", {})
    command_str = tool_input.get("command", "")

    if not command_str:
        return None

    # Remove leading slash and extract first word
    command_str = command_str.lstrip("/")
    parts = command_str.split()

    if not parts:
        return None

    return parts[0].lower()


def should_trigger(command: str) -> bool:
    """Check if command should trigger /update-docs."""
    return command in TRIGGER_COMMANDS


def get_trigger_config(command: str) -> dict:
    """Get trigger configuration for a command."""
    return TRIGGER_COMMANDS.get(command, {})


def get_marker_path(issue_key: str, command: str) -> Path:
    """Get marker file path for issue/command combination."""
    safe_key = issue_key.replace("/", "-").replace("\\", "-")
    safe_cmd = command.replace("/", "-").replace("\\", "-")
    return MARKER_DIR / f"{safe_key}-{safe_cmd}.marker"


def check_recent_update(issue_key: str, command: str) -> bool:
    """Check if update was recently triggered for this issue/command."""
    if not issue_key:
        return False

    ensure_dirs()
    marker_path = get_marker_path(issue_key, command)

    if not marker_path.exists():
        return False

    try:
        marker_time = datetime.fromisoformat(marker_path.read_text().strip())
        cooldown_threshold = datetime.now() - timedelta(minutes=COOLDOWN_MINUTES)
        return marker_time > cooldown_threshold
    except (ValueError, OSError):
        # Invalid marker, treat as no recent update
        return False


def mark_update_triggered(issue_key: str, command: str):
    """Mark that update was triggered for issue/command."""
    if not issue_key:
        return

    ensure_dirs()
    marker_path = get_marker_path(issue_key, command)

    try:
        marker_path.write_text(datetime.now().isoformat())
    except OSError as e:
        print(f"Failed to write marker: {e}", file=sys.stderr)


def is_disabled() -> bool:
    """Check if hook is disabled via environment variable."""
    disabled = os.environ.get("UPDATE_DOCS_DISABLED", "").lower()
    return disabled in ("1", "true", "yes")


def build_invoke_response(issue_key: Optional[str], command: str, config: dict) -> dict:
    """Build response to invoke /update-docs command."""
    arguments = []
    if issue_key:
        arguments.append(issue_key)

    context = {
        "triggered_by": command,
        "scope": config.get("scope", "general"),
        "priority": config.get("priority", "medium"),
        "timestamp": datetime.now().isoformat()
    }

    message = f"Auto-triggering /update-docs after /{command}"
    if issue_key:
        message += f" for {issue_key}"

    return {
        "status": "invoke_command",
        "command": "/update-docs",
        "arguments": arguments,
        "context": context,
        "message": message
    }


def main():
    """Main entry point for hook."""
    # Check if disabled
    if is_disabled():
        print(json.dumps({"continue": True, "skipped": "disabled"}))
        return

    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    # Extract command and issue
    command = extract_command_name(input_data)
    issue_key = extract_issue_key(input_data)

    # Check if this command should trigger update-docs
    if not command or not should_trigger(command):
        log_hook_activity(
            command or "unknown",
            "skipped",
            {"reason": "not a trigger command", "issue": issue_key}
        )
        print(json.dumps({"continue": True}))
        return

    config = get_trigger_config(command)

    # Check for duplicate (cooldown)
    if issue_key and check_recent_update(issue_key, command):
        log_hook_activity(
            command,
            "skipped",
            {"reason": "cooldown active", "issue": issue_key, "cooldown_minutes": COOLDOWN_MINUTES}
        )
        print(json.dumps({
            "continue": True,
            "skipped": "cooldown",
            "message": f"Update docs skipped - triggered within last {COOLDOWN_MINUTES} minutes"
        }))
        return

    # Mark update as triggered
    if issue_key:
        mark_update_triggered(issue_key, command)

    # Log and build invoke response
    log_hook_activity(
        command,
        "triggered",
        {
            "issue": issue_key,
            "scope": config.get("scope"),
            "priority": config.get("priority")
        }
    )

    response = build_invoke_response(issue_key, command, config)
    print(json.dumps(response))


if __name__ == "__main__":
    main()
