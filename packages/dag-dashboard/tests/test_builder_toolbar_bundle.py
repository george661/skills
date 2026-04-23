"""
test_builder_toolbar_bundle.py

Validates that builder.js contains BuilderToolbar and stays under 450 kB minified.
"""

import subprocess
import shutil
from pathlib import Path
import pytest


def test_bundle_contains_toolbar():
    """Assert builder.js contains toolbar-specific strings."""
    builder_js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "builder.js"

    if not builder_js_path.exists():
        pytest.skip("builder.js not built yet - run npm run build first")

    content = builder_js_path.read_text()

    # Check for toolbar-specific strings that survive minification
    assert 'unsaved-indicator' in content, "builder.js should contain unsaved-indicator"
    assert 'YAML View' in content or 'yaml view' in content.lower(), "builder.js should contain YAML View toggle"
    assert 'Validate' in content, "builder.js should contain Validate button"


def test_bundle_size_within_budget():
    """Assert builder.js is under 450 kB minified (hard ceiling)."""
    if not shutil.which('node'):
        pytest.skip("Node.js not found - skipping bundle size check")
    
    builder_js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "builder.js"
    
    if not builder_js_path.exists():
        pytest.skip("builder.js not built yet - run npm run build first")
    
    size_bytes = builder_js_path.stat().st_size
    size_kb = size_bytes / 1024
    
    # Hard ceiling: 450 kB
    max_size_kb = 450
    
    assert size_kb <= max_size_kb, \
        f"builder.js is {size_kb:.1f} kB, exceeds hard ceiling of {max_size_kb} kB"
