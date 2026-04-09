#!/usr/bin/env python3
"""
Session-start hook: Inject ambient domain model context.

Reads the domain-index.json and prints a concise domain model summary
to stderr so it appears in the session context.

Opt-in: Silently exits if TENANT_DOMAIN_PATH or TENANT_DOMAIN_INDEX
are not set, or if the index file does not exist.
"""

import json
import os
import sys


def main():
    domain_path = os.environ.get('TENANT_DOMAIN_PATH', '')
    domain_index = os.environ.get('TENANT_DOMAIN_INDEX', 'domain-index.json')

    if not domain_path:
        sys.exit(0)

    index_file = os.path.join(domain_path, domain_index)
    if not os.path.exists(index_file):
        sys.exit(0)

    try:
        with open(index_file) as f:
            idx = json.load(f)
    except (json.JSONDecodeError, IOError):
        sys.exit(0)

    meta = idx.get('meta', {})
    contexts = idx.get('contexts', {})
    counts = meta.get('counts', {})

    print("--- DOMAIN MODEL ---", file=sys.stderr)
    print(f"Vision: {meta.get('domainVision', 'N/A')}", file=sys.stderr)
    print(
        f"Model: {counts.get('contexts', len(contexts))} contexts, "
        f"{counts.get('aggregates', 0)} aggregates, "
        f"{counts.get('commands', 0)} commands, "
        f"{counts.get('events', 0)} events",
        file=sys.stderr
    )
    print("", file=sys.stderr)
    print("Bounded Contexts:", file=sys.stderr)
    for name, ctx in contexts.items():
        implements = ctx.get('implements', '')
        vision = ctx.get('vision', '')[:60]
        print(f"  {name} ({implements}) — {vision}...", file=sys.stderr)

    print("", file=sys.stderr)
    print("IMPORTANT: Before planning or implementing, identify the affected bounded context(s).", file=sys.stderr)
    print("Use domain-context skill for lookups: .claude/skills/domain-context.skill.md", file=sys.stderr)
    print("Use CML skills for model operations: .claude/skills/cml/", file=sys.stderr)
    print("--- END DOMAIN MODEL ---", file=sys.stderr)


if __name__ == '__main__':
    main()
