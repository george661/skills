#!/usr/bin/env python3
"""
On-demand AgentDB memory context loader.
Loads memory context only when explicitly requested by commands/skills.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Import agentdb client
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from agentdb_client import agentdb_request
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False


def load_memory_context(task_context=None):
    """
    Load relevant memory context from AgentDB on-demand.

    Args:
        task_context: Optional task context string. If not provided,
                     will use current directory and git branch.

    Returns:
        str: Formatted memory context or empty string if unavailable
    """
    if not AGENTDB_AVAILABLE:
        return ""

    # Build task context if not provided
    if not task_context:
        cwd = os.getcwd()
        branch = ""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, timeout=5, cwd=cwd
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
        except Exception:
            pass

        task_context = f"{os.path.basename(cwd)}"
        if branch:
            task_context += f" {branch}"

    # Retrieve relevant episodes
    try:
        result = agentdb_request('POST', '/api/v1/reflexion/retrieve-relevant', {
            'task': task_context,
            'k': 3,
        }, timeout=5)

        if not result:
            return ""

        episodes = result.get('results', [])
        if not episodes:
            return ""

        lines = ["[MEMORY CONTEXT]", ""]
        for ep in episodes:
            task = ep.get('task', 'unknown')
            reward = ep.get('reward', 0.0)
            success = ep.get('success', False)
            critique = ep.get('critique', '')
            status = 'SUCCESS' if success else 'FAILURE'
            lines.append(f"  - [{status}] {task} (reward: {reward:.1f})")
            if critique:
                lines.append(f"    {critique[:150]}")

        lines.append("")
        lines.append("[END MEMORY CONTEXT]")
        return "\n".join(lines)

    except Exception as e:
        print(f"[WARN] AgentDB unavailable - continuing without memory context", file=sys.stderr)
        return ""


def load_anti_pattern_summary():
    """
    Load anti-pattern cache summary on-demand.

    Returns:
        str: Anti-pattern summary or empty string if unavailable
    """
    ANTI_PATTERN_CACHE = os.path.join(str(Path.home()), '.claude', 'cache', 'anti-patterns.json')

    try:
        if not os.path.exists(ANTI_PATTERN_CACHE):
            return ""

        with open(ANTI_PATTERN_CACHE) as f:
            patterns = json.load(f)

        if not patterns:
            return ""

        count = len(patterns)
        tier1 = sum(1 for p in patterns if p.get('success_rate', 1.0) < 0.1)
        tier2 = sum(1 for p in patterns if 0.1 <= p.get('success_rate', 1.0) <= 0.3)

        lines = [f"[ANTI-PATTERNS] {count} cached ({tier1} blocking, {tier2} warnings)"]
        return "\n".join(lines)
    except Exception:
        return ""


def load_heartbeat_brief():
    """
    Load latest heartbeat brief from second-brain state on-demand.

    Reads ~/.claude/second-brain/alerts.json and ~/.claude/second-brain/state/
    to produce a concise status summary for session start context.

    Returns:
        str: Formatted heartbeat brief or empty string if unavailable
    """
    sb_dir = Path.home() / ".claude" / "second-brain"
    alerts_file = sb_dir / "alerts.json"

    lines = []

    # Check for P1 alerts
    try:
        if alerts_file.exists():
            with open(alerts_file) as f:
                alerts_data = json.load(f)
            p1_alerts = alerts_data.get("p1_alerts", [])
            if p1_alerts:
                lines.append(f"[HEARTBEAT] {len(p1_alerts)} P1 alert(s):")
                for alert in p1_alerts[:3]:
                    alert_type = alert.get("type", "unknown")
                    integration = alert.get("integration", "unknown")
                    synthesis = alert.get("synthesis", "")[:100]
                    lines.append(f"  - [{alert_type}] {integration}: {synthesis}")
    except Exception:
        pass

    # Check daily log for recent activity
    daily_dir = sb_dir / "daily"
    if daily_dir.exists():
        try:
            today = __import__("datetime").date.today().isoformat()
            daily_log = daily_dir / f"{today}.md"
            if daily_log.exists():
                content = daily_log.read_text()
                # Count sessions today
                session_count = content.count("## ")
                if session_count > 0:
                    lines.append(f"[HEARTBEAT] {session_count} session(s) captured today")
        except Exception:
            pass

    if not lines:
        return ""

    return "\n".join(lines)


def load_active_recall(task_context=None):
    """
    Load active recall context from both AgentDB and second-brain daily logs.

    Combines AgentDB episode memory with recent daily log entries to provide
    richer context for the current task.

    Args:
        task_context: Optional task context string for AgentDB query.

    Returns:
        str: Combined recall context or empty string if unavailable
    """
    parts = []

    # Part 1: AgentDB memory (reuse existing function)
    agentdb_context = load_memory_context(task_context)
    if agentdb_context:
        parts.append(agentdb_context)

    # Part 2: Recent daily log entries (last 3 sessions)
    sb_dir = Path.home() / ".claude" / "second-brain" / "daily"
    if sb_dir.exists():
        try:
            today = __import__("datetime").date.today().isoformat()
            daily_log = sb_dir / f"{today}.md"
            if daily_log.exists():
                content = daily_log.read_text()
                # Get last 3 session entries (sections start with ##)
                sections = content.split("\n## ")
                recent = sections[-3:] if len(sections) > 3 else sections[1:]
                if recent:
                    lines = ["[DAILY LOG - Recent Sessions]"]
                    for section in recent:
                        # Truncate each section
                        truncated = section[:200].strip()
                        if truncated:
                            lines.append(f"  ## {truncated}")
                    lines.append("[END DAILY LOG]")
                    parts.append("\n".join(lines))
        except Exception:
            pass

    return "\n\n".join(parts)


if __name__ == "__main__":
    # Test the loader
    context = load_memory_context()
    if context:
        print(context)
    else:
        print("No memory context available")

    brief = load_heartbeat_brief()
    if brief:
        print(brief)

    recall = load_active_recall()
    if recall:
        print(recall)