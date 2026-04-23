"""Static checks that the canvas JSX sources live where the bundle expects
them. The JSX behavior itself is tested via the Node test runner inside
``builder/tests/`` — this pytest file guards against accidental file
moves that would break the bundle build without any Node-side failure.
"""
from pathlib import Path


BUILDER_SRC = Path(__file__).parents[1] / "builder" / "src"


def test_workflow_canvas_source_exists() -> None:
    assert (BUILDER_SRC / "WorkflowCanvas.jsx").exists()


def test_dag_node_source_exists() -> None:
    assert (BUILDER_SRC / "DagNode.jsx").exists()


def test_dag_to_reactflow_source_exists() -> None:
    assert (BUILDER_SRC / "dagToReactFlow.js").exists()


def test_use_canvas_state_source_exists() -> None:
    assert (BUILDER_SRC / "useCanvasState.js").exists()


def test_index_jsx_imports_canvas() -> None:
    text = (BUILDER_SRC / "index.jsx").read_text()
    assert "WorkflowCanvas" in text, "index.jsx should import WorkflowCanvas"


def test_canvas_imports_from_hook() -> None:
    text = (BUILDER_SRC / "WorkflowCanvas.jsx").read_text()
    assert "useCanvasState" in text


def test_dag_node_covers_all_six_node_types() -> None:
    text = (BUILDER_SRC / "DagNode.jsx").read_text()
    for node_type in ("bash", "skill", "command", "prompt", "gate", "interrupt"):
        # Accept either a quoted string literal or an object key
        assert (
            f"'{node_type}'" in text
            or f'"{node_type}"' in text
            or f"\n    {node_type}:" in text
            or f"\n        {node_type}:" in text
        ), f"DagNode source should reference node type {node_type!r}"


def test_dag_node_uses_css_variables_not_tailwind() -> None:
    text = (BUILDER_SRC / "DagNode.jsx").read_text()
    assert "var(--" in text, "DagNode should style via dashboard CSS variables"
    # Tailwind-style compound utility class runs look like className="px-4 py-2 bg-blue"
    for suspicious in ("className=\"px-", "className=\"py-", "className=\"bg-", "className=\"text-"):
        assert suspicious not in text, (
            f"DagNode should not use Tailwind utility classes ({suspicious!r} found)"
        )


def test_canvas_listens_for_known_drag_data_formats() -> None:
    text = (BUILDER_SRC / "useCanvasState.js").read_text()
    # NodeLibrary (GW-5245) publishes drops under application/x-dag-node
    assert "application/x-dag-node" in text
