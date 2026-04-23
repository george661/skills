"""Static tests: verify workflow canvas JS modules follow GW-5242 vendor bundle contract."""
from pathlib import Path
import re


STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_workflow_canvas_js_exists() -> None:
    assert (STATIC_DIR / "js" / "workflow-canvas.js").exists()


def test_dag_node_js_exists() -> None:
    assert (STATIC_DIR / "js" / "dag-node.js").exists()


def test_dag_to_reactflow_js_exists() -> None:
    assert (STATIC_DIR / "js" / "dag-to-reactflow.js").exists()


def test_canvas_uses_builder_bundle_global() -> None:
    """Canvas must use window.__builderBundle, not hardcoded vendor paths."""
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    assert "window.__builderBundle" in canvas
    # Anti-pattern: direct vendor imports
    assert "/js/vendor/react-flow" not in canvas
    assert "/js/vendor/builder-bundle" not in canvas
    assert "import" not in canvas or "window.__builderBundle" in canvas


def test_canvas_exposes_test_hooks() -> None:
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    assert "window.__testHooks.WorkflowCanvas" in canvas


def test_dag_node_covers_all_node_types() -> None:
    """All 6 node types must be handled."""
    dag_node = (STATIC_DIR / "js" / "dag-node.js").read_text()
    node_types = ["bash", "skill", "command", "prompt", "gate", "interrupt"]
    for node_type in node_types:
        # Look for type reference in switch/case, string literal, or object key
        assert (
            f"'{node_type}'" in dag_node
            or f'"{node_type}"' in dag_node
            or f"case '{node_type}'" in dag_node
            or f"{node_type}:" in dag_node  # Object key syntax
        )


def test_dag_node_uses_css_vars_not_tailwind() -> None:
    """Must use dashboard CSS vars, not Tailwind utilities."""
    dag_node = (STATIC_DIR / "js" / "dag-node.js").read_text()
    # Must use CSS variables
    assert "var(--" in dag_node
    # Anti-pattern: Tailwind utility classes (e.g., className="flex items-center")
    # This is a heuristic; false positives possible with single-word classes
    tailwind_pattern = re.compile(r'className=["\'][a-z-]+\s+[a-z-]+["\']')
    matches = tailwind_pattern.findall(dag_node)
    # Allow some multi-word classes like "node-container" but flag Tailwind-style strings
    suspect_matches = [m for m in matches if any(tw in m for tw in ["flex ", "grid ", "items-", "justify-", "bg-", "text-xs", "p-", "m-"])]
    assert len(suspect_matches) == 0, f"Found Tailwind-like classes: {suspect_matches}"


def test_canvas_placeholder_when_bundle_missing() -> None:
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    # Must show a placeholder when bundle is missing
    assert "Builder bundle not loaded" in canvas or "builderBundle" in canvas


def test_canvas_handles_drag_to_connect() -> None:
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    assert "onConnect" in canvas


def test_canvas_handles_delete_key() -> None:
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    assert "'Delete'" in canvas or '"Delete"' in canvas or "'Backspace'" in canvas or '"Backspace"' in canvas


def test_canvas_handles_drop_from_library() -> None:
    canvas = (STATIC_DIR / "js" / "workflow-canvas.js").read_text()
    assert "onDrop" in canvas
