#!/usr/bin/env python3
"""
PreToolUse hook: Inject domain context into superpowers skills.

Intercepts Skill tool invocations and, for superpowers:* skills,
adds domain model context to the approval reason so the skill
has awareness of bounded contexts.

Opt-in: Approves silently if TENANT_DOMAIN_PATH is not set or
domain-index.json does not exist.
"""

import json
import os
import sys

# Process-level cache for domain index
_DOMAIN_CACHE = {}


def load_domain_index(index_file):
    """Load domain index with caching."""
    global _DOMAIN_CACHE

    # Check cache first
    if index_file in _DOMAIN_CACHE:
        return _DOMAIN_CACHE[index_file]

    try:
        with open(index_file) as f:
            idx = json.load(f)
        # Cache for session lifetime
        _DOMAIN_CACHE[index_file] = idx
        return idx
    except (json.JSONDecodeError, IOError):
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, IOError):
        print(json.dumps({"decision": "allow"}))
        return

    tool_input = data.get('tool_input', {})
    skill_name = tool_input.get('skill', '')

    # Only activate for superpowers:* skills
    if not skill_name.startswith('superpowers:'):
        print(json.dumps({"decision": "allow"}))
        return

    domain_path = os.environ.get('TENANT_DOMAIN_PATH', '')
    domain_index = os.environ.get('TENANT_DOMAIN_INDEX', 'domain-index.json')

    if not domain_path:
        print(json.dumps({"decision": "allow"}))
        return

    index_file = os.path.join(domain_path, domain_index)
    if not os.path.exists(index_file):
        print(json.dumps({"decision": "allow"}))
        return

    # Load with caching
    idx = load_domain_index(index_file)
    if not idx:
        print(json.dumps({"decision": "allow"}))
        return

    contexts = idx.get('contexts', {})
    counts = idx.get('meta', {}).get('counts', {})
    context_names = list(contexts.keys())
    num_contexts = counts.get('contexts', len(contexts))

    reason = (
        f"DOMAIN CONTEXT: This project follows domain-driven development with "
        f"{num_contexts} bounded contexts: {', '.join(context_names)}. "
        f"Before planning or implementing, identify the affected bounded context. "
        f"Use domain-context skill (.claude/skills/domain-context.skill.md) for lookups. "
        f"Use CML skills (.claude/skills/cml/) for model operations. "
        f"Changes MUST align with the domain model to avoid churn."
    )

    print(json.dumps({"decision": "allow", "reason": reason}))


if __name__ == '__main__':
    main()
