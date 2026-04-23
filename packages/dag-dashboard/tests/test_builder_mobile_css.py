"""Static tests for mobile/touch support in the DAG builder (GW-5253).

Covers three deliverables from PRP-PLAT-008 Tier E Task 15:

1. React Flow canvas has pinch/pan gesture props compiled into the bundle.
2. 768px breakpoint makes Inspector/NodeLibrary/toolbars readable.
3. 320px breakpoint keeps critical paths (view/validate/publish) usable.

These are CI-enforced static tests — the Playwright e2e in ``e2e/tests/``
cover behaviour, these cover that the responsive CSS and gesture props
actually ship in the committed artifacts.
"""
from pathlib import Path


DASHBOARD_PKG = Path(__file__).parent.parent / "src" / "dag_dashboard"
BUILDER_BUNDLE = DASHBOARD_PKG / "static" / "js" / "builder" / "builder.js"
NODE_LIBRARY_CSS = DASHBOARD_PKG / "static" / "js" / "builder" / "node-library.css"
MAIN_CSS = DASHBOARD_PKG / "static" / "css" / "styles.css"


def test_builder_bundle_enables_pinch_zoom() -> None:
    """React Flow bundle must include ``zoomOnPinch`` so touch pinch works."""
    content = BUILDER_BUNDLE.read_text()
    assert "zoomOnPinch" in content, (
        "Builder bundle is missing zoomOnPinch prop — pinch-zoom will not work on touch devices. "
        "Rebuild via `cd packages/dag-dashboard/builder && npm run build`."
    )


def test_builder_bundle_enables_pan_on_drag() -> None:
    """React Flow bundle must include ``panOnDrag`` so one-finger touch panning works."""
    content = BUILDER_BUNDLE.read_text()
    assert "panOnDrag" in content, (
        "Builder bundle is missing panOnDrag prop — touch pan will not work."
    )


def test_node_library_css_has_mobile_breakpoint() -> None:
    """NodeLibrary must collapse into a full-width drawer below 768px."""
    content = NODE_LIBRARY_CSS.read_text()
    assert "@media (max-width: 767px)" in content, (
        "node-library.css is missing the 767px breakpoint required for 768px iPad readability."
    )
    # Drawer state class is toggled by node-library.js when mobile.
    assert "node-library--mobile" in content or "node-library-mobile" in content, (
        "node-library.css must define a mobile drawer state class (node-library--mobile*)."
    )


def test_main_css_has_builder_mobile_rules() -> None:
    """Main styles.css must ship builder-specific mobile rules appended at EOF."""
    content = MAIN_CSS.read_text()
    # Canvas must fill viewport on mobile.
    assert ".workflow-canvas" in content, (
        "styles.css is missing .workflow-canvas selector — canvas won't be sized on mobile."
    )
    # 16px inputs prevent iOS auto-zoom.
    assert "font-size: 16px" in content
    # 44px touch targets on builder action buttons.
    assert "min-height: 44px" in content or "min-height:44px" in content


def test_main_css_has_touch_action_manipulation() -> None:
    """Builder toolbar buttons must use ``touch-action: manipulation`` to avoid the iOS 300ms tap delay."""
    content = MAIN_CSS.read_text()
    assert "touch-action: manipulation" in content, (
        "styles.css must set `touch-action: manipulation` on builder toolbar buttons to "
        "eliminate the iOS 300ms click delay."
    )


def test_builder_bundle_has_media_query_hook() -> None:
    """Builder bundle must embed the max-width:767px media query string (from useMediaQuery)."""
    content = BUILDER_BUNDLE.read_text()
    assert "max-width: 767px" in content or "max-width:767px" in content, (
        "Builder bundle is missing the (max-width: 767px) media query — "
        "the responsive layout switch never fires."
    )
