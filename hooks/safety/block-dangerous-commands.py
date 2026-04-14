#!/usr/bin/env python3
import json
import re
import sys

DANGEROUS_PATTERNS = [
    r'^rm\s+-rf\s+/$',           # rm -rf /
    r'^rm\s+-rf\s+/\*',          # rm -rf /*
    r'^chmod\s+777\s+/',         # chmod 777 /
    r'>\s*/dev/[sh]d[a-z]',      # > /dev/sda
    r'dd.*of=/dev/[sh]d[a-z]',   # dd to raw disk
    r'dd.*of\s*=\s*/dev/[sh]d[a-z]'  # dd with spaces around =
]

def check_command(command):
    """Check if command is dangerous"""
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return {
                "decision": "deny",
                "reason": f"BLOCKED: Dangerous command detected - {command[:50]}"
            }
    return {"decision": "approve"}

if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        command = data.get("tool_input", {}).get("command", "")
        result = check_command(command)
    except Exception:
        result = {"decision": "approve"}
    print(json.dumps(result))
