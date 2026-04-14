#!/usr/bin/env python3
"""
PreToolUse hook - Pattern Guard for anti-pattern blocking.

Checks tool calls against cached anti-patterns and either blocks (Tier 1),
warns (Tier 2), or allows (Tier 3) based on success_rate thresholds.

Input (stdin JSON):
  {"tool_name": "Bash", "tool_input": {"command": "..."}}

Output:
  Tier 1 (success_rate < 0.1): {"error": "BLOCKED: <approach>"}
  Tier 2 (0.1 <= success_rate <= 0.3): warning to stderr + {"continue": true}
  Tier 3 / no match: {"continue": true}
"""

import json
import os
import re
import sys
import threading
from pathlib import Path

# Import agentdb client for async usage logging
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from agentdb_client import agentdb_request
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

CACHE_PATH = os.path.join(str(Path.home()), '.claude', 'cache', 'anti-patterns.json')


def load_cache():
    """Load the anti-pattern cache file. Returns empty list if missing/invalid."""
    try:
        if not os.path.exists(CACHE_PATH):
            return []
        with open(CACHE_PATH) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def extract_command(tool_input):
    """Extract the command string from tool_input."""
    if isinstance(tool_input, dict):
        return tool_input.get('command', '')
    return str(tool_input)


def match_anti_patterns(command, patterns):
    """Match command against cached anti-patterns.

    Returns list of (pattern, tier) tuples sorted by tier (lowest first).
    """
    matches = []
    for pattern in patterns:
        task_type = pattern.get('task_type', '')
        pattern.get('approach', '')
        success_rate = pattern.get('success_rate', 1.0)

        # Build regex from task_type keywords (strip anti-pattern- prefix)
        keywords = task_type.replace('anti-pattern-', '').replace('-', '|')
        try:
            if re.search(keywords, command, re.IGNORECASE):
                if success_rate < 0.1:
                    tier = 1
                elif success_rate <= 0.3:
                    tier = 2
                else:
                    tier = 3
                matches.append((pattern, tier))
        except re.error:
            continue

    matches.sort(key=lambda x: x[1])
    return matches


def log_usage_async(pattern_id, session_id):
    """Asynchronously log pattern usage to AgentDB."""
    if not AGENTDB_AVAILABLE:
        return
    try:
        def _log():
            try:
                agentdb_request('POST', '/api/v1/pattern/log-usage', {
                    'pattern_id': pattern_id,
                    'session_id': session_id,
                    'context': 'pattern-guard-match'
                }, timeout=5)
            except Exception:
                pass

        thread = threading.Thread(target=_log, daemon=True)
        thread.start()
    except Exception:
        pass


def main():
    # Read hook input from stdin
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        input_data = json.loads(raw) if raw.strip() else {}
    except Exception:
        print(json.dumps({"continue": True}))
        return

    tool_name = input_data.get('tool_name', '')
    tool_input = input_data.get('tool_input', {})

    # Only process Bash and Skill tools
    if tool_name not in ('Bash', 'Skill'):
        print(json.dumps({"continue": True}))
        return

    # Load cached anti-patterns
    patterns = load_cache()
    if not patterns:
        print(json.dumps({"continue": True}))
        return

    # Extract command from tool input
    command = extract_command(tool_input)
    if not command:
        print(json.dumps({"continue": True}))
        return

    # Match against anti-patterns
    matches = match_anti_patterns(command, patterns)
    if not matches:
        print(json.dumps({"continue": True}))
        return

    # Get session ID for usage logging
    session_id = os.environ.get('CLAUDE_SESSION_ID', 'unknown')

    # Process the highest-priority match (lowest tier)
    pattern, tier = matches[0]

    # Log usage for all matches asynchronously
    for matched_pattern, _ in matches:
        pattern_id = matched_pattern.get('id', matched_pattern.get('task_type', ''))
        log_usage_async(str(pattern_id), session_id)

    if tier == 1:
        # Block the tool call
        approach = pattern.get('approach', 'Unknown anti-pattern')
        print(json.dumps({"error": f"BLOCKED: {approach}"}))
        return

    if tier == 2:
        # Warn but allow
        approach = pattern.get('approach', 'Unknown anti-pattern')
        task_type = pattern.get('task_type', '')
        print(f"[pattern-guard] WARNING ({task_type}): {approach}", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return

    # Tier 3 or no actionable match
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
