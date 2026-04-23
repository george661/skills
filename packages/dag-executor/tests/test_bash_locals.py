"""Tests for bash_locals.py - bash script variable extraction."""

from dag_executor.bash_locals import extract_bash_locals


def test_simple_assignment():
    """Simple assignment: foo=bar extracts foo."""
    script = "foo=bar"
    result = extract_bash_locals(script)
    assert "foo" in result


def test_multiple_assignments():
    """Multiple assignments extracts all."""
    script = """
    foo=bar
    baz=qux
    ANOTHER_VAR=value
    """
    result = extract_bash_locals(script)
    assert result == {"foo", "baz", "ANOTHER_VAR"}


def test_for_loop():
    """For loop: for x in ... extracts x."""
    script = "for item in *.txt; do echo $item; done"
    result = extract_bash_locals(script)
    assert "item" in result


def test_while_read():
    """While read: while read line extracts line."""
    script = "while read line; do echo $line; done"
    result = extract_bash_locals(script)
    assert "line" in result


def test_read_builtin():
    """Read builtin: read name extracts name."""
    script = "read user_input"
    result = extract_bash_locals(script)
    assert "user_input" in result


def test_read_with_flag():
    """Read with -r flag: read -r var1 var2 extracts both."""
    script = "read -r var1 var2"
    result = extract_bash_locals(script)
    assert "var1" in result
    assert "var2" in result


def test_multiple_locals():
    """Script with 3+ declarations returns all."""
    script = """
    bug_key="GW-123"
    transitions=$(curl ...)
    for t in $transitions; do
        echo $t
    done
    read answer
    """
    result = extract_bash_locals(script)
    assert "bug_key" in result
    assert "transitions" in result
    assert "t" in result
    assert "answer" in result


def test_no_locals():
    """Script with only references, no declarations returns empty set."""
    script = """
    echo $UPSTREAM_VAR
    curl $API_URL
    """
    result = extract_bash_locals(script)
    assert len(result) == 0


def test_assignment_after_command():
    """Assignment on its own line is captured."""
    script = """
    echo "Starting..."
    result=$(some_command)
    echo $result
    """
    result = extract_bash_locals(script)
    assert "result" in result
