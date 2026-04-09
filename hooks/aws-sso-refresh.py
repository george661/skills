#!/usr/bin/env python3
"""
PostToolUse:Bash hook — detects expired AWS SSO tokens and auto-refreshes.

When an AWS CLI command fails with a token expiry error, this hook:
1. Extracts the active AWS profile from the command or environment
2. Runs `aws sso login --profile <profile>` (opens browser for user approval)
3. Blocks the tool result with a retry instruction once login completes

The `aws sso login` subprocess relays its output via stderr so the user
can see the browser URL/confirmation messages in the Claude Code terminal.
"""

import json
import os
import re
import subprocess
import sys

# Patterns that indicate an expired or invalid AWS SSO token.
# Checked case-insensitively against the combined command output.
EXPIRY_PATTERNS = [
    "Token has expired and refresh failed",
    "ExpiredTokenException",
    "Error loading SSO Token",
    "SSO Token has expired",
    "credentials have expired",
    "Your authentication tokens have expired",
    "token is expired",
    "TokenExpiredError",
    "The security token included in the request is expired",
    "Unable to refresh SSO token",
]


def is_aws_token_expired(text: str) -> bool:
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in EXPIRY_PATTERNS)


def extract_profile(command: str) -> str | None:
    """Return the AWS profile from --profile flag, AWS_PROFILE, or None."""
    match = re.search(r'--profile\s+(\S+)', command)
    if match:
        return match.group(1)
    return os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE") or None


def main():
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        input_data = {}

    command = input_data.get("tool_input", {}).get("command", "")
    tool_result = input_data.get("tool_result", "")
    result_str = str(tool_result) if not isinstance(tool_result, str) else tool_result

    # Only act on AWS CLI commands
    if not re.search(r'\baws\b', command):
        return

    if not is_aws_token_expired(result_str):
        return

    profile = extract_profile(command)

    login_cmd = ["aws", "sso", "login"]
    if profile:
        login_cmd += ["--profile", profile]

    profile_label = profile or "default"
    print(
        f"[aws-sso-refresh] AWS SSO token expired (profile: {profile_label}). "
        f"Running: {' '.join(login_cmd)}",
        file=sys.stderr,
    )

    try:
        # Capture aws sso login output so we can relay it — browser still opens
        # via `open` regardless of whether stdout/stderr are pipes.
        proc = subprocess.run(
            login_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Relay login output to the user via stderr (hook-loader passes this through)
        combined = (proc.stdout + proc.stderr).strip()
        if combined:
            print(combined, file=sys.stderr)

        if proc.returncode == 0:
            print(
                json.dumps({
                    "decision": "block",
                    "reason": (
                        f"AWS SSO token refreshed (profile: {profile_label}). "
                        "Please retry the previous command."
                    ),
                })
            )
        else:
            print(
                f"[aws-sso-refresh] aws sso login failed (exit {proc.returncode}). "
                "Run `aws sso login` manually then retry.",
                file=sys.stderr,
            )

    except subprocess.TimeoutExpired:
        print(
            "[aws-sso-refresh] aws sso login timed out (120s). "
            f"Run `aws sso login --profile {profile_label}` manually then retry.",
            file=sys.stderr,
        )
    except FileNotFoundError:
        print(
            "[aws-sso-refresh] `aws` CLI not found in PATH — cannot auto-refresh token.",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[aws-sso-refresh] Unexpected error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
