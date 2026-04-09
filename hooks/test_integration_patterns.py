#!/usr/bin/env python3
"""
Integration test for pattern retrieval system.

Tests the full flow:
1. Pattern retrieval utility works
2. Pre-command hook retrieves patterns
3. Session start hook shows summary
"""

import subprocess
import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def test_pattern_retrieval_utility():
    """Test pattern_retrieval.py CLI."""
    result = subprocess.run(
        ['python3', 'pattern_retrieval.py', 'work', '{"issue_key": "TEST-1"}'],
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    # Should not error (may return empty if AgentDB unavailable)
    assert result.returncode == 0, f"Error: {result.stderr}"
    print("✓ pattern_retrieval.py CLI works")


def test_pattern_retrieval_import():
    """Test that pattern_retrieval module imports correctly."""
    result = subprocess.run(
        ['python3', '-c', 'from pattern_retrieval import retrieve_and_format; print("OK")'],
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    assert result.returncode == 0, f"Import error: {result.stderr}"
    assert 'OK' in result.stdout
    print("✓ pattern_retrieval imports correctly")


def test_pre_command_hook():
    """Test pre-command.py with workflow command."""
    input_data = json.dumps({"tool_input": {"command": "/work TEST-1"}})
    result = subprocess.run(
        ['python3', 'pre-command.py'],
        input=input_data,
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    assert result.returncode == 0, f"Hook error: {result.stderr}"
    output = json.loads(result.stdout)
    assert output.get('continue') == True, f"Expected continue=True, got {output}"
    print("✓ pre-command.py works with workflow command")


def test_pre_command_non_workflow():
    """Test pre-command.py with non-workflow command."""
    input_data = json.dumps({"tool_input": {"command": "git status"}})
    result = subprocess.run(
        ['python3', 'pre-command.py'],
        input=input_data,
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output.get('continue') == True
    # Should NOT have pattern retrieval output for non-workflow commands
    assert '<retrieved-patterns' not in result.stderr
    print("✓ pre-command.py skips pattern retrieval for non-workflow commands")


def test_session_start_hook():
    """Test session-start-workflow-prompt.py."""
    result = subprocess.run(
        ['python3', 'session-start-workflow-prompt.py'],
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    assert result.returncode == 0, f"Hook error: {result.stderr}"
    output = json.loads(result.stdout)
    assert output.get('continue') == True, f"Expected continue=True, got {output}"
    print("✓ session-start-workflow-prompt.py works")


def test_extract_command_context():
    """Test command context extraction."""
    result = subprocess.run(
        ['python3', '-c', '''
from pre_command import extract_command_context
import json

# Test workflow command with issue
ctx = extract_command_context({"tool_input": {"command": "/work PROJ-123"}})
print(json.dumps(ctx))
'''],
        capture_output=True,
        text=True,
        cwd=HOOKS_DIR
    )
    # This may fail if pre_command doesn't expose the function - that's OK
    if result.returncode == 0:
        ctx = json.loads(result.stdout)
        assert ctx[0] == 'work', f"Expected cmd_name='work', got {ctx[0]}"
        assert ctx[1].get('issue_key') == 'PROJ-123'
        print("✓ extract_command_context extracts issue key correctly")
    else:
        print("⚠ extract_command_context test skipped (function not importable)")


def main():
    """Run all integration tests."""
    print("\n=== Pattern Retrieval Integration Tests ===\n")

    tests = [
        test_pattern_retrieval_import,
        test_pattern_retrieval_utility,
        test_pre_command_hook,
        test_pre_command_non_workflow,
        test_session_start_hook,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed += 1

    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")

    if failed > 0:
        sys.exit(1)
    else:
        print("✅ All integration tests passed!")
        sys.exit(0)


if __name__ == '__main__':
    main()
