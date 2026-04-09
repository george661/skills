#!/usr/bin/env python3
"""
TESTING.md Parser Hook

Parses repository TESTING.md files to extract standardized configuration
for workflow commands. Provides technology-agnostic command extraction.

Standardized Sections:
- Pre-Commit Requirements: Steps to run before committing (lint, format, test)
- Required Tests by Change Type: Which test types for which file changes
- Test Data: Fixture mappings from shared test data repository

Falls back to technology detection if sections are missing.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# Import AgentDB client for memory storage (optional dependency)
try:
    from agentdb_client import agentdb_request, get_namespace
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False


# Technology detection patterns and their default commands
TECH_DEFAULTS = {
    'go': {
        'indicators': ['go.mod', 'go.sum'],
        'pre_commit': [
            {'step': 'Format', 'command': 'go fmt ./...', 'auto_fix': True},
            {'step': 'Lint', 'command': 'golangci-lint run', 'auto_fix': False},
            {'step': 'Unit Tests', 'command': 'go test ./...', 'auto_fix': False},
        ],
        'test_types': {
            'handlers': ['Unit', 'Hurl'],
            'models': ['Unit'],
            'pkg': ['Unit'],
        }
    },
    'typescript': {
        'indicators': ['package.json', 'tsconfig.json'],
        'pre_commit': [
            {'step': 'Format', 'command': 'npm run format', 'auto_fix': True},
            {'step': 'Lint', 'command': 'npm run lint', 'auto_fix': False},
            {'step': 'Type Check', 'command': 'npm run typecheck', 'auto_fix': False},
            {'step': 'Unit Tests', 'command': 'npm test', 'auto_fix': False},
        ],
        # Alternative type-check script names to try (in order of preference)
        'typecheck_alternatives': ['typecheck', 'type-check', 'type:check', 'tsc'],
        'test_types': {
            'components': ['Unit', 'E2E'],
            'hooks': ['Unit'],
            'services': ['Unit', 'Integration'],
            'utils': ['Unit'],
        }
    },
    'python': {
        'indicators': ['pyproject.toml', 'requirements.txt', 'setup.py'],
        'pre_commit': [
            {'step': 'Format', 'command': 'black .', 'auto_fix': True},
            {'step': 'Lint', 'command': 'ruff check .', 'auto_fix': False},
            {'step': 'Type Check', 'command': 'mypy .', 'auto_fix': False},
            {'step': 'Unit Tests', 'command': 'pytest', 'auto_fix': False},
        ],
        'test_types': {
            'src': ['Unit'],
            'api': ['Unit', 'Integration'],
        }
    }
}


def detect_technology(repo_path: str) -> Optional[str]:
    """
    Detect repository technology from indicator files.

    Priority order matters: Go > Python > TypeScript
    (A Go project might have package.json for tooling)

    Also checks common subdirectories for multi-module repos.
    """
    repo = Path(repo_path)

    # Directories to check (root + common subdirs for mono-repos)
    check_dirs = [
        repo,
        repo / 'src',
        repo / 'cmd',
        repo / 'pkg',
        repo / 'functions',
        repo / 'lambda',  # auth-service pattern
    ]

    # Also check first-level subdirs of functions/ (Lambda pattern)
    functions_dir = repo / 'functions'
    if functions_dir.exists():
        for subdir in functions_dir.iterdir():
            if subdir.is_dir():
                check_dirs.append(subdir)
                break  # Only need to find one

    # Check in priority order
    priority_order = ['go', 'python', 'typescript']

    for tech in priority_order:
        config = TECH_DEFAULTS.get(tech, {})
        for indicator in config.get('indicators', []):
            for check_dir in check_dirs:
                if (check_dir / indicator).exists():
                    return tech

    return None


def parse_markdown_table(content: str, section_header: str) -> List[Dict[str, str]]:
    """
    Parse a markdown table under a specific section header.

    Returns list of dicts with column headers as keys.
    """
    lines = content.split('\n')
    in_section = False
    table_lines = []
    headers = []

    for line in lines:
        # Check for section header
        if re.match(rf'^#{{1,3}}\s+{re.escape(section_header)}', line, re.IGNORECASE):
            in_section = True
            continue

        # Check for next section (exit)
        if in_section and re.match(r'^#{1,3}\s+', line) and section_header.lower() not in line.lower():
            break

        if in_section:
            # Skip empty lines before table
            if not line.strip():
                continue

            # Table header row
            if '|' in line and not headers:
                # Extract headers
                cells = [c.strip() for c in line.split('|') if c.strip()]
                headers = cells
                continue

            # Separator row (skip)
            if '|' in line and re.match(r'^[\s|:-]+$', line):
                continue

            # Data row
            if '|' in line and headers:
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if len(cells) >= len(headers):
                    row = {headers[i]: cells[i] for i in range(len(headers))}
                    table_lines.append(row)

    return table_lines


def parse_pre_commit_requirements(content: str) -> List[Dict[str, Any]]:
    """
    Parse Pre-Commit Requirements section.

    Expected format:
    ## Pre-Commit Requirements

    | Step | Command | Auto-Fix |
    |------|---------|----------|
    | Format | `go fmt ./...` | Yes |
    """
    rows = parse_markdown_table(content, 'Pre-Commit Requirements')

    requirements = []
    for row in rows:
        step = row.get('Step', '')
        command = row.get('Command', '')
        auto_fix = row.get('Auto-Fix', 'No')

        # Clean up command (remove backticks)
        command = re.sub(r'^`|`$', '', command)

        # Parse auto-fix boolean
        auto_fix_bool = auto_fix.lower() in ('yes', 'true', '1')

        if step and command:
            requirements.append({
                'step': step,
                'command': command,
                'auto_fix': auto_fix_bool
            })

    return requirements


def parse_required_tests(content: str) -> Dict[str, List[str]]:
    """
    Parse Required Tests by Change Type section.

    Expected format:
    ## Required Tests by Change Type

    | Change Type | Required Tests | Notes |
    |-------------|----------------|-------|
    | API endpoint (new) | Unit, Hurl, Pact | Pact for contracts |
    """
    rows = parse_markdown_table(content, 'Required Tests by Change Type')

    test_map = {}
    for row in rows:
        change_type = row.get('Change Type', '')
        tests = row.get('Required Tests', '')

        if change_type and tests:
            # Parse comma-separated test types
            test_list = [t.strip() for t in tests.split(',')]
            test_map[change_type] = test_list

    return test_map


def parse_test_data(content: str) -> List[Dict[str, str]]:
    """
    Parse Test Data section for fixture mappings.

    Expected format:
    ## Test Data

    | Fixture Path | Use Case | Example Usage |
    |--------------|----------|---------------|
    | fixtures/users/valid-user.json | User creation | loadFixture('...') |
    """
    rows = parse_markdown_table(content, 'Test Data')

    fixtures = []
    for row in rows:
        fixture_path = row.get('Fixture Path', '')
        use_case = row.get('Use Case', '')
        example = row.get('Example Usage', '')

        if fixture_path:
            fixtures.append({
                'path': fixture_path,
                'use_case': use_case,
                'example': example
            })

    return fixtures


def parse_test_modes(content: str) -> List[Dict[str, str]]:
    """
    Parse Test Modes section (for E2E repos).

    Expected format:
    ## Test Modes

    | Mode | Frontend | Backend | Command |
    |------|----------|---------|---------|
    | Local | localhost:5173 | localhost:8080 | npm run test:local |
    """
    rows = parse_markdown_table(content, 'Test Modes')

    modes = []
    for row in rows:
        mode = row.get('Mode', '')
        frontend = row.get('Frontend', '')
        backend = row.get('Backend', '')
        command = row.get('Command', '')

        # Clean up command
        command = re.sub(r'^`|`$', '', command)

        if mode and command:
            modes.append({
                'mode': mode,
                'frontend': frontend,
                'backend': backend,
                'command': command
            })

    return modes


def parse_testing_md(repo_path: str) -> Dict[str, Any]:
    """
    Parse TESTING.md from repository and return structured configuration.

    Falls back to technology detection if sections are missing.
    """
    repo = Path(repo_path)
    testing_md = repo / 'TESTING.md'

    result = {
        'repo_path': str(repo_path),
        'repo_name': repo.name,
        'has_testing_md': False,
        'technology': None,
        'pre_commit_requirements': [],
        'required_tests': {},
        'test_data': [],
        'test_modes': [],
        'fallback_used': False,
        'warnings': []
    }

    # Detect technology
    tech = detect_technology(repo_path)
    result['technology'] = tech

    # Try to parse TESTING.md
    if testing_md.exists():
        result['has_testing_md'] = True

        try:
            content = testing_md.read_text()

            # Parse each section
            pre_commit = parse_pre_commit_requirements(content)
            required_tests = parse_required_tests(content)
            test_data = parse_test_data(content)
            test_modes = parse_test_modes(content)

            if pre_commit:
                result['pre_commit_requirements'] = pre_commit
            else:
                result['warnings'].append('No Pre-Commit Requirements section found')

            if required_tests:
                result['required_tests'] = required_tests

            if test_data:
                result['test_data'] = test_data

            if test_modes:
                result['test_modes'] = test_modes

        except Exception as e:
            result['warnings'].append(f'Error parsing TESTING.md: {str(e)}')
    else:
        result['warnings'].append('TESTING.md not found')

    # Apply fallback if pre_commit_requirements is empty
    if not result['pre_commit_requirements'] and tech:
        result['fallback_used'] = True
        # Deep copy to avoid mutating TECH_DEFAULTS
        import copy
        result['pre_commit_requirements'] = copy.deepcopy(TECH_DEFAULTS[tech]['pre_commit'])
        result['warnings'].append(f'Using {tech} defaults for pre-commit requirements')

        # For TypeScript, resolve the actual typecheck script name from package.json
        if tech == 'typescript':
            result['pre_commit_requirements'] = _resolve_ts_scripts(
                result['pre_commit_requirements'], repo_path
            )

        # Also apply default test types if missing
        if not result['required_tests']:
            result['required_tests'] = TECH_DEFAULTS[tech]['test_types']

    return result


def _resolve_ts_scripts(
    requirements: List[Dict[str, Any]],
    repo_path: str
) -> List[Dict[str, Any]]:
    """Resolve TypeScript npm script names from package.json.

    Checks if the default script names actually exist and swaps in
    the correct name when a known alternative is found.
    """
    package_json = Path(repo_path) / 'package.json'
    if not package_json.exists():
        return requirements

    try:
        with open(package_json) as f:
            pkg = json.load(f)
    except Exception:
        return requirements

    scripts = pkg.get('scripts', {})
    alternatives = TECH_DEFAULTS.get('typescript', {}).get('typecheck_alternatives', [])

    resolved = []
    for req in requirements:
        command = req.get('command', '')

        # Resolve typecheck command
        if 'typecheck' in command or 'type-check' in command:
            # Extract the script name from "npm run <script>"
            npm_match = re.match(r'npm\s+run\s+(\S+)', command)
            if npm_match:
                script_name = npm_match.group(1)
                if script_name not in scripts:
                    # Try alternatives
                    found = False
                    for alt in alternatives:
                        if alt in scripts:
                            req = dict(req)
                            req['command'] = f'npm run {alt}'
                            found = True
                            break
                    if not found:
                        # No typecheck script found at all — skip this step
                        req = dict(req)
                        req['command'] = ''

        resolved.append(req)

    return resolved


def store_config(config: Dict[str, Any]) -> bool:
    """Store parsed config in AgentDB memory."""
    if not AGENTDB_AVAILABLE:
        print("[testing-md-parser] AgentDB not available, skipping memory storage", file=sys.stderr)
        return False

    repo_name = config.get('repo_name', 'unknown')
    namespace = get_namespace()

    # Store as pattern for retrieval
    result = agentdb_request('POST', '/api/v1/pattern/store', {
        'task_type': f'testing-config-{repo_name}',
        'approach': json.dumps(config),
        'success_rate': 1.0,
        'namespace': namespace,
        'metadata': {
            'repo': repo_name,
            'technology': config.get('technology'),
            'has_testing_md': config.get('has_testing_md'),
            'fallback_used': config.get('fallback_used')
        }
    })

    return result is not None


def main():
    """
    Main entry point for hook execution.

    Usage:
        python testing-md-parser.py [repo_path]
        python testing-md-parser.py  # Uses current directory

    Output: JSON configuration to stdout
    """
    # Get repository path
    if len(sys.argv) > 1:
        repo_path = sys.argv[1]
    else:
        repo_path = os.getcwd()

    # Parse TESTING.md
    config = parse_testing_md(repo_path)

    # Store in memory (async, don't block)
    if AGENTDB_AVAILABLE:
        try:
            store_config(config)
        except Exception as e:
            config['warnings'].append(f'Failed to store config: {str(e)}')

    # Output JSON to stdout
    print(json.dumps(config, indent=2))

    return 0


if __name__ == '__main__':
    sys.exit(main())
