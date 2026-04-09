#!/usr/bin/env python3
"""
Validate environment configuration for all configured providers.

Non-blocking hook — warns on stderr but always emits {"decision": "allow"}
on stdout so the session is never prevented from starting.
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Provider → required env-var definitions
# ---------------------------------------------------------------------------

# Always required (regardless of provider selection)
ALWAYS_REQUIRED = {
    "TENANT_PROJECT_OR_JIRA_PROJECT_KEYS": ["TENANT_PROJECT", "JIRA_PROJECT_KEYS"],  # either/or
    "PROJECT_ROOT": ["PROJECT_ROOT"],
}

ISSUE_TRACKER_VARS = {
    "jira": ["JIRA_HOST", "JIRA_USERNAME", "JIRA_API_TOKEN"],
    "github": ["GITHUB_TOKEN", "GITHUB_OWNER"],
    "linear": ["LINEAR_API_KEY"],
}

VCS_PROVIDER_VARS = {
    "bitbucket": ["BITBUCKET_WORKSPACE", "BITBUCKET_USERNAME", "BITBUCKET_TOKEN"],
    "github": ["GITHUB_TOKEN", "GITHUB_OWNER"],
}

CI_PROVIDER_VARS = {
    "concourse": ["CONCOURSE_URL"],
    "github_actions": ["GITHUB_TOKEN", "GITHUB_OWNER"],
}

OPTIONAL_VARS = ["AGENTDB_URL", "SLACK_BOT_TOKEN", "TENANT_DOMAIN_PATH"]

# Connectivity endpoints per provider type
CONNECTIVITY_ENDPOINTS = {
    "issue_tracker": {
        "jira": lambda: f"https://{os.environ.get('JIRA_HOST', '')}/rest/api/3/serverInfo",
        "github": lambda: "https://api.github.com/octocat",
        "linear": lambda: "https://api.linear.app/graphql",
    },
    "vcs_provider": {
        "bitbucket": lambda: "https://api.bitbucket.org/2.0/user",
        "github": lambda: "https://api.github.com/octocat",
    },
    "ci_provider": {
        "concourse": lambda: f"{os.environ.get('CONCOURSE_URL', '').rstrip('/')}/api/v1/info",
        "github_actions": lambda: "https://api.github.com/octocat",
    },
}


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------

def _env(name):
    """Return env value or empty string."""
    return os.environ.get(name, "")


def build_status_table():
    """Build a list of (variable, status, provider) tuples and a missing count."""
    rows = []
    missing_count = 0

    # --- always-required (either/or for TENANT_PROJECT / JIRA_PROJECT_KEYS) ---
    tp = _env("TENANT_PROJECT")
    jpk = _env("JIRA_PROJECT_KEYS")
    if tp or jpk:
        if tp:
            rows.append(("TENANT_PROJECT", "SET", "core"))
        if jpk:
            rows.append(("JIRA_PROJECT_KEYS", "SET", "core"))
    else:
        rows.append(("TENANT_PROJECT", "MISSING", "core"))
        rows.append(("JIRA_PROJECT_KEYS", "MISSING", "core"))
        missing_count += 1  # counts as one logical requirement

    pr = _env("PROJECT_ROOT")
    if pr:
        rows.append(("PROJECT_ROOT", "SET", "core"))
    else:
        rows.append(("PROJECT_ROOT", "MISSING", "core"))
        missing_count += 1

    # --- per-provider checks ---
    issue_tracker = _env("ISSUE_TRACKER").lower()
    vcs_provider = _env("VCS_PROVIDER").lower()
    ci_provider = _env("CI_PROVIDER").lower()

    warnings = []

    def _check(var_list, provider_label):
        nonlocal missing_count
        for var in var_list:
            val = _env(var)
            if val:
                rows.append((var, "SET", provider_label))
            else:
                rows.append((var, "MISSING", provider_label))
                missing_count += 1

    if issue_tracker:
        if issue_tracker in ISSUE_TRACKER_VARS:
            _check(ISSUE_TRACKER_VARS[issue_tracker], f"issue_tracker:{issue_tracker}")
        else:
            warnings.append(f"Unknown ISSUE_TRACKER value: '{issue_tracker}'")

    if vcs_provider:
        if vcs_provider in VCS_PROVIDER_VARS:
            _check(VCS_PROVIDER_VARS[vcs_provider], f"vcs_provider:{vcs_provider}")
        else:
            warnings.append(f"Unknown VCS_PROVIDER value: '{vcs_provider}'")

    if ci_provider:
        if ci_provider in CI_PROVIDER_VARS:
            _check(CI_PROVIDER_VARS[ci_provider], f"ci_provider:{ci_provider}")
        else:
            warnings.append(f"Unknown CI_PROVIDER value: '{ci_provider}'")

    # --- optional vars ---
    for var in OPTIONAL_VARS:
        val = _env(var)
        rows.append((var, "SET" if val else "OPTIONAL", "optional"))

    return rows, missing_count, warnings


def format_table(rows):
    """Return a human-readable table string."""
    if not rows:
        return ""
    col_widths = [
        max(len(r[0]) for r in rows),
        max(len(r[1]) for r in rows),
        max(len(r[2]) for r in rows),
    ]
    header = f"{'Variable':<{col_widths[0]}}  {'Status':<{col_widths[1]}}  {'Provider':<{col_widths[2]}}"
    sep = "-" * len(header)
    lines = [header, sep]
    for var, status, provider in rows:
        lines.append(f"{var:<{col_widths[0]}}  {status:<{col_widths[1]}}  {provider:<{col_widths[2]}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Connectivity checks (--check-connectivity)
# ---------------------------------------------------------------------------

def check_connectivity():
    """Attempt lightweight HTTP requests to configured provider endpoints.

    Results are printed to stderr.  Uses only the standard library.
    """
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    issue_tracker = _env("ISSUE_TRACKER").lower()
    vcs_provider = _env("VCS_PROVIDER").lower()
    ci_provider = _env("CI_PROVIDER").lower()

    checks = []

    for category, provider_val, endpoints in [
        ("issue_tracker", issue_tracker, CONNECTIVITY_ENDPOINTS["issue_tracker"]),
        ("vcs_provider", vcs_provider, CONNECTIVITY_ENDPOINTS["vcs_provider"]),
        ("ci_provider", ci_provider, CONNECTIVITY_ENDPOINTS["ci_provider"]),
    ]:
        if not provider_val:
            checks.append((category, "skipped", "no provider configured"))
            continue
        if provider_val not in endpoints:
            checks.append((category, "skipped", f"unknown provider '{provider_val}'"))
            continue

        url = endpoints[provider_val]()
        if not url or url.startswith("https:///") or url.startswith("http:///"):
            checks.append((category, "skipped", "endpoint URL incomplete"))
            continue

        try:
            if provider_val == "linear":
                # Linear requires a POST with an introspection query
                req = Request(
                    url,
                    data=b'{"query":"{ __typename }"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
            else:
                req = Request(url, method="GET")
            resp = urlopen(req, timeout=5)
            checks.append((category, "reachable", f"{resp.status} {url}"))
        except URLError as exc:
            checks.append((category, "unreachable", f"{exc.reason} {url}"))
        except Exception as exc:
            checks.append((category, "unreachable", f"{exc} {url}"))

    if checks:
        print("\nConnectivity:", file=sys.stderr)
        for category, status, detail in checks:
            print(f"  {category}: {status} — {detail}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_config(check_conn=False):
    """Run validation.  Returns (rows, missing_count, warnings)."""
    rows, missing_count, warnings = build_status_table()

    print("\n--- Provider Config Validation ---", file=sys.stderr)
    table_str = format_table(rows)
    if table_str:
        print(table_str, file=sys.stderr)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if missing_count:
        print(
            f"WARNING: {missing_count} required variable(s) missing for configured providers",
            file=sys.stderr,
        )

    if check_conn:
        check_connectivity()

    print("--- End Config Validation ---\n", file=sys.stderr)

    return rows, missing_count, warnings


def main():
    check_conn = "--check-connectivity" in sys.argv

    # Read stdin (hook protocol) — may be empty
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass

    validate_config(check_conn=check_conn)

    # Always allow — never block session start
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
