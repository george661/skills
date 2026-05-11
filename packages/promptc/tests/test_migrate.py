"""Tests for promptc migrate command."""

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from promptc import migrate
from promptc.cli import main

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "migrate"


def test_migrate_frontmatter_description():
    """Test YAML description field converts to {% meta %} tag."""
    source = """---
description: Test command
---

Content here.
"""
    result = migrate.migrate_text(source)
    assert '{% meta description="Test command"' in result
    assert 'doc_type="command"' in result


def test_migrate_frontmatter_arguments():
    """Test YAML arguments convert to {% input %} tags."""
    source = """---
description: Test
arguments:
  - name: foo
    description: Foo arg
    required: true
  - name: bar
    description: Bar arg
---

Content.
"""
    result = migrate.migrate_text(source)
    assert '{% input name="foo" type="string" required="true" description="Foo arg" /%}' in result
    assert '{% input name="bar" type="string" description="Bar arg" /%}' in result
    # required="false" should be omitted (default)
    assert 'required="false"' not in result


def test_migrate_model_tier_comment():
    """Test MODEL_TIER comment merges into meta tag."""
    source = """<!-- MODEL_TIER: local -->
---
description: Test
---

Content.
"""
    result = migrate.migrate_text(source)
    assert 'tier="local"' in result
    assert '<!-- MODEL_TIER' not in result  # Should be stripped


def test_migrate_arguments_substitution():
    """Test $ARGUMENTS.foo converts to {% $inputs.foo %}."""
    source = """---
description: Test
---

Use $ARGUMENTS.issue here and $ARGUMENTS.other there.
"""
    result = migrate.migrate_text(source)
    assert '{% $inputs.issue %}' in result
    assert '{% $inputs.other %}' in result
    assert '$ARGUMENTS.' not in result


def test_migrate_phase_heading():
    """Test ## Phase N: Name heading wraps content in {% phase %} block."""
    source = """---
description: Test
---

## Phase 1: Setup

Setup content here.
"""
    result = migrate.migrate_text(source)
    assert '{% phase name="Setup" %}' in result
    assert '{% /phase %}' in result
    assert 'Setup content here.' in result


def test_migrate_multiple_phases():
    """Test multiple phase headings produce separate phase blocks."""
    source = """---
description: Test
---

## Phase 1: First

First content.

## Phase 2: Second

Second content.
"""
    result = migrate.migrate_text(source)
    assert result.count('{% phase') == 2
    assert '{% phase name="First" %}' in result
    assert '{% phase name="Second" %}' in result


def test_migrate_content_before_first_phase():
    """Test content before first phase is preserved above phase blocks."""
    source = """---
description: Test
---

Preamble content.

## Phase 1: Work

Phase content.
"""
    result = migrate.migrate_text(source)
    lines = result.split('\n')
    preamble_idx = next(i for i, line in enumerate(lines) if 'Preamble content' in line)
    phase_idx = next(i for i, line in enumerate(lines) if '{% phase name="Work"' in line)
    assert preamble_idx < phase_idx


def test_migrate_unconvertible_section_flagged():
    """Test unconvertible sections get TODO comment."""
    source = """---
description: Test
unknown_key: value
---

Content.
"""
    result = migrate.migrate_text(source)
    assert '<!-- TODO(promptc-migrate):' in result


def test_migrate_original_file_never_modified():
    """Test migrate_file never modifies the original file."""
    fixture_path = FIXTURES_DIR / "simple.md"
    original_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()

    migrate.migrate_file(str(fixture_path))

    after_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert original_hash == after_hash


def test_migrate_no_disk_writes():
    """Test migrate module never opens files in write mode."""
    write_calls = []

    original_open = open
    def tracked_open(path, mode='r', *args, **kwargs):
        if 'w' in mode or 'a' in mode:
            write_calls.append((path, mode))
        return original_open(path, mode, *args, **kwargs)

    fixture_path = FIXTURES_DIR / "simple.md"
    with patch('builtins.open', side_effect=tracked_open):
        migrate.migrate_file(str(fixture_path))

    # Filter out pytest's own file writes
    migrate_writes = [call for call in write_calls if 'migrate' in str(call[0])]
    assert len(migrate_writes) == 0, f"Unexpected write calls: {migrate_writes}"


def test_cli_migrate_exit_zero_on_warnings(capsys, tmp_path):
    """Test CLI exits 0 even with warnings about unconvertible content."""
    test_file = tmp_path / "test.md"
    test_file.write_text("""---
description: Test
unknown_key: value
---
Content.
""")

    with pytest.raises(SystemExit) as exc:
        sys.exit(main(["migrate", str(test_file)]))

    assert exc.value.code == 0
    captured = capsys.readouterr()
    # Should still produce output
    assert '{% meta' in captured.out


def test_cli_migrate_exit_nonzero_on_parse_failure(capsys, tmp_path):
    """Test CLI exits 1 on malformed YAML frontmatter."""
    test_file = tmp_path / "malformed.md"
    test_file.write_text("""---
description: "unclosed quote
---
Content.
""")

    with pytest.raises(SystemExit) as exc:
        sys.exit(main(["migrate", str(test_file)]))

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert 'error' in captured.err.lower() or 'failed' in captured.err.lower()


def test_cli_migrate_file_not_found(capsys):
    """Test CLI exits 1 when file doesn't exist."""
    with pytest.raises(SystemExit) as exc:
        sys.exit(main(["migrate", "/nonexistent/file.md"]))

    assert exc.value.code == 1


def test_migrate_validate_deploy_status_smoke():
    """Smoke test: migrate a realistic fixture and verify it parses."""
    from promptc.parser import Parser

    source = """<!-- MODEL_TIER: sonnet -->
---
description: Validate deployment status
arguments:
  - name: issue
    description: Issue key
    required: true
---

Check if $ARGUMENTS.issue deployment succeeded.

## Phase 1: Fetch Status

Get the status for $ARGUMENTS.issue.

## Phase 2: Validate

Check the results.
"""
    result = migrate.migrate_text(source)

    # Should produce valid promptc that parser can load
    parser = Parser()
    try:
        parser.parse(result)
        # If we get here, it's valid promptc
        assert True
    except Exception as e:
        pytest.fail(f"Migrated output failed to parse: {e}\n\nOutput:\n{result}")
