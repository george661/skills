#!/usr/bin/env python3
"""
Pre-session hook: Load tenant configuration from AppConfig/file.

This hook runs at agent session start and exports tenant-specific values
as environment variables that commands and skills can use.

Configuration sources (in priority order):
1. APPCONFIG_BACKUP_FILE environment variable (path to routing.json)
2. /config/routing.json (default container mount point)
3. ../issue-daemon/config/routing.gw.json (local development fallback)

Exported environment variables:
- TENANT_ID: Tenant identifier (e.g., 'default', 'myproject')
- TENANT_NAMESPACE: Memory namespace for this tenant
- TENANT_PROJECT: Primary Jira project key
- TENANT_VCS: VCS provider ('bitbucket' or 'github')
- TENANT_WORKSPACE: VCS workspace/org name
- TENANT_REPOS: Comma-separated list of repositories
- TENANT_BASE_BRANCH: Default base branch for PRs
- TENANT_BRANCH_PREFIX: Prefix for agent-created branches
- TENANT_RUNTIME: Agent runtime type ('ecs', 'local', 'remote')
- REPO_{ROLE}: Repository name for each role (e.g., REPO_API, REPO_FRONTEND)
- TENANT_APP_URL_DEV: App URL for the dev environment (used by validate-deploy-status)
- TENANT_APP_URL_DEMO: App URL for the demo environment
- TENANT_APP_URL_PROD: App URL for the prod environment
- TENANT_DOTENV_PATH: Path to the .env credentials file (used by dispatch-local.py)
"""

import json
import os
import sys
from pathlib import Path


def find_config_file() -> Path | None:
    """Find the tenant configuration file from various sources."""
    # Priority 1: Explicit environment variable
    if env_path := os.environ.get('APPCONFIG_BACKUP_FILE'):
        path = Path(env_path)
        if path.exists():
            return path
        # Try relative to current directory
        rel_path = Path.cwd() / env_path
        if rel_path.exists():
            return rel_path

    # Priority 2: Container mount point (ECS/Docker)
    container_path = Path('/config/routing.json')
    if container_path.exists():
        return container_path

    # Priority 3: Local development - sibling issue-daemon directory
    # Try to find issue-daemon relative to agents
    current = Path.cwd()

    # Check if we're in agents or a subdirectory
    for parent in [current] + list(current.parents):
        if (parent / '.claude' / 'hooks').exists():
            # Found agents root, look for sibling issue-daemon
            sibling_configs = [
                parent.parent / 'issue-daemon' / 'config' / 'routing.gw.json',
                parent.parent / 'issue-daemon' / 'config' / 'routing.json',
            ]
            for config_path in sibling_configs:
                if config_path.exists():
                    return config_path
            break

    return None


def load_config(config_path: Path) -> dict:
    """Load and parse the configuration file."""
    with open(config_path) as f:
        return json.load(f)


def extract_tenant_values(config: dict) -> dict[str, str]:
    """Extract tenant-specific values from the configuration."""
    values = {}

    # Tenant identifier
    values['TENANT_ID'] = config.get('tenant', 'default')

    # Agent configuration
    agent = config.get('agent', {})

    # Memory namespace
    memory = agent.get('memory', {})
    values['TENANT_NAMESPACE'] = memory.get('namespace', values['TENANT_ID'])

    # VCS configuration
    vcs = agent.get('vcs', {})
    values['TENANT_VCS'] = vcs.get('provider', 'bitbucket')
    values['TENANT_REPOS'] = ','.join(vcs.get('repos', []))

    # CI configuration
    ci = agent.get('ci', {})
    values['TENANT_CI_PROVIDER'] = ci.get('provider', 'concourse')  # concourse | github-actions | bitbucket-pipelines

    # Defaults
    defaults = agent.get('defaults', {})
    values['TENANT_BASE_BRANCH'] = defaults.get('baseBranch', 'main')
    values['TENANT_BRANCH_PREFIX'] = defaults.get('branchPrefix', 'agent/')

    # Runtime
    runtime = agent.get('runtime', {})
    values['TENANT_RUNTIME'] = runtime.get('type', 'ecs')

    # Context file (relative to config directory)
    values['TENANT_CONTEXT_FILE'] = agent.get('contextFile', '')

    # Repository roles (e.g., api -> api-service, frontend -> frontend-app)
    repo_roles = agent.get('repoRoles', {})
    for role, repo_name in repo_roles.items():
        # Convert role to uppercase env var name: api -> REPO_API
        env_key = f'REPO_{role.upper()}'
        values[env_key] = repo_name

    # Services configuration
    services = config.get('services', {})

    # Jira
    jira = services.get('jira', {})
    project_keys = jira.get('projectKeys', [])
    values['TENANT_PROJECT'] = project_keys[0] if project_keys else ''
    values['TENANT_JIRA_HOST'] = jira.get('host', '')

    # Bitbucket/GitHub workspace
    bitbucket = services.get('bitbucket', {})
    github = services.get('github', {})
    values['TENANT_WORKSPACE'] = bitbucket.get('workspace') or github.get('org', '')

    # Workspace root - derive from config path or use current directory
    # In container: /workspace, locally: parent of config directory or cwd
    if 'TENANT_CONFIG_DIR' in values:
        # Assume repos are siblings of issue-daemon
        config_parent = Path(values['TENANT_CONFIG_DIR']).parent.parent
        values['WORKSPACE_ROOT'] = str(config_parent) + '/'
    else:
        values['WORKSPACE_ROOT'] = str(Path.cwd()) + '/'

    # Docs/domain configuration (opt-in)
    docs = agent.get('docs', {})
    docs_path = docs.get('path', '')

    # Fallback: derive from DOCS_REPO env var or workspace root + repo name
    if not docs_path:
        project_root = os.environ.get('PROJECT_ROOT', '')
        docs_repo = os.environ.get('DOCS_REPO', 'project-docs')
        docs_path = os.path.join(project_root, docs_repo) if project_root else ''
    if not docs_path and values.get('WORKSPACE_ROOT'):
        docs_repo = docs.get('repo', '')
        if docs_repo:
            docs_path = values['WORKSPACE_ROOT'] + docs_repo

    values['DOCS_REPO'] = os.path.basename(docs_path) if docs_path else docs.get('repo', 'project-docs')
    values['TENANT_DOCS_ENABLED'] = str(docs.get('enabled', bool(docs_path))).lower()

    # Domain model paths (derived from docs path)
    domain_path = docs.get('domainPath', '')
    if not domain_path and docs_path:
        domain_path = docs_path + '/domain'
    values['TENANT_DOMAIN_PATH'] = domain_path
    values['TENANT_DOMAIN_INDEX'] = docs.get('domainIndex', 'domain-index.json')

    # App environment URLs (used by dispatch-local.py for deploy status checks)
    environments = agent.get('environments', {})
    values['TENANT_APP_URL_DEV'] = environments.get('dev', {}).get('appUrl', '')
    values['TENANT_APP_URL_DEMO'] = environments.get('demo', {}).get('appUrl', '')
    values['TENANT_APP_URL_PROD'] = environments.get('prod', {}).get('appUrl', '')

    # Dotenv path for credentials (used by dispatch-local.py)
    # Can be set explicitly in routing.json agent.dotenvPath (relative to WORKSPACE_ROOT)
    # or falls back to $WORKSPACE_ROOT/.env
    dotenv_relative = agent.get('dotenvPath', '')
    workspace = values.get('WORKSPACE_ROOT', '').rstrip('/')
    if dotenv_relative and workspace:
        dotenv_path = workspace + '/' + dotenv_relative.lstrip('/')
    elif workspace:
        dotenv_path = workspace + '/.env'
    else:
        dotenv_path = ''
    values['TENANT_DOTENV_PATH'] = dotenv_path

    return values


def write_env_file(values: dict[str, str], output_path: Path):
    """Write environment variables to a sourceable file."""
    with open(output_path, 'w') as f:
        for key, value in values.items():
            # Escape any special characters in values
            escaped_value = value.replace('"', '\\"')
            f.write(f'export {key}="{escaped_value}"\n')


def main():
    """Main entry point."""
    # Find configuration file
    config_path = find_config_file()

    if not config_path:
        print("Warning: No tenant configuration found. Using defaults.", file=sys.stderr)
        print("Searched locations:", file=sys.stderr)
        print("  - $APPCONFIG_BACKUP_FILE environment variable", file=sys.stderr)
        print("  - /config/routing.json (container mount)", file=sys.stderr)
        print("  - ../issue-daemon/config/routing.gw.json (local dev)", file=sys.stderr)

        # Export minimal defaults
        values = {
            'TENANT_ID': 'default',
            'TENANT_NAMESPACE': 'default',
            'TENANT_PROJECT': '',
            'TENANT_VCS': 'bitbucket',
            'TENANT_WORKSPACE': '',
            'TENANT_REPOS': '',
            'TENANT_BASE_BRANCH': 'main',
            'TENANT_BRANCH_PREFIX': 'agent/',
            'TENANT_RUNTIME': 'local',
            'TENANT_CI_PROVIDER': 'concourse',
            'TENANT_JIRA_HOST': '',
            'TENANT_CONTEXT_FILE': '',
            'WORKSPACE_ROOT': str(Path.cwd()) + '/',
            'DOCS_REPO': 'project-docs',
            'TENANT_DOCS_ENABLED': 'false',
            'TENANT_DOMAIN_PATH': '',
            'TENANT_DOMAIN_INDEX': 'domain-index.json',
            'TENANT_APP_URL_DEV': '',
            'TENANT_APP_URL_DEMO': '',
            'TENANT_APP_URL_PROD': '',
            'TENANT_DOTENV_PATH': str(Path.cwd()) + '/.env',
        }
    else:
        print(f"Loading tenant config from: {config_path}", file=sys.stderr)
        config = load_config(config_path)
        values = extract_tenant_values(config)
        # Add config directory for resolving relative paths like contextFile
        values['TENANT_CONFIG_DIR'] = str(config_path.parent)

    # Write to env file for sourcing
    env_file = Path('/tmp/tenant.env')
    write_env_file(values, env_file)

    # Print summary
    print(f"Tenant: {values['TENANT_ID']}", file=sys.stderr)
    print(f"  Namespace: {values['TENANT_NAMESPACE']}", file=sys.stderr)
    print(f"  Project: {values['TENANT_PROJECT']}", file=sys.stderr)
    print(f"  VCS: {values['TENANT_VCS']}", file=sys.stderr)
    print(f"  Runtime: {values['TENANT_RUNTIME']}", file=sys.stderr)
    print(f"Environment written to: {env_file}", file=sys.stderr)

    # Also print to stdout for direct sourcing: eval $(python load-tenant-config.py)
    for key, value in values.items():
        escaped_value = value.replace('"', '\\"')
        print(f'export {key}="{escaped_value}"')


if __name__ == '__main__':
    main()
