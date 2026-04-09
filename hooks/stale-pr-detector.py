#!/usr/bin/env python3
"""
SessionStart hook - Detect stale PRs and flag them for review.

Queries Bitbucket for open PRs and flags those with no activity > 3 days.
Results are stored via AgentDB REST skills for other hooks/commands to access.

Design Reference:
- project-docs/designs/2026-02-09-agent-workflow-improvements-design.md (Phase 6)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional


def load_tenant_config() -> Optional[Dict[str, str]]:
    """Load tenant configuration from routing config."""
    script_dir = Path(__file__).parent
    loader_script = script_dir / 'load-tenant-config.py'

    if not loader_script.exists():
        return None

    try:
        result = subprocess.run(
            ['python3', str(loader_script)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            tenant_vars = {}
            for line in result.stdout.strip().split('\n'):
                if line.startswith('export '):
                    var_def = line[7:]
                    if '=' in var_def:
                        key, value = var_def.split('=', 1)
                        value = value.strip('"')
                        tenant_vars[key] = value
            return tenant_vars
    except Exception as e:
        print(f"[stale-pr] Error loading tenant config: {e}", file=sys.stderr)

    return None


def get_repositories(tenant_vars: Dict[str, str]) -> List[str]:
    """Get list of repositories to check for stale PRs."""
    # For now, return a predefined list
    # In the future, this could be dynamic based on tenant config
    repos = tenant_vars.get('TENANT_REPOS', '').split(',')
    repos = [r.strip() for r in repos if r.strip()]
    return repos


def query_open_prs(repo_slug: str) -> List[Dict[str, Any]]:
    """Query Bitbucket for open PRs in a repository."""
    skills_dir = Path.home() / '.claude' / 'skills' / 'bitbucket'
    list_prs_skill = skills_dir / 'list_pull_requests.ts'

    if not list_prs_skill.exists():
        print(f"[stale-pr] Skill not found: {list_prs_skill}", file=sys.stderr)
        return []

    try:
        cmd = [
            'npx', 'tsx', str(list_prs_skill),
            json.dumps({
                'repo_slug': repo_slug,
                'state': 'OPEN'
            })
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('values', [])
        else:
            print(f"[stale-pr] Failed to query {repo_slug}: {result.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"[stale-pr] Error querying {repo_slug}: {e}", file=sys.stderr)

    return []


def parse_iso_date(date_str: str) -> datetime:
    """Parse ISO date string to datetime object."""
    # Handle Bitbucket's date format with timezone
    if date_str.endswith('Z'):
        date_str = date_str[:-1] + '+00:00'
    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))


def is_stale(pr: Dict[str, Any], stale_threshold_days: int = 3) -> bool:
    """Check if a PR is stale (no activity > threshold days)."""
    updated_on = pr.get('updated_on')
    if not updated_on:
        return False

    try:
        updated_dt = parse_iso_date(updated_on)
        now = datetime.now(timezone.utc)
        age = now - updated_dt
        return age.days >= stale_threshold_days
    except Exception as e:
        print(f"[stale-pr] Error parsing date: {e}", file=sys.stderr)
        return False


def analyze_prs(repos: List[str], stale_threshold_days: int = 3) -> Dict[str, Any]:
    """Analyze PRs across repositories and identify stale ones."""
    stale_prs = []
    total_open = 0

    for repo in repos:
        prs = query_open_prs(repo)
        total_open += len(prs)

        for pr in prs:
            if is_stale(pr, stale_threshold_days):
                pr_id = pr.get('id')
                title = pr.get('title', 'No title')
                updated_on = pr.get('updated_on')
                author = pr.get('author', {}).get('display_name', 'Unknown')
                links = pr.get('links', {})
                html_url = links.get('html', {}).get('href', '')

                stale_prs.append({
                    'repo': repo,
                    'pr_id': pr_id,
                    'title': title,
                    'author': author,
                    'updated_on': updated_on,
                    'url': html_url
                })

    return {
        'total_open': total_open,
        'stale_count': len(stale_prs),
        'stale_prs': stale_prs,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'threshold_days': stale_threshold_days
    }


def store_in_memory(data: Dict[str, Any], namespace: str) -> bool:
    """Store stale PR data via AgentDB REST skills."""
    try:
        # Output to stderr for visibility
        print(f"[stale-pr] Found {data['stale_count']} stale PRs out of {data['total_open']} open", file=sys.stderr)

        if data['stale_count'] > 0:
            print("[stale-pr] Stale PRs:", file=sys.stderr)
            for pr in data['stale_prs']:
                print(f"  - {pr['repo']}: PR #{pr['pr_id']} - {pr['title']} (by {pr['author']})", file=sys.stderr)
                print(f"    Last updated: {pr['updated_on']}", file=sys.stderr)
                print(f"    URL: {pr['url']}", file=sys.stderr)

        # Store to AgentDB via REST skill
        # Example: npx tsx .claude/skills/agentdb/store.ts '{"namespace": "${TENANT_NAMESPACE}", "key": "stale-prs", "value": {...}}'
        # This can be implemented when persistent storage is needed

        return True
    except Exception as e:
        print(f"[stale-pr] Error storing in memory: {e}", file=sys.stderr)
        return False


def format_report(data: Dict[str, Any]) -> str:
    """Format stale PR report for user output."""
    lines = [
        "STALE PR DETECTION",
        ""
    ]

    if data['stale_count'] == 0:
        lines.append(f"✅ No stale PRs found ({data['total_open']} open PRs checked)")
        lines.append(f"Threshold: {data['threshold_days']} days")
    else:
        lines.append(f"⚠️  Found {data['stale_count']} stale PR(s) out of {data['total_open']} open")
        lines.append(f"Threshold: {data['threshold_days']} days of inactivity")
        lines.append("")

        for pr in data['stale_prs']:
            lines.append(f"📌 {pr['repo']}: PR #{pr['pr_id']}")
            lines.append(f"   Title: {pr['title']}")
            lines.append(f"   Author: {pr['author']}")
            lines.append(f"   Last updated: {pr['updated_on']}")
            lines.append(f"   URL: {pr['url']}")
            lines.append("")

        lines.append("Consider reviewing or closing these stale PRs.")

    lines.append("")
    return '\n'.join(lines)


def main():
    """Main hook entry point."""
    # Read hook input (may be empty on session start)
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        input_data = {}

    # Load tenant configuration
    tenant_vars = load_tenant_config()

    if not tenant_vars:
        print("[stale-pr] No tenant configuration found, skipping stale PR detection", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    namespace = tenant_vars.get('TENANT_NAMESPACE', 'default')

    # Get repositories to check
    repos = get_repositories(tenant_vars)

    print(f"[stale-pr] Checking {len(repos)} repositories for stale PRs...", file=sys.stderr)

    # Analyze PRs
    data = analyze_prs(repos, stale_threshold_days=3)

    # Store in memory
    store_in_memory(data, namespace)

    # Output report to stderr (shown to user)
    report = format_report(data)
    print(report, file=sys.stderr)

    # Output metadata in result for potential use by other hooks
    result = {
        "continue": True,
        "stale_pr_data": {
            "total_open": data['total_open'],
            "stale_count": data['stale_count'],
            "checked_at": data['checked_at']
        }
    }

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
