#!/usr/bin/env python3
"""
SessionStart hook - Pattern Scorer for decay, score adjustment, and cache refresh.

Runs at session start to:
1. Decay stale pattern scores
2. Adjust scores based on usage outcomes
3. Refresh the local anti-pattern cache
4. Check for failure promotion candidates

Graceful degradation: if AgentDB is unavailable, skip silently.
"""

import json
import os
import sys
from pathlib import Path

# Import agentdb client
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from agentdb_client import agentdb_request
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

CACHE_DIR = os.path.join(str(Path.home()), '.claude', 'cache')
CACHE_PATH = os.path.join(CACHE_DIR, 'anti-patterns.json')
TIMEOUT = 5


def safe_request(method, path, body=None):
    """Make a request with timeout and graceful error handling."""
    try:
        return agentdb_request(method, path, body, timeout=TIMEOUT)
    except Exception as e:
        print(f"[pattern-scorer] Request failed ({path}): {e}", file=sys.stderr)
        return None


def run_decay():
    """Call decay endpoint to reduce stale pattern scores."""
    result = safe_request('POST', '/api/v1/maintenance/decay', {
        'decay_amount': 0.05,
        'decay_interval_days': 30,
    })
    if result:
        count = result.get('decayed_count', result.get('content', 'unknown'))
        print(f"[pattern-scorer] Decay applied: {count}", file=sys.stderr)
    return result


def run_score_adjust():
    """Call score-adjust endpoint to update scores from usage outcomes."""
    result = safe_request('POST', '/api/v1/maintenance/score-adjust', {})
    if result:
        count = result.get('adjusted_count', result.get('content', 'unknown'))
        print(f"[pattern-scorer] Score adjust: {count}", file=sys.stderr)
    return result


def refresh_cache():
    """Fetch anti-patterns and write to local cache file."""
    result = safe_request('POST', '/api/v1/pattern/search', {
        'task': 'anti-pattern',
        'k': 50,
        'weighted': True,
    })

    if not result:
        return False

    results = result.get('results', [])

    # Filter client-side for success_rate <= 0.5
    anti_patterns = [
        r for r in results
        if r.get('success_rate', 1.0) <= 0.5
    ]

    # Write cache
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_PATH, 'w') as f:
            json.dump(anti_patterns, f, indent=2)
        print(f"[pattern-scorer] Cache refreshed: {len(anti_patterns)} anti-patterns", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[pattern-scorer] Failed to write cache: {e}", file=sys.stderr)
        return False


def check_promotion_candidates():
    """Check for failure patterns that could be promoted to anti-patterns."""
    result = safe_request('POST', '/api/v1/reflexion/failure-summary', {
        'threshold': 3,
    })

    if not result:
        return 0

    candidates = result.get('candidates', [])
    if candidates:
        count = len(candidates)
        print(
            f"[pattern-scorer] {count} failure pattern(s) eligible for promotion. "
            "Run /review-patterns to review.",
            file=sys.stderr
        )
        return count
    return 0


def main():
    # Read hook input (may be empty on session start)
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else '{}'
        json.loads(raw) if raw.strip() else {}
    except Exception:
        pass

    if not AGENTDB_AVAILABLE:
        print("[pattern-scorer] AgentDB client not available, skipping", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return

    # Step 1: Decay stale scores
    run_decay()

    # Step 2: Adjust scores from usage
    run_score_adjust()

    # Step 3: Refresh anti-pattern cache
    refresh_cache()

    # Step 4: Check promotion candidates
    check_promotion_candidates()

    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
