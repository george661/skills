#!/usr/bin/env python3
"""
AgentDB-First Metrics Collection Hook

Stores metrics in AgentDB as the primary source of truth, with local file backup
only if AgentDB is unavailable. Also stores reflexion episodes for learning.

Key differences from cost-capture.py:
1. SYNCHRONOUS AgentDB storage with verification (not fire-and-forget)
2. AgentDB is PRIMARY, local is BACKUP (not the reverse)
3. Stores reflexion episodes for pattern learning
4. Includes checkpoint sync for phase transitions

Usage:
  - Runs automatically via PostToolUse hook on SlashCommand
  - Manual: python3 metrics-agentdb.py <issue> <command> [success|failure]
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Import AgentDB client
try:
    from agentdb_client import (
        agentdb_request,
        store_pattern,
        store_episode,
        get_credentials,
        validate_issue_key,
        get_namespace
    )
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

    # Fallback validation if agentdb_client not available
    import re

    def validate_issue_key(issue_key: str) -> str:
        if not issue_key or not re.match(r'^[A-Za-z0-9_-]+$', issue_key):
            raise ValueError(f"Invalid issue key: {issue_key}")
        return issue_key.upper()

    def get_namespace() -> str:
        return os.environ.get('TENANT_NAMESPACE', 'default')

# Constants
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
LOCAL_BACKUP_DIR = Path.home() / ".claude" / "output"
LOCAL_COSTS_FILE = LOCAL_BACKUP_DIR / "costs.jsonl"
NAMESPACE = os.environ.get('TENANT_NAMESPACE', 'default')

# Tracked commands
TRACKED_COMMANDS = [
    "work", "validate", "implement", "create-implementation-plan",
    "review", "fix-pr", "resolve-pr",
    "plan", "groom", "validate-prp", "validate-groom", "fix-prp", "fix-groom",
    "next", "issue", "bug", "change",
    "audit", "investigate", "garden", "garden-accuracy",
    "garden-cache", "garden-readiness", "garden-relevancy",
    "sequence", "sequence-json",
    "consolidate-prs", "update-docs", "reclaim", "fix-pipeline",
    "loop:issue", "loop:epic", "loop:backlog",
    "metrics:baseline", "metrics:current", "metrics:compare",
    "metrics:report", "metrics:before-after",
]

# Model pricing (per 1M tokens)
# Local models are $0 — they run on Ollama via localhost
LOCAL_MODEL_PRICING = {'input': 0.0, 'output': 0.0, 'cache_read': 0.0, 'cache_write': 0.0}

MODEL_PRICING = {
    'claude-opus-4-6': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-sonnet-4-5-20250929': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-3-5-sonnet-20241022': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-haiku-4-5-20251001': {'input': 0.80, 'output': 4.0, 'cache_read': 0.08, 'cache_write': 1.0},
    'default': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
}

# Local Ollama model prefixes — any model matching these is $0 cost
LOCAL_MODEL_PREFIXES = (
    'qwen', 'deepseek', 'glm', 'llama', 'gemma', 'phi', 'devstral',
    'nomic', 'dolphin', 'mistral', 'codellama',
)

# Model tier classification
MODEL_TIERS = {
    'claude-opus': 'cloud_opus',
    'claude-sonnet': 'cloud_sonnet',
    'claude-haiku': 'cloud_haiku',
}


def classify_model(model_name: str) -> tuple:
    """Classify a model name into (tier, is_local) for metrics.

    Returns:
        (tier_name, is_local) e.g. ('local_primary', True) or ('cloud_opus', False)
    """
    model_lower = model_name.lower()

    # Check if it's a local model
    if any(model_lower.startswith(prefix) for prefix in LOCAL_MODEL_PREFIXES):
        # Classify by size: 32b+ = primary, <32b = fast
        if any(size in model_lower for size in [':32b', ':70b', ':27b', ':24b']):
            return ('local_primary', True)
        return ('local_fast', True)

    # Cloud model classification
    for prefix, tier in MODEL_TIERS.items():
        if prefix in model_lower:
            return (tier, False)

    return ('cloud_unknown', False)

# Phase transitions for auto-checkpointing
PHASE_TRANSITIONS = {
    'create-implementation-plan': 'planning',
    'implement': 'implementing',
    'review': 'reviewing',
    'fix-pr': 'fixing',
    'resolve-pr': 'merging',
    'validate': 'validating',
    'plan': 'epic-planning',
    'groom': 'grooming',
}


def find_current_session() -> Optional[Path]:
    """Find the most recently modified conversation file."""
    if not CLAUDE_PROJECTS.exists():
        return None

    jsonl_files = list(CLAUDE_PROJECTS.rglob("*.jsonl"))
    jsonl_files = [f for f in jsonl_files if not f.name.startswith('agent-')]

    if not jsonl_files:
        return None

    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def calculate_cost(usage: dict, model: str = 'default') -> float:
    """Calculate cost from usage stats. Local models are always $0."""
    if not usage or not isinstance(usage, dict):
        return 0.0

    _, is_local = classify_model(model)
    if is_local:
        return 0.0

    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])

    return (
        (usage.get('input_tokens', 0) / 1_000_000) * pricing['input'] +
        (usage.get('output_tokens', 0) / 1_000_000) * pricing['output'] +
        (usage.get('cache_read_input_tokens', 0) / 1_000_000) * pricing['cache_read'] +
        (usage.get('cache_creation_input_tokens', 0) / 1_000_000) * pricing['cache_write']
    )


def extract_session_metrics(session_file: Path) -> Dict[str, Any]:
    """Extract metrics from session file."""
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    model_used = 'default'
    first_ts = None
    last_ts = None
    tool_calls = 0
    errors = 0

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())

                    ts = entry.get('timestamp')
                    if ts:
                        if not first_ts:
                            first_ts = ts
                        last_ts = ts

                    if entry.get('type') == 'assistant':
                        message = entry.get('message', {})
                        usage = message.get('usage', {})
                        if usage:
                            model_used = message.get('model', 'default')
                            total_input += usage.get('input_tokens', 0)
                            total_output += usage.get('output_tokens', 0)
                            total_cache_read += usage.get('cache_read_input_tokens', 0)
                            total_cache_write += usage.get('cache_creation_input_tokens', 0)
                            total_cost += calculate_cost(usage, model_used)

                    if entry.get('type') == 'tool_use':
                        tool_calls += 1

                    if entry.get('type') == 'tool_result':
                        result = entry.get('result', {})
                        if isinstance(result, dict) and result.get('error'):
                            errors += 1
                except:
                    continue
    except Exception as e:
        return {'error': str(e)}

    return {
        'cost_usd': round(total_cost, 4),
        'tokens': {
            'input': total_input,
            'output': total_output,
            'cache_read': total_cache_read,
            'cache_write': total_cache_write,
            'total': total_input + total_output + total_cache_read + total_cache_write
        },
        'model': model_used,
        'session_file': session_file.name,
        'first_timestamp': first_ts,
        'last_timestamp': last_ts,
        'tool_calls': tool_calls,
        'errors': errors
    }


def extract_command_info(tool_input: dict) -> Optional[Tuple[str, str]]:
    """Extract command type and issue key from tool input."""
    command = tool_input.get("command", "")

    for tracked in TRACKED_COMMANDS:
        if command.startswith(f"/{tracked}"):
            parts = command.split()
            if len(parts) > 1:
                arg = parts[1].upper()
            else:
                arg = tracked.upper().replace(":", "-").replace("-", "_")
            return (tracked, arg)

    return None


def store_metrics_to_agentdb(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store metrics to AgentDB SYNCHRONOUSLY with verification.
    Returns storage result with success status.
    """
    if not AGENTDB_AVAILABLE:
        return {'stored': False, 'reason': 'agentdb_not_available'}

    try:
        # Check connectivity first
        creds = get_credentials()
        if not creds.get('apiKey'):
            return {'stored': False, 'reason': 'no_credentials'}

        issue = metrics.get('issue', 'unknown')
        command = metrics.get('command', 'unknown')
        cost = metrics.get('cost_usd', 0)
        namespace = metrics.get('namespace', NAMESPACE)

        # 1. Store as a metrics pattern (for cost analysis)
        pattern_result = store_pattern(
            task_type='command-metrics',
            pattern={
                'approach': f"{command} on {issue}",
                'success_rate': 1.0 if metrics.get('success', True) else 0.0,
                'metadata': metrics
            },
            namespace=namespace
        )

        # 2. Store as reflexion episode (for learning)
        reward = 1.0 if metrics.get('success', True) else 0.0
        # Penalize high-cost sessions slightly
        if cost > 50:
            reward = max(0.5, reward - 0.2)

        episode_result = store_episode(
            session_id=f"{namespace}-{issue}",
            task=f"{command}:{issue}",
            reward=reward,
            success=metrics.get('success', True),
            trajectory=[{
                'action': command,
                'cost': cost,
                'tokens': metrics.get('tokens', {}).get('total', 0),
                'tool_calls': metrics.get('tool_calls', 0),
                'errors': metrics.get('errors', 0)
            }],
            namespace=namespace
        )

        # CRITICAL: Verify both storage operations succeeded
        if not pattern_result and not episode_result:
            return {
                'stored': False,
                'reason': 'both_storage_operations_failed',
                'pattern_stored': pattern_result,
                'episode_stored': episode_result,
                'namespace': namespace
            }

        # Partial success - at least one operation worked
        all_stored = pattern_result and episode_result
        return {
            'stored': all_stored,
            'partial': not all_stored,
            'pattern_stored': pattern_result,
            'episode_stored': episode_result,
            'namespace': namespace
        }

    except Exception as e:
        return {'stored': False, 'reason': str(e)}


def store_checkpoint_to_agentdb(issue: str, phase: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Store checkpoint to AgentDB for cross-session persistence."""
    if not AGENTDB_AVAILABLE:
        return {'stored': False, 'reason': 'agentdb_not_available'}

    try:
        namespace = get_namespace() if AGENTDB_AVAILABLE else os.environ.get('TENANT_NAMESPACE', NAMESPACE)
        checkpoint_key = f"checkpoint-{issue}-{phase}"
        checkpoint_data = {
            'issue': issue,
            'phase': phase,
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'resumable': True
        }

        result = store_pattern(
            task_type='checkpoint',
            pattern={
                'approach': f"Checkpoint for {issue} at {phase}",
                'success_rate': 1.0,
                'metadata': checkpoint_data
            },
            namespace=namespace
        )

        return {'stored': result, 'key': checkpoint_key}

    except Exception as e:
        return {'stored': False, 'reason': str(e)}


def save_local_backup(metrics: Dict[str, Any]) -> bool:
    """Save metrics to local file as backup."""
    try:
        LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOCAL_COSTS_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(metrics) + '\n')
        return True
    except Exception:
        return False


def collect_and_store_metrics(issue_key: str, command: str, success: bool = True) -> Dict[str, Any]:
    """
    Main entry point: collect session metrics and store to AgentDB.
    Falls back to local storage only if AgentDB fails.
    """
    # Validate issue key to prevent injection
    try:
        issue_key = validate_issue_key(issue_key)
    except ValueError as e:
        return {"error": str(e)}

    session_file = find_current_session()
    if not session_file:
        return {"error": "No session file found"}

    session_metrics = extract_session_metrics(session_file)
    if 'error' in session_metrics:
        return session_metrics

    namespace = get_namespace() if AGENTDB_AVAILABLE else os.environ.get('TENANT_NAMESPACE', NAMESPACE)

    # Classify model for tier tracking
    model_name = session_metrics['model']
    model_tier, is_local = classify_model(model_name)

    # Compute latency from session timestamps
    latency_ms = 0
    try:
        start = session_metrics.get('first_timestamp')
        end = session_metrics.get('last_timestamp')
        if start and end:
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            latency_ms = int((end_dt - start_dt).total_seconds() * 1000)
    except (ValueError, TypeError):
        pass

    # Build complete metrics record
    metrics = {
        'issue': issue_key,
        'command': command,
        'success': success,
        'cost_usd': session_metrics['cost_usd'],
        'tokens': session_metrics['tokens'],
        'model': model_name,
        'model_tier': model_tier,
        'is_local': is_local,
        'latency_ms': latency_ms,
        'session_file': session_metrics['session_file'],
        'tool_calls': session_metrics.get('tool_calls', 0),
        'errors': session_metrics.get('errors', 0),
        'captured_at': datetime.now().isoformat(),
        'session_start': session_metrics.get('first_timestamp'),
        'session_end': session_metrics.get('last_timestamp'),
        'namespace': namespace
    }

    # 1. PRIMARY: Store to AgentDB (synchronous, verified)
    agentdb_result = store_metrics_to_agentdb(metrics)

    # 2. BACKUP: Store locally only if AgentDB failed
    local_stored = False
    if not agentdb_result.get('stored'):
        local_stored = save_local_backup(metrics)
        print(f"[metrics] AgentDB failed ({agentdb_result.get('reason')}), saved to local backup", file=sys.stderr)

    # 3. Auto-checkpoint on phase transitions
    checkpoint_result = None
    phase = PHASE_TRANSITIONS.get(command)
    if phase:
        checkpoint_result = store_checkpoint_to_agentdb(
            issue_key,
            phase,
            {'command': command, 'metrics': metrics}
        )

    return {
        "collected": True,
        "issue": issue_key,
        "command": command,
        "cost_usd": metrics['cost_usd'],
        "tokens": metrics['tokens']['total'],
        "agentdb": agentdb_result,
        "local_backup": local_stored,
        "checkpoint": checkpoint_result
    }


def handle_post_tool(tool_input: dict) -> dict:
    """Handle PostToolUse for SlashCommand."""
    cmd_info = extract_command_info(tool_input)

    if cmd_info:
        command, issue_key = cmd_info
        # Default to success=True, can be overridden
        result = collect_and_store_metrics(issue_key, command, success=True)

        storage_status = "AgentDB" if result.get('agentdb', {}).get('stored') else "local"
        print(f"[metrics] {issue_key} {command} ${result.get('cost_usd', 0):.2f} -> {storage_status}", file=sys.stderr)

        return {"continue": True, "metrics_captured": result}

    return {"continue": True}


def main():
    """Main entry point."""
    # Manual invocation: python3 metrics-agentdb.py <issue> <command> [success|failure]
    if len(sys.argv) >= 3:
        try:
            issue_key = validate_issue_key(sys.argv[1])
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            return
        command = sys.argv[2].lower()
        success = sys.argv[3].lower() != 'failure' if len(sys.argv) > 3 else True
        result = collect_and_store_metrics(issue_key, command, success)
        print(json.dumps(result, indent=2))
        return

    # Hook invocation via stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    tool_input = input_data.get("tool_input", {})
    result = handle_post_tool(tool_input)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
