#!/usr/bin/env python3
"""
Skill Execution Tracker Hook
Captures skill invocations and outcomes for metrics tracking.

Tracks skills invoked via the Skill tool, logging execution details
to ~/.claude/skill-tracking/executions.jsonl for analysis.

Usage:
  - Runs automatically via Pre/PostToolUse hook on Skill tool
  - Manual: python3 .claude/hooks/skill-tracker.py stats
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Storage paths
SKILL_DIR = Path.home() / ".claude" / "skill-tracking"
SKILL_DIR.mkdir(parents=True, exist_ok=True)

EXECUTIONS_FILE = SKILL_DIR / "executions.jsonl"
STATS_FILE = SKILL_DIR / "stats.json"


def log_skill_execution(skill_name: str, args: str, phase: str, outcome: str = None):
    """Log a skill execution event."""
    entry = {
        "skill": skill_name,
        "args": args,
        "phase": phase,
        "outcome": outcome,
        "timestamp": datetime.now().isoformat()
    }

    with open(EXECUTIONS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def get_skill_stats() -> dict:
    """Get statistics about skill executions."""
    stats = {
        "total_executions": 0,
        "by_skill": {},
        "by_outcome": {"success": 0, "failure": 0, "partial": 0, "unknown": 0},
        "recent": []
    }

    if not EXECUTIONS_FILE.exists():
        return stats

    executions = []
    try:
        with open(EXECUTIONS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    executions.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass

    # Count only "post" phase entries to avoid double counting
    for entry in executions:
        if entry.get("phase") == "post":
            stats["total_executions"] += 1
            skill = entry.get("skill", "unknown")

            if skill not in stats["by_skill"]:
                stats["by_skill"][skill] = {"count": 0, "success": 0, "failure": 0}

            stats["by_skill"][skill]["count"] += 1

            outcome = entry.get("outcome", "unknown")
            if outcome in stats["by_outcome"]:
                stats["by_outcome"][outcome] += 1
            else:
                stats["by_outcome"]["unknown"] += 1

            if outcome == "success":
                stats["by_skill"][skill]["success"] += 1
            elif outcome == "failure":
                stats["by_skill"][skill]["failure"] += 1

    # Get recent executions (last 10)
    post_entries = [e for e in executions if e.get("phase") == "post"]
    stats["recent"] = post_entries[-10:]

    return stats


def determine_outcome(tool_output: dict) -> str:
    """Determine outcome from tool output."""
    output_str = str(tool_output.get("output", ""))

    success_indicators = [
        "complete", "success", "done", "finished", "executed",
        "loaded", "invoked", "skill instructions"
    ]
    failure_indicators = [
        "error", "failed", "not found", "invalid", "exception",
        "timeout", "blocked"
    ]

    output_lower = output_str.lower()

    if any(ind in output_lower for ind in failure_indicators):
        return "failure"
    if any(ind in output_lower for ind in success_indicators):
        return "success"

    # If output has content, assume partial success
    if len(output_str) > 50:
        return "success"

    return "partial"


def handle_pre_tool(tool_input: dict) -> dict:
    """Handle PreToolUse for Skill tool."""
    skill_name = tool_input.get("skill", "unknown")
    args = tool_input.get("args", "")

    log_skill_execution(skill_name, args, "pre")

    return {"continue": True}


def handle_post_tool(tool_input: dict, tool_output: dict) -> dict:
    """Handle PostToolUse for Skill tool - capture outcome."""
    skill_name = tool_input.get("skill", "unknown")
    args = tool_input.get("args", "")
    outcome = determine_outcome(tool_output)

    log_skill_execution(skill_name, args, "post", outcome)

    return {"continue": True}


def main():
    """Main entry point for hook."""
    # Check for special commands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "stats":
            stats = get_skill_stats()
            print(json.dumps(stats, indent=2))
            return

        elif cmd == "reset":
            if EXECUTIONS_FILE.exists():
                EXECUTIONS_FILE.unlink()
            print(json.dumps({"reset": True}))
            return

    # Normal hook operation
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    hook_type = os.environ.get("CLAUDE_HOOK_TYPE", "pre")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_output", {})

    # Only process Skill tool invocations
    tool_name = input_data.get("tool_name", "")
    if tool_name != "Skill":
        print(json.dumps({"continue": True}))
        return

    if hook_type == "pre":
        result = handle_pre_tool(tool_input)
    else:
        result = handle_post_tool(tool_input, tool_output)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
