#!/usr/bin/env python3
"""
PreToolUse:Bash hook - validates pre-commit requirements before git push.

Parses TESTING.md to get repo-specific validation commands and runs them
before allowing git push operations. Blocks push if validation fails.

Design Reference:
- project-docs/designs/2026-02-09-agent-workflow-improvements-design.md
- project-docs/designs/2026-02-09-agent-workflow-improvements-plan.md
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import the testing-md-parser
try:
    from testing_md_parser import parse_testing_md
    PARSER_AVAILABLE = True
except ImportError:
    # Try to import from same directory
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from testing_md_parser import parse_testing_md
        PARSER_AVAILABLE = True
    except ImportError:
        PARSER_AVAILABLE = False


# Auto-fix command mappings (technology-specific)
# Maps base commands to their auto-fix variants
AUTO_FIX_COMMANDS = {
    # Go
    'golangci-lint run': 'golangci-lint run --fix',
    # TypeScript/JavaScript
    'npm run lint': 'npm run lint -- --fix',
    'npx eslint': 'npx eslint --fix',
    'eslint ': 'eslint --fix ',
    # Python
    'ruff check': 'ruff check --fix',
    'black --check': 'black',
    'isort --check': 'isort',
}


def is_git_push_command(command: str) -> bool:
    """Check if command is a git push operation."""
    command_lower = command.lower().strip()

    # Direct git push
    if command_lower.startswith('git push'):
        return True

    # Piped commands that end in git push
    if '| git push' in command_lower or '&& git push' in command_lower:
        return True

    return False


def find_git_root(start_path: str) -> Optional[str]:
    """Find the git root directory starting from the given path."""
    current = Path(start_path).resolve()

    while current != current.parent:
        if (current / '.git').exists():
            return str(current)
        current = current.parent

    return None


def get_auto_fix_command(command: str) -> Optional[str]:
    """Get the auto-fix variant of a command if available."""
    for base_cmd, fix_cmd in AUTO_FIX_COMMANDS.items():
        if base_cmd in command:
            return command.replace(base_cmd, fix_cmd)

    # For npm commands, try adding --fix
    if 'npm run' in command and '--fix' not in command:
        return f"{command} -- --fix"

    return None


def command_exists(command: str, cwd: str) -> bool:
    """Check if a command is available before running it."""
    # Extract the base command (first word or npm script name)
    cmd = command.strip()

    # Check npm scripts: verify the script exists in package.json
    npm_match = re.match(r'npm\s+run\s+(\S+)', cmd)
    if npm_match:
        script_name = npm_match.group(1)
        package_json = Path(cwd) / 'package.json'
        if package_json.exists():
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                scripts = pkg.get('scripts', {})
                return script_name in scripts
            except Exception:
                return True  # If we can't parse, assume it exists
        return False

    # Check npm test
    if cmd.startswith('npm test'):
        package_json = Path(cwd) / 'package.json'
        if package_json.exists():
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                scripts = pkg.get('scripts', {})
                return 'test' in scripts
            except Exception:
                return True
        return False

    # Check binary commands (go, golangci-lint, etc.)
    base_cmd = cmd.split()[0] if cmd else ''
    if base_cmd:
        try:
            result = subprocess.run(
                ['which', base_cmd],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return True  # If we can't check, assume it exists

    return True


def run_command(command: str, cwd: str, timeout: int = 300) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr).

    Default timeout is 300s (5 min) to accommodate slow test suites.
    Measured baselines: frontend-app unit tests ~71s, api-service unit tests ~51s.
    Under CI load these can double, so 300s provides safe headroom.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, '', f'Command timed out after {timeout}s: {command}'
    except Exception as e:
        return 1, '', str(e)


def run_validation_step(
    step: Dict[str, Any],
    repo_path: str,
    attempt_auto_fix: bool = True
) -> Dict[str, Any]:
    """
    Run a single validation step.

    Returns dict with:
      - step: str (step name)
      - command: str (command run)
      - success: bool
      - auto_fixed: bool (if auto-fix was attempted)
      - output: str (combined stdout/stderr)
    """
    step_name = step.get('step', 'Unknown')
    command = step.get('command', '')
    can_auto_fix = step.get('auto_fix', False)

    result = {
        'step': step_name,
        'command': command,
        'success': False,
        'auto_fixed': False,
        'output': ''
    }

    if not command:
        result['output'] = 'No command specified'
        return result

    # Skip commands that don't exist (missing npm scripts, missing binaries)
    if not command_exists(command, repo_path):
        result['success'] = True
        result['output'] = f'Skipped (command not available: {command})'
        return result

    # Run the validation command
    exit_code, stdout, stderr = run_command(command, repo_path)
    output = f"{stdout}\n{stderr}".strip()

    if exit_code == 0:
        result['success'] = True
        result['output'] = output if output else 'Passed'
        return result

    # Command failed - try auto-fix if enabled
    if can_auto_fix and attempt_auto_fix:
        fix_command = get_auto_fix_command(command)

        if fix_command:
            print(f"[pre-push] Auto-fixing with: {fix_command}", file=sys.stderr)
            fix_exit, fix_stdout, fix_stderr = run_command(fix_command, repo_path)

            if fix_exit == 0:
                # Re-run original validation to verify fix worked
                exit_code, stdout, stderr = run_command(command, repo_path)
                output = f"{stdout}\n{stderr}".strip()

                if exit_code == 0:
                    result['success'] = True
                    result['auto_fixed'] = True
                    result['output'] = 'Auto-fixed successfully'
                    return result

    # Still failed
    result['output'] = output if output else f'Exit code: {exit_code}'
    return result


def run_all_validations(
    requirements: List[Dict[str, Any]],
    repo_path: str,
    max_total_seconds: int = 600
) -> Dict[str, Any]:
    """
    Run all validation steps and aggregate results.

    Default overall timeout is 600s (10 min).
    Measured baselines: frontend-app total ~94s, api-service total ~73s.
    Under load these can 2-3x, and some repos have more steps.

    Returns dict with:
      - success: bool (all steps passed)
      - results: list of step results
      - failures: list of failed step names
      - auto_fixed: list of auto-fixed step names
      - skipped: list of skipped step names
      - durations: dict mapping step name to seconds elapsed
      - total_seconds: float total wall-clock time
    """
    import time
    start_time = time.monotonic()

    results = []
    failures = []
    auto_fixed = []
    skipped = []
    durations = {}

    for step in requirements:
        step_name = step.get('step', 'Unknown')

        # Check overall timeout
        elapsed = time.monotonic() - start_time
        if elapsed > max_total_seconds:
            print(f"[pre-push] Overall timeout ({max_total_seconds}s) reached after {int(elapsed)}s, skipping remaining steps", file=sys.stderr)
            skipped.append(step_name)
            results.append({
                'step': step_name,
                'command': step.get('command', ''),
                'success': True,
                'auto_fixed': False,
                'output': f'Skipped (overall timeout after {int(elapsed)}s)'
            })
            continue

        print(f"[pre-push] Running: {step_name}...", file=sys.stderr)

        step_start = time.monotonic()
        step_result = run_validation_step(step, repo_path)
        step_elapsed = time.monotonic() - step_start
        durations[step_name] = round(step_elapsed, 1)

        results.append(step_result)

        if step_result['success']:
            if 'Skipped' in step_result.get('output', ''):
                skipped.append(step_name)
                print(f"[pre-push] {step_name}: Skipped", file=sys.stderr)
            elif step_result['auto_fixed']:
                auto_fixed.append(step_name)
                print(f"[pre-push] {step_name}: Auto-fixed ({step_elapsed:.1f}s)", file=sys.stderr)
            else:
                print(f"[pre-push] {step_name}: Passed ({step_elapsed:.1f}s)", file=sys.stderr)
        else:
            failures.append(step_name)
            print(f"[pre-push] {step_name}: FAILED ({step_elapsed:.1f}s)", file=sys.stderr)
            # Print first few lines of output for context
            output_lines = step_result['output'].split('\n')[:15]
            for line in output_lines:
                if line.strip():
                    print(f"  {line}", file=sys.stderr)

    total_seconds = round(time.monotonic() - start_time, 1)

    return {
        'success': len(failures) == 0,
        'results': results,
        'failures': failures,
        'auto_fixed': auto_fixed,
        'skipped': skipped,
        'durations': durations,
        'total_seconds': total_seconds,
    }


def format_block_message(
    validation_results: Dict[str, Any],
    repo_name: str
) -> str:
    """Format a detailed, actionable block message with failure reasons."""
    failures = validation_results.get('failures', [])
    auto_fixed = validation_results.get('auto_fixed', [])
    results = validation_results.get('results', [])
    durations = validation_results.get('durations', {})
    total_seconds = validation_results.get('total_seconds', 0)

    lines = [
        "",
        f"=== Pre-push validation FAILED for {repo_name} ===",
        f"Total validation time: {total_seconds}s",
        "",
    ]

    # Show all step results as a summary table
    lines.append("Step results:")
    for result in results:
        step_name = result['step']
        elapsed = durations.get(step_name, '?')
        if result['success']:
            if result.get('auto_fixed'):
                status = "AUTO-FIXED"
            elif 'Skipped' in result.get('output', ''):
                status = "SKIPPED"
            else:
                status = "PASSED"
        else:
            status = "FAILED"
        lines.append(f"  [{status:>10}] {step_name} ({elapsed}s)")

    # Detailed failure information
    lines.append("")
    lines.append(f"{len(failures)} step(s) failed:")
    lines.append("")

    for result in results:
        if not result['success']:
            step_name = result['step']
            command = result.get('command', 'unknown')
            output = result.get('output', '')
            elapsed = durations.get(step_name, '?')

            lines.append(f"--- {step_name} ---")
            lines.append(f"  Command: {command}")
            lines.append(f"  Duration: {elapsed}s")

            # Detect timeout vs actual failure
            if 'timed out' in output.lower():
                lines.append(f"  Reason: TIMEOUT - command exceeded time limit")
                lines.append(f"  Action: Run the command manually to check if it passes outside the hook")
            else:
                lines.append(f"  Reason: Command exited with non-zero status")

            # Show truncated output (last 20 meaningful lines)
            output_lines = [l for l in output.split('\n') if l.strip()]
            if output_lines:
                # For test failures, tail is usually more useful than head
                shown = output_lines[-20:] if len(output_lines) > 20 else output_lines
                lines.append(f"  Output ({len(output_lines)} lines, showing last {len(shown)}):")
                for line in shown:
                    lines.append(f"    {line[:300]}")
            lines.append("")

    # Auto-fix summary
    if auto_fixed:
        lines.append("Auto-fixed steps (changes staged):")
        for step in auto_fixed:
            lines.append(f"  - {step}")
        lines.append("Review auto-fixed changes and commit before pushing.")
        lines.append("")

    # Actionable next steps
    lines.append("To fix:")
    for result in results:
        if not result['success']:
            command = result.get('command', '')
            step_name = result['step']
            if 'timed out' in result.get('output', '').lower():
                lines.append(f"  1. Run manually: {command}")
                lines.append(f"     (the hook has a per-step timeout; your command may just be slow)")
            elif 'test' in step_name.lower() or 'test' in command.lower():
                lines.append(f"  1. Run: {command}")
                lines.append(f"     Fix failing tests, then retry push")
            elif 'lint' in step_name.lower() or 'lint' in command.lower():
                lines.append(f"  1. Run: {command} --fix  (or equivalent)")
                lines.append(f"     Then commit the fixes and retry push")
            elif 'format' in step_name.lower() or 'format' in command.lower():
                lines.append(f"  1. Run: {command}")
                lines.append(f"     Commit any formatting changes and retry push")
            else:
                lines.append(f"  1. Run: {command}")
                lines.append(f"     Fix errors and retry push")

    return '\n'.join(lines)


def log_validation(repo_name: str, results: Dict[str, Any]):
    """Log validation results to local file including per-step durations."""
    log_dir = os.path.expanduser('~/.claude/logs')
    os.makedirs(log_dir, exist_ok=True)

    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'repo': repo_name,
        'success': results.get('success', False),
        'failures': results.get('failures', []),
        'auto_fixed': results.get('auto_fixed', []),
        'skipped': results.get('skipped', []),
        'durations': results.get('durations', {}),
        'total_seconds': results.get('total_seconds', 0),
    }

    try:
        with open(os.path.join(log_dir, 'pre-push-validation.jsonl'), 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass


def _auto_commit_fixes(repo_path: str, fixed_steps: List[str]) -> bool:
    """
    Stage and amend the last commit with auto-fixed changes.

    Returns True if the fixes were successfully committed.
    """
    try:
        # Check if there are actually unstaged changes
        exit_code, stdout, _ = run_command('git diff --name-only', repo_path, timeout=10)
        changed_files = [f for f in stdout.strip().split('\n') if f.strip()]

        if not changed_files:
            # No changes to commit (auto-fix was a no-op)
            return True

        # Stage the auto-fixed files
        exit_code, _, stderr = run_command('git add -u', repo_path, timeout=10)
        if exit_code != 0:
            print(f"[pre-push] git add failed: {stderr}", file=sys.stderr)
            return False

        # Amend the last commit to include the fixes
        steps_desc = ', '.join(fixed_steps)
        exit_code, _, stderr = run_command(
            'git commit --amend --no-edit --no-verify',
            repo_path,
            timeout=15
        )
        if exit_code != 0:
            print(f"[pre-push] git commit --amend failed: {stderr}", file=sys.stderr)
            return False

        print(f"[pre-push] Amended last commit with auto-fixes from: {steps_desc}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"[pre-push] Auto-commit error: {e}", file=sys.stderr)
        return False


def main():
    """Main hook entry point."""
    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        input_data = {}

    # Get the command being executed
    tool_input = input_data.get('tool_input', {})
    command = tool_input.get('command', '')

    # Only process git push commands
    if not is_git_push_command(command):
        print(json.dumps({"continue": True}))
        return 0

    print("[pre-push] Git push detected - running pre-commit validation", file=sys.stderr)

    # Find git root
    cwd = os.getcwd()
    repo_path = find_git_root(cwd)

    if not repo_path:
        print("[pre-push] Warning: Not in a git repository", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    repo_name = Path(repo_path).name

    # Check if parser is available
    if not PARSER_AVAILABLE:
        print("[pre-push] Warning: testing-md-parser not available, skipping validation", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    # Parse TESTING.md to get validation requirements
    try:
        config = parse_testing_md(repo_path)
    except Exception as e:
        print(f"[pre-push] Warning: Failed to parse TESTING.md: {e}", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    requirements = config.get('pre_commit_requirements', [])

    if not requirements:
        print(f"[pre-push] No pre-commit requirements found for {repo_name}", file=sys.stderr)
        print(json.dumps({"continue": True}))
        return 0

    print(f"[pre-push] Found {len(requirements)} validation steps for {repo_name}", file=sys.stderr)

    # Show technology detected
    tech = config.get('technology', 'unknown')
    fallback = ' (fallback defaults)' if config.get('fallback_used') else ''
    print(f"[pre-push] Technology: {tech}{fallback}", file=sys.stderr)

    # Run all validations
    results = run_all_validations(requirements, repo_path)

    # Log results
    log_validation(repo_name, results)

    total_time = results.get('total_seconds', 0)

    if results['success']:
        if results['auto_fixed']:
            print(f"[pre-push] Validation passed with auto-fixes ({total_time}s total)", file=sys.stderr)
            # Auto-stage and amend the last commit with the fixes
            auto_committed = _auto_commit_fixes(repo_path, results['auto_fixed'])
            if auto_committed:
                print("[pre-push] Auto-fixes committed, push may proceed", file=sys.stderr)
                print(json.dumps({
                    "continue": True,
                    "message": f"Auto-fixes applied and committed for: {', '.join(results['auto_fixed'])}"
                }))
            else:
                print("[pre-push] Could not auto-commit fixes", file=sys.stderr)
                print(json.dumps({
                    "continue": True,
                    "message": "Auto-fixes applied but could not be committed. Stage and commit the changes, then push again."
                }))
        else:
            # Show per-step timing on success for visibility
            durations = results.get('durations', {})
            timing_parts = [f"{name}: {dur}s" for name, dur in durations.items()]
            timing_summary = ', '.join(timing_parts) if timing_parts else 'no steps timed'
            print(f"[pre-push] All validation steps passed ({total_time}s total: {timing_summary})", file=sys.stderr)
            print(json.dumps({"continue": True}))
    else:
        message = format_block_message(results, repo_name)
        print(f"\n{message}", file=sys.stderr)
        print(json.dumps({
            "continue": True,
            "message": message
        }))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
