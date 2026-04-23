"""Tests for builder sidebar link markup in static HTML."""
from pathlib import Path


def test_builder_link_present_and_hidden_by_default() -> None:
    """Builder link should exist in sidebar with hidden class."""
    index_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "index.html"
    html = index_path.read_text()
    
    # Check that a builder link exists in the main sidebar
    assert 'data-route="/builder"' in html or 'href="#/builder"' in html, \
        "Builder link should exist in sidebar"
    
    # Check that the builder link has the hidden class by default
    # The link markup should contain class="...hidden..." or class="hidden..."
    lines = html.split("\n")
    builder_link_found = False
    for i, line in enumerate(lines):
        if ('data-route="/builder"' in line or 'href="#/builder"' in line) and '<aside' in '\n'.join(lines[:i]):
            # Found builder link in sidebar context
            # Check within a few lines for the class attribute
            context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
            assert 'hidden' in context.lower(), \
                f"Builder link should have 'hidden' class by default, found: {context}"
            builder_link_found = True
            break
    
    assert builder_link_found, "Could not find builder link in sidebar context"


def test_builder_mobile_link_present_and_hidden_by_default() -> None:
    """Builder link should exist in mobile nav with hidden class."""
    index_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "index.html"
    html = index_path.read_text()
    
    # Check for mobile nav builder link
    lines = html.split("\n")
    mobile_builder_found = False
    for i, line in enumerate(lines):
        if ('data-route="/builder"' in line or 'href="#/builder"' in line):
            # Check if this is within mobile-nav context
            context_before = '\n'.join(lines[max(0, i-20):i])
            if 'mobile-nav' in context_before or 'id="mobile-nav"' in context_before:
                # Check for hidden class
                context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
                assert 'hidden' in context.lower(), \
                    f"Mobile builder link should have 'hidden' class by default"
                mobile_builder_found = True
                break
    
    assert mobile_builder_found, "Could not find builder link in mobile nav"


def test_builder_config_script_before_app() -> None:
    """builder-config.js script should appear before app.js in HTML."""
    index_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "index.html"
    html = index_path.read_text()
    
    # Find positions of both scripts
    builder_config_pos = html.find('/builder-config.js')
    app_js_pos = html.find('/js/app.js')
    
    assert builder_config_pos != -1, "builder-config.js script tag should be present"
    assert app_js_pos != -1, "app.js script tag should be present"
    assert builder_config_pos < app_js_pos, \
        "builder-config.js must load before app.js"
