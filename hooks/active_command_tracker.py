#!/usr/bin/env python3
"""
PreToolUse:SlashCommand hook - tracks the active command name.

Writes the current command name to ~/.claude/.active-command so that
other hooks (like result-compressor.py) can determine which command
tier to use for context-aware behavior.
"""

import json
import sys
import os

ACTIVE_COMMAND_FILE = os.path.expanduser('~/.claude/.active-command')


def extract_command_name(hook_input: dict) -> str:
    """Extract the command name from a SlashCommand hook input."""
    tool_input = hook_input.get('tool_input', {})
    command_name = tool_input.get('command_name', '')
    return command_name


def write_active_command(command_name: str, path: str = ACTIVE_COMMAND_FILE) -> None:
    """Write the active command name to the tracking file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(command_name)
    except OSError:
        pass  # Don't fail the hook on write errors


def read_active_command(path: str = ACTIVE_COMMAND_FILE) -> str:
    """Read the current active command name. Returns empty string if not set."""
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ''


def main():
    """Hook entry point - reads from stdin, writes active command file."""
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    command_name = extract_command_name(input_data)
    if command_name:
        write_active_command(command_name)

    # Always allow the command to proceed
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
