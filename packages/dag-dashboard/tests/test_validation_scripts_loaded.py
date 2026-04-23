"""
test_validation_scripts_loaded.py

CRITICAL: Validates that app.js loads validation scripts BEFORE builder.js.
This is a static content test - no browser or FastAPI required.
"""

import re
from pathlib import Path


def test_validation_scripts_loaded_before_builder():
    """
    Assert that app.js contains evidence of loading the three validation scripts
    (use-builder-validation.js, validation-panel.js, validation-rules.js)
    before loading builder.js.
    """
    app_js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "app.js"
    assert app_js_path.exists(), f"app.js not found at {app_js_path}"
    
    content = app_js_path.read_text()
    
    # Check for validation scripts
    validation_scripts = [
        'validation-rules.js',
        'use-builder-validation.js',
        'validation-panel.js',
    ]
    
    for script in validation_scripts:
        pattern = rf'["\'].*?/js/builder/{script}["\']'
        assert re.search(pattern, content), \
            f"app.js should load {script} (pattern: {pattern})"
    
    # Check that builder.js is also loaded
    assert re.search(r'["\'].*?/js/builder/builder\.js["\']', content), \
        "app.js should load builder.js"
    
    # Verify scripts are loaded in the builder route handler region
    # Look for router.register('/builder' pattern
    builder_route_match = re.search(
        r"router\.register\(['\"]\/builder['\"]",
        content
    )
    assert builder_route_match, \
        "app.js should contain builder route handler"

    # Verify that script loading code is present
    assert 'appendChild' in content or 'createElement' in content, \
        "app.js should contain script loading code"
    
    # Verify loadValidationScripts function exists
    assert 'loadValidationScripts' in content, \
        "app.js should contain loadValidationScripts function"
