#!/usr/bin/env python3
"""
Tier 5 Validation Loop — PostToolUse:SlashCommand hook

Runs lightweight validation checks after local-model execution commands.
Only fires when:
  1. The active cost-strategy profile has validation_loop.enabled = true
  2. The command's resolved model alias is in validation_loop.trigger_tiers
  3. The command actually produced file changes (git diff --name-only)

Checks performed:
  - TypeScript: tsc --noEmit (if tsconfig.json exists in worktree)
  - ESLint: eslint on changed .ts/.tsx/.js/.jsx files
  - Python: python3 -m py_compile on changed .py files
  - Tests exist: warns if new source files lack corresponding test files
  - JSON validity: validates changed .json files

Output is printed to stderr (visible to user) and returned as JSON
for the hook system. Does NOT block — always returns {"continue": true}.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Import routing config loader
try:
    sys.path.insert(0, os.path.expanduser('~/.claude/hooks'))
    from load_model_routing import load_routing, get_command_alias, get_validation_loop_config
    ROUTING_AVAILABLE = True
except ImportError:
    ROUTING_AVAILABLE = False


def should_validate(tool_input: dict) -> tuple:
    """Check if validation loop should fire for this command.

    Returns (should_run: bool, command: str, reason: str)
    """
    if not ROUTING_AVAILABLE:
        return (False, '', 'routing config not available')

    command_str = tool_input.get('command', '')
    if not command_str.startswith('/'):
        return (False, '', 'not a slash command')

    # Extract command name (e.g. "/implement PROJ-123" → "implement")
    command = command_str.lstrip('/').split()[0].lower()

    config = load_routing()
    vl = get_validation_loop_config(config)

    if not vl.get('enabled', False):
        return (False, command, f'validation loop disabled in profile {config.get("_active_profile", "?")}')

    # Check if this command's model is in trigger_tiers
    alias = get_command_alias(config, command)
    trigger_tiers = vl.get('trigger_tiers', [])

    if alias not in trigger_tiers:
        return (False, command, f'{alias} not in trigger_tiers {trigger_tiers}')

    return (True, command, f'{alias} matched trigger_tiers')


def get_changed_files() -> list:
    """Get files changed in the current git working tree."""
    try:
        # Staged + unstaged changes
        result = subprocess.run(
            ['git', 'diff', '--name-only', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]

        # Also include untracked new files
        result2 = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            capture_output=True, text=True, timeout=5
        )
        files += [f.strip() for f in result2.stdout.strip().split('\n') if f.strip()]

        return list(set(files))
    except Exception:
        return []


def run_check(name: str, cmd: list, timeout: int = 30) -> dict:
    """Run a validation check and return result."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=os.environ.get('PROJECT_ROOT', os.getcwd())
        )
        return {
            'check': name,
            'passed': result.returncode == 0,
            'exit_code': result.returncode,
            'output': (result.stdout + result.stderr)[-500:] if result.returncode != 0 else '',
        }
    except subprocess.TimeoutExpired:
        return {'check': name, 'passed': False, 'exit_code': -1, 'output': f'Timed out after {timeout}s'}
    except FileNotFoundError:
        return {'check': name, 'passed': True, 'exit_code': 0, 'output': 'tool not found, skipped'}


def validate_json_files(files: list) -> dict:
    """Validate JSON syntax for changed .json files."""
    json_files = [f for f in files if f.endswith('.json')]
    if not json_files:
        return {'check': 'json-syntax', 'passed': True, 'exit_code': 0, 'output': 'no json files changed'}

    errors = []
    for jf in json_files:
        try:
            with open(jf, 'r') as fh:
                json.load(fh)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            errors.append(f'{jf}: {e}')

    if errors:
        return {'check': 'json-syntax', 'passed': False, 'exit_code': 1, 'output': '\n'.join(errors)}
    return {'check': 'json-syntax', 'passed': True, 'exit_code': 0, 'output': f'{len(json_files)} files OK'}


def check_test_coverage(files: list) -> dict:
    """Warn if new source files lack corresponding test files."""
    src_extensions = {'.ts', '.tsx', '.js', '.jsx', '.py', '.go'}
    test_patterns = {'test', 'spec', '_test', 'tests'}

    new_src_files = []
    test_files_seen = set()

    for f in files:
        p = Path(f)
        if p.suffix in src_extensions:
            stem_lower = p.stem.lower()
            if any(pat in stem_lower for pat in test_patterns):
                test_files_seen.add(p.stem.replace('.test', '').replace('.spec', '').replace('_test', ''))
            elif '/test' not in f and '/tests' not in f and '/__test' not in f:
                new_src_files.append(f)

    missing_tests = []
    for src in new_src_files:
        stem = Path(src).stem
        if stem not in test_files_seen:
            missing_tests.append(src)

    if missing_tests:
        return {
            'check': 'test-coverage',
            'passed': True,  # Warning only, don't block
            'exit_code': 0,
            'output': f'WARNING: {len(missing_tests)} new files without tests: {", ".join(missing_tests[:5])}'
        }
    return {'check': 'test-coverage', 'passed': True, 'exit_code': 0, 'output': 'OK'}


def run_validation(command: str) -> dict:
    """Run all validation checks on changed files."""
    files = get_changed_files()
    if not files:
        return {'validated': True, 'checks': [], 'message': 'No changed files to validate'}

    checks = []
    project_root = os.environ.get('PROJECT_ROOT', os.getcwd())

    # TypeScript type checking
    ts_files = [f for f in files if f.endswith(('.ts', '.tsx'))]
    if ts_files and Path(project_root, 'tsconfig.json').exists():
        checks.append(run_check('typecheck', ['npx', 'tsc', '--noEmit'], timeout=60))

    # ESLint on changed JS/TS files
    lint_files = [f for f in files if f.endswith(('.ts', '.tsx', '.js', '.jsx'))]
    if lint_files and (Path(project_root, '.eslintrc.json').exists() or
                       Path(project_root, '.eslintrc.js').exists() or
                       Path(project_root, 'eslint.config.js').exists() or
                       Path(project_root, 'eslint.config.mjs').exists()):
        checks.append(run_check('eslint', ['npx', 'eslint', '--no-error-on-unmatched-pattern'] + lint_files[:20], timeout=30))

    # Python compile check
    py_files = [f for f in files if f.endswith('.py')]
    for pf in py_files[:10]:
        checks.append(run_check(f'py-compile:{Path(pf).name}', ['python3', '-m', 'py_compile', pf], timeout=10))

    # JSON syntax
    checks.append(validate_json_files(files))

    # Test coverage warning
    checks.append(check_test_coverage(files))

    passed = all(c['passed'] for c in checks)
    failed = [c for c in checks if not c['passed']]

    return {
        'validated': passed,
        'total_checks': len(checks),
        'passed_checks': len(checks) - len(failed),
        'failed_checks': len(failed),
        'files_checked': len(files),
        'checks': checks,
        'failures': failed,
    }


def main():
    # Read hook input
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except (json.JSONDecodeError, Exception):
        print(json.dumps({"continue": True}))
        return

    tool_input = input_data.get('tool_input', {})

    should_run, command, reason = should_validate(tool_input)

    if not should_run:
        # Silent skip — don't clutter output
        print(json.dumps({"continue": True}))
        return

    print(f'[validation-loop] Running Tier 5 validation for /{command} ({reason})', file=sys.stderr)

    result = run_validation(command)

    if result['validated']:
        print(f'[validation-loop] PASSED ({result["passed_checks"]}/{result["total_checks"]} checks, {result["files_checked"]} files)', file=sys.stderr)
    else:
        print(f'[validation-loop] FAILED ({result["failed_checks"]} failures):', file=sys.stderr)
        for f in result['failures']:
            print(f'  {f["check"]}: {f["output"][:200]}', file=sys.stderr)

    # Return result — the hook system can surface this to the agent
    print(json.dumps({
        "continue": True,
        "validation_result": result
    }))


if __name__ == '__main__':
    main()
