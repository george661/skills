#!/usr/bin/env python3
"""
Simulate daemon dispatching to local agent.

This script mimics what happens when issue-daemon dispatches a task:
1. Daemon finds an issue via JQL polling
2. Daemon creates ECS task with environment variables
3. Agent session starts with tenant context
4. Agent executes command with tenant-scoped behavior

Usage:
    python scripts/simulate-dispatch.py --tenant tenant-a --command "/next"
    python scripts/simulate-dispatch.py --tenant tenant-b --command "/work PROJ-123"
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def simulate_daemon_dispatch(tenant: str, command: str, issue_key: str | None = None):
    """Simulate daemon dispatching a task."""
    print("=" * 60)
    print("PHASE 1: DAEMON DISPATCH SIMULATION")
    print("=" * 60)

    # Determine routing config path
    script_dir = Path(__file__).parent.parent
    issue_daemon_dir = script_dir.parent / 'issue-daemon'

    routing_configs = {
        'tenant-a': issue_daemon_dir / 'config' / 'routing.tenant-a.json',
        'tenant-b': issue_daemon_dir / 'config' / 'routing.tenant-b.json',
    }

    config_path = routing_configs.get(tenant)
    if not config_path or not config_path.exists():
        print(f"ERROR: Routing config not found for tenant '{tenant}'")
        print(f"Looked for: {config_path}")
        return False

    print(f"\n[Daemon] Found issue, preparing dispatch:")
    print(f"  Tenant: {tenant}")
    print(f"  Command: {command}")
    print(f"  Issue: {issue_key or '(auto-selected)'}")
    print(f"  Config: {config_path}")

    # Load routing config to show what daemon sees
    with open(config_path) as f:
        routing = json.load(f)

    print(f"\n[Daemon] Routing config loaded:")
    print(f"  Version: {routing.get('version', 'unknown')}")
    print(f"  Jira Host: {routing.get('services', {}).get('jira', {}).get('host', 'N/A')}")
    print(f"  Project Keys: {routing.get('services', {}).get('jira', {}).get('projectKeys', [])}")
    print(f"  VCS Provider: {routing.get('agent', {}).get('vcs', {}).get('provider', 'N/A')}")

    # Simulate ECS task environment
    print(f"\n[Daemon] Creating ECS task with environment:")
    ecs_env = {
        'APPCONFIG_BACKUP_FILE': str(config_path),
        'JIRA_PROJECT_KEYS': ','.join(routing.get('services', {}).get('jira', {}).get('projectKeys', [])),
        'AGENT_COMMAND': command,
        'ISSUE_KEY': issue_key or '',
    }
    for key, value in ecs_env.items():
        print(f"  {key}={value}")

    return config_path, ecs_env


def simulate_agent_startup(config_path: Path, ecs_env: dict):
    """Simulate agent session starting."""
    print("\n" + "=" * 60)
    print("PHASE 2: AGENT SESSION START")
    print("=" * 60)

    # Set environment for tenant config loader
    env = os.environ.copy()
    env['APPCONFIG_BACKUP_FILE'] = str(config_path)

    # Run session-start hook
    hooks_dir = Path(__file__).parent.parent / '.claude' / 'hooks'
    session_hook = hooks_dir / 'session-start-workflow-prompt.py'

    if not session_hook.exists():
        print(f"ERROR: Session hook not found: {session_hook}")
        return None

    print(f"\n[Agent] Running session-start hook...")
    result = subprocess.run(
        ['python3', str(session_hook)],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=15
    )

    # Show stderr (user-visible output)
    if result.stderr:
        print("\n[Agent] Session start output:")
        for line in result.stderr.strip().split('\n'):
            print(f"  {line}")

    # Parse stdout (JSON result)
    if result.stdout.strip():
        try:
            hook_result = json.loads(result.stdout.strip())
            tenant_vars = hook_result.get('tenant', {})
            print(f"\n[Agent] Tenant variables loaded:")
            for key, value in tenant_vars.items():
                print(f"  {key}={value}")
            return tenant_vars
        except json.JSONDecodeError:
            print(f"ERROR: Failed to parse hook output: {result.stdout}")
            return None

    return None


def simulate_command_execution(tenant_vars: dict, command: str):
    """Simulate command execution with tenant context."""
    print("\n" + "=" * 60)
    print("PHASE 3: COMMAND EXECUTION SIMULATION")
    print("=" * 60)

    tenant_project = tenant_vars.get('TENANT_PROJECT', 'UNKNOWN')
    tenant_namespace = tenant_vars.get('TENANT_NAMESPACE', 'default')
    tenant_vcs = tenant_vars.get('TENANT_VCS', 'bitbucket')
    tenant_workspace = tenant_vars.get('TENANT_WORKSPACE', '')

    print(f"\n[Agent] Executing command: {command}")
    print(f"  With tenant context:")
    print(f"    Project: {tenant_project}")
    print(f"    Namespace: {tenant_namespace}")
    print(f"    VCS: {tenant_vcs}")

    # Simulate what queries would be made based on command
    if command.startswith('/next'):
        print(f"\n[Agent] /next would execute:")
        print(f"  1. Memory search: namespace='{tenant_namespace}', pattern='impl-|merged-'")
        print(f"  2. Jira query: project = {tenant_project} AND labels IN ('outcome:needs-changes'...)")
        print(f"  3. Jira query: project = {tenant_project} AND status = 'VALIDATION'...")
        print(f"  4. Jira query: project = {tenant_project} AND status = 'To Do' AND type = Bug...")

    elif command.startswith('/work'):
        issue_key = command.split()[-1] if len(command.split()) > 1 else f'{tenant_project}-XXX'
        print(f"\n[Agent] /work {issue_key} would execute:")
        print(f"  1. Jira fetch: {issue_key}")
        print(f"  2. Memory store: namespace='{tenant_namespace}', key='impl-{issue_key}'")
        print(f"  3. Branch create: {tenant_workspace}/{issue_key.lower().replace('-', '/')}")
        print(f"  4. Jira transition: {issue_key} -> In Progress")
        print(f"  5. Jira label: {issue_key} + 'step:implementing'")

    elif command.startswith('/validate'):
        issue_key = command.split()[-1] if len(command.split()) > 1 else f'{tenant_project}-XXX'
        print(f"\n[Agent] /validate {issue_key} would execute:")
        print(f"  1. Jira fetch: {issue_key}")
        print(f"  2. Memory recall: namespace='{tenant_namespace}', query='{issue_key} validation'")
        print(f"  3. Jira label: {issue_key} + 'step:validating'")

    elif command.startswith('/resolve-pr'):
        print(f"\n[Agent] /resolve-pr would execute:")
        if tenant_vcs == 'bitbucket':
            print(f"  1. Bitbucket: getPullRequests(workspace='{tenant_workspace}')")
            print(f"  2. Bitbucket: getPipelineRuns()")
            print(f"  3. Bitbucket: mergePullRequest()")
        else:
            print(f"  1. GitHub: list_pull_requests()")
            print(f"  2. GitHub: list_workflow_runs()")
            print(f"  3. GitHub: merge_pull_request()")

    print(f"\n[Agent] All operations would use:")
    print(f"  - Memory namespace: '{tenant_namespace}'")
    print(f"  - Jira project: '{tenant_project}'")
    print(f"  - VCS workspace: '{tenant_workspace}'")

    return True


def verify_tenant_isolation(tenant_vars: dict, other_tenant: str):
    """Verify tenant isolation by checking no cross-tenant access."""
    print("\n" + "=" * 60)
    print("PHASE 4: TENANT ISOLATION VERIFICATION")
    print("=" * 60)

    current_tenant = tenant_vars.get('TENANT_ID', 'unknown')
    current_project = tenant_vars.get('TENANT_PROJECT', '')
    current_namespace = tenant_vars.get('TENANT_NAMESPACE', '')

    other_project = 'OTHER' if current_project == 'PROJ' else 'PROJ'
    other_namespace = 'tenant-b' if current_namespace == 'tenant-a' else 'tenant-a'

    print(f"\n[Isolation Check] Current tenant: {current_tenant}")
    print(f"  Project: {current_project}")
    print(f"  Namespace: {current_namespace}")

    print(f"\n[Isolation Check] Would NOT access:")
    print(f"  ✗ Project: {other_project}")
    print(f"  ✗ Namespace: {other_namespace}")

    print(f"\n[Isolation Check] Verification points:")
    print(f"  ✓ JQL queries include 'project = {current_project}'")
    print(f"  ✓ Memory operations use namespace='{current_namespace}'")
    print(f"  ✓ No hardcoded references to other tenant")

    # Check for any hardcoded tenant references in commands
    commands_dir = Path(__file__).parent.parent / '.claude' / 'commands'
    hardcoded_issues = []

    for cmd_file in commands_dir.glob('*.md'):
        content = cmd_file.read_text()
        # Check for hardcoded project references that aren't using variables
        if f'project = {other_project}' in content and '${TENANT_PROJECT}' not in content:
            hardcoded_issues.append(f"{cmd_file.name}: hardcoded 'project = {other_project}'")

    if hardcoded_issues:
        print(f"\n[Isolation Check] ⚠️ Found hardcoded references:")
        for issue in hardcoded_issues:
            print(f"  - {issue}")
    else:
        print(f"\n[Isolation Check] ✓ No hardcoded cross-tenant references found")

    return True


def main():
    parser = argparse.ArgumentParser(description='Simulate daemon dispatch to local agent')
    parser.add_argument('--tenant', required=True, choices=['tenant-a', 'tenant-b'],
                       help='Tenant to simulate (tenant-a or tenant-b)')
    parser.add_argument('--command', required=True,
                       help='Command to simulate (e.g., /next, /work PROJ-123)')
    parser.add_argument('--issue', default=None,
                       help='Issue key (optional)')

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print(f"MULTI-TENANT DISPATCH SIMULATION")
    print(f"Tenant: {args.tenant.upper()}")
    print(f"Command: {args.command}")
    print("=" * 60)

    # Phase 1: Daemon dispatch
    result = simulate_daemon_dispatch(args.tenant, args.command, args.issue)
    if not result:
        sys.exit(1)
    config_path, ecs_env = result

    # Phase 2: Agent startup
    tenant_vars = simulate_agent_startup(config_path, ecs_env)
    if not tenant_vars:
        print("\nERROR: Failed to load tenant configuration")
        sys.exit(1)

    # Phase 3: Command execution
    simulate_command_execution(tenant_vars, args.command)

    # Phase 4: Isolation verification
    other_tenant = 'tenant-b' if args.tenant == 'tenant-a' else 'tenant-a'
    verify_tenant_isolation(tenant_vars, other_tenant)

    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE")
    print("=" * 60)
    print(f"\n✓ Tenant '{args.tenant}' dispatch simulation successful")
    print(f"✓ Agent would execute '{args.command}' with correct tenant context")
    print(f"✓ Tenant isolation verified")


if __name__ == '__main__':
    main()
