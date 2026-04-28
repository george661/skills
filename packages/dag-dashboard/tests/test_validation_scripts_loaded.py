"""
test_validation_scripts_loaded.py

Validates that app.js loads the builder bundle AND the three sidecar validation
scripts on the /builder route.

Ordering requirement: the validation scripts are classical (ES5) React components
that reference ``window.React``. The builder bundle ships React and exposes it on
the window, so the sidecars must load AFTER the bundle. Verifying app.js
references them in the right order.
"""

import re
from pathlib import Path


def test_builder_and_validation_scripts_loaded_on_builder_route():
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    assert app_js_path.exists(), f"app.js not found at {app_js_path}"

    content = app_js_path.read_text()

    expected_scripts = [
        "builder.js",
        "validation-rules.js",
        "use-builder-validation.js",
        "validation-panel.js",
    ]

    positions = {}
    for script in expected_scripts:
        match = re.search(rf'["\'].*?/js/builder/{re.escape(script)}["\']', content)
        assert match, f"app.js should reference /js/builder/{script}"
        positions[script] = match.start()

    builder_route_match = re.search(r"router\.register\(['\"]\/builder['\"]", content)
    assert builder_route_match, "app.js should contain a /builder route handler"

    assert "createElement" in content, "app.js should contain script loading code"

    # The bundle ships React; the sidecar scripts reference window.React.
    # They must be listed AFTER the bundle so they run once React is available.
    for sidecar in ("validation-rules.js", "use-builder-validation.js", "validation-panel.js"):
        assert positions["builder.js"] < positions[sidecar], (
            f"builder.js must be loaded before {sidecar} so window.React is available"
        )
