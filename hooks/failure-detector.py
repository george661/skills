#!/usr/bin/env python3
"""
PostToolUse hook - Failure Detector for episode storage.

Scans tool_result text for known failure signatures and stores reflexion
episodes in AgentDB when matches are found. Never blocks tool execution.

Input (stdin JSON):
  {"tool_name": "Bash", "tool_input": {"command": "..."}, "tool_result": "combined text output"}

Output:
  Always {"continue": true} (PostToolUse never blocks)
"""

import json
import os
import re
import sys
import threading
from pathlib import Path

# Import agentdb client for async episode storage
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from agentdb_client import agentdb_request, get_namespace
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

# Config search paths (installed location first, then source)
CONFIG_PATHS = [
    os.path.join(str(Path.home()), '.claude', 'config', 'failure-signatures.json'),
    os.path.join(str(Path(__file__).parent.parent), 'config', 'failure-signatures.json'),
]


def load_signatures():
    """Load failure signatures from config file. Returns empty list if missing/invalid."""
    for config_path in CONFIG_PATHS:
        try:
            if not os.path.exists(config_path):
                continue
            with open(config_path) as f:
                data = json.load(f)
            return data.get('signatures', [])
        except Exception:
            continue
    return []


def extract_result_text(tool_result):
    """Extract text from tool_result. It may be a string or dict."""
    if isinstance(tool_result, str):
        return tool_result
    if isinstance(tool_result, dict):
        # Combine all string values for matching
        parts = []
        for key in ('stdout', 'stderr', 'output', 'error', 'message'):
            val = tool_result.get(key, '')
            if val:
                parts.append(str(val))
        if parts:
            return '\n'.join(parts)
        return str(tool_result)
    return str(tool_result)


def match_signatures(result_text, signatures):
    """Match result text against failure signatures. Returns list of matches."""
    matches = []
    for sig in signatures:
        pattern = sig.get('pattern', '')
        if not pattern:
            continue
        try:
            match = re.search(pattern, result_text, re.IGNORECASE)
            if match:
                matches.append({
                    'type': sig.get('type', 'unknown'),
                    'suggested_fix': sig.get('suggested_fix', ''),
                    'matched_text': match.group(0)[:200],
                    'promotion_threshold': sig.get('promotion_threshold', 3),
                })
        except re.error:
            continue
    return matches


def store_episode_async(sig_match, command, namespace):
    """Asynchronously store a reflexion episode for a failure match."""
    if not AGENTDB_AVAILABLE:
        return

    def _store():
        try:
            session_id = os.environ.get('CLAUDE_SESSION_ID', namespace)
            agentdb_request('POST', '/api/v1/reflexion/store', {
                'session_id': session_id,
                'task': f"{sig_match['type']}: {command[:100]}",
                'reward': 0.0,
                'success': False,
                'critique': f"Failure detected: {sig_match['matched_text']}. Fix: {sig_match['suggested_fix']}",
                'namespace': namespace,
            }, timeout=5)
        except Exception:
            pass

    thread = threading.Thread(target=_store, daemon=True)
    thread.start()


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
    tool_result = input_data.get('tool_result', '')

    # Only process Bash and Skill tools
    if tool_name not in ('Bash', 'Skill'):
        print(json.dumps({"continue": True}))
        return

    # Extract text from tool_result
    result_text = extract_result_text(tool_result)
    if not result_text:
        print(json.dumps({"continue": True}))
        return

    # Load failure signatures
    signatures = load_signatures()
    if not signatures:
        print(json.dumps({"continue": True}))
        return

    # Match against signatures
    matches = match_signatures(result_text, signatures)

    if matches:
        # Extract command for context
        command = ''
        if isinstance(tool_input, dict):
            command = tool_input.get('command', '')
        elif isinstance(tool_input, str):
            command = tool_input

        namespace = get_namespace() if AGENTDB_AVAILABLE else 'default'

        for sig_match in matches:
            print(
                f"[failure-detector] Detected: {sig_match['type']} - {sig_match['suggested_fix']}",
                file=sys.stderr
            )
            store_episode_async(sig_match, command, namespace)

    # PostToolUse never blocks
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
