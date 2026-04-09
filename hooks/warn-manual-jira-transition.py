#!/usr/bin/env python3
"""
PreToolUse hook that warns when manual Jira transitions are attempted.
Checks memory for active workflow context.
"""

import json
import sys

def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        input_data = {}

    tool_name = input_data.get("tool_name", "")

    # Only warn for transition_issue tool
    if "transition_issue" in tool_name:
        # Output warning to stderr (visible to user)
        warning = """
WARNING: MANUAL JIRA TRANSITION DETECTED

Consider using workflow commands instead:
  /work PROJ-XXX      - Full implementation workflow
  /validate PROJ-XXX  - Post-deployment validation

Workflows provide automatic step labels, memory context, and cost tracking.

Proceeding with manual transition...
"""
        print(warning, file=sys.stderr)

    # Always allow the operation to continue
    result = {"continue": True}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
