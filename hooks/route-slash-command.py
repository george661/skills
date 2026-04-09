#!/usr/bin/env python3
"""
PreToolUse hook for SlashCommand AND Skill: intercepts commands and routes to
local models when the routing config says to use Ollama.

Delegates actual subprocess work to dispatch-local.sh (single source of truth).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from load_model_routing import load_routing, resolve_with_fallback
except ImportError:
    print(json.dumps({"decision": "allow"}))
    sys.exit(0)

DISPATCH_SCRIPT = os.path.expanduser("~/.claude/hooks/dispatch-local.sh")


def extract_command_name(tool_name, tool_input):
    if tool_name == "SlashCommand":
        return tool_input.get("command_name", "").lstrip("/")
    if tool_name == "Skill":
        skill_name = tool_input.get("skill_name", "")
        if skill_name.startswith("/"):
            return skill_name.lstrip("/")
        return skill_name
    return ""


def extract_arguments(tool_name, tool_input):
    if tool_name in ("SlashCommand", "Skill"):
        return tool_input.get("arguments", "")
    return ""


def progress(msg):
    """Print progress to terminal, bypassing Claude Code's stderr capture."""
    line = f"[Ollama] {msg}"
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(f"\r\033[K{line}\n")
            tty.flush()
    except OSError:
        print(line, file=sys.stderr, flush=True)


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        print(json.dumps({"decision": "allow"}))
        return

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if tool_name not in ("SlashCommand", "Skill"):
        print(json.dumps({"decision": "allow"}))
        return

    command_name = extract_command_name(tool_name, tool_input)
    if not command_name:
        print(json.dumps({"decision": "allow"}))
        return

    # Commands that should NEVER be rerouted
    orchestrator_commands = {"loop:issue", "loop:epic", "loop:backlog"}
    if command_name in orchestrator_commands:
        print(json.dumps({"decision": "allow"}))
        return

    # Non-command skills should never be rerouted
    non_command_prefixes = (
        "superpowers:", "claude-api", "design-principles", "domain-map",
        "desloppify", "confidence-check", "smart-commits", "index-repos",
        "simplify", "code-review:", "visual-capture",
    )
    if any(command_name.startswith(p) for p in non_command_prefixes):
        print(json.dumps({"decision": "allow"}))
        return

    # Resolve the model for this command
    try:
        config = load_routing()
        result = resolve_with_fallback(config, command_name)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return

    # If it routes to Bedrock, allow inline execution
    if result.get("provider_type") == "bedrock":
        print(json.dumps({"decision": "allow"}))
        return

    # It routes to a local model — delegate to dispatch-local.sh
    actual_model = result.get("model", "qwen3-coder:30b")
    args = extract_arguments(tool_name, tool_input)

    progress(f"/{command_name} {args} → {actual_model} via Ollama")
    progress("Running... (this may take several minutes)")

    start_time = time.time()

    try:
        proc = subprocess.run(
            [DISPATCH_SCRIPT, command_name, args],
            capture_output=True, text=True, timeout=1800,
            cwd=os.environ.get("PROJECT_ROOT", str(Path.home())),
        )
        output = proc.stdout.strip() if proc.stdout else "(no output)"
    except subprocess.TimeoutExpired:
        output = f"/{command_name} timed out after 30 minutes."
    except Exception as e:
        output = f"Error dispatching: {e}"

    elapsed = time.time() - start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60

    # Truncate very long output
    if len(output) > 8000:
        output = output[:3000] + "\n\n...(truncated)...\n\n" + output[-3000:]

    progress(f"Completed in {mins}m {secs}s")

    print(json.dumps({
        "decision": "block",
        "reason": (
            f"**/{command_name} {args} completed on {actual_model} "
            f"(Ollama, $0 cost, {mins}m {secs}s)**\n\n{output}"
        )
    }))


if __name__ == "__main__":
    main()
