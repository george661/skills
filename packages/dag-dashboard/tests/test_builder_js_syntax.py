"""
Test JavaScript syntax for builder files using node --check.
"""
import subprocess
from pathlib import Path


def test_validation_panel_js_syntax():
    """Verify validation-panel.js has valid JavaScript syntax."""
    js_file = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "validation-panel.js"
    result = subprocess.run(
        ["node", "--check", str(js_file)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"validation-panel.js has syntax errors:\n{result.stderr}"


def test_validation_rules_js_syntax():
    """Verify validation-rules.js has valid JavaScript syntax."""
    js_file = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "validation-rules.js"
    result = subprocess.run(
        ["node", "--check", str(js_file)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"validation-rules.js has syntax errors:\n{result.stderr}"


def test_use_builder_validation_js_syntax():
    """Verify use-builder-validation.js has valid JavaScript syntax."""
    js_file = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "use-builder-validation.js"
    result = subprocess.run(
        ["node", "--check", str(js_file)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"use-builder-validation.js has syntax errors:\n{result.stderr}"
