"""Tests for Mermaid diagram generation."""
import pytest
from dag_executor.schema import WorkflowDef, NodeDef, EdgeDef, WorkflowConfig
from dag_executor.terminal.mermaid_gen import generate_mermaid


# Default config for test workflows
TEST_CONFIG = WorkflowConfig(checkpoint_prefix=".test-checkpoints")


def test_mermaid_output_has_graph_header():
    """Mermaid output contains graph TD header and is wrapped in code fence."""
    workflow = WorkflowDef(
        name="test",
        config=TEST_CONFIG,
        nodes=[
            NodeDef(id="a", name="Node A", type="bash", script="echo a"),
        ],
    )
    result = generate_mermaid(workflow)
    assert "```mermaid" in result
    assert "graph TD" in result
    assert result.strip().endswith("```")


def test_mermaid_renders_all_nodes_with_labels():
    """Every node appears exactly once with its label."""
    workflow = WorkflowDef(
        name="test",
        config=TEST_CONFIG,
        nodes=[
            NodeDef(id="node_a", name="Node A", type="bash", script="echo a"),
            NodeDef(id="node_b", name="Node B", type="bash", script="echo b"),
        ],
    )
    result = generate_mermaid(workflow)
    # Each node should appear exactly once
    assert result.count("node_a[Node A]") == 1
    assert result.count("node_b[Node B]") == 1


def test_mermaid_renders_depends_on_edges():
    """a --> b for each depends_on entry."""
    workflow = WorkflowDef(
        name="test",
        config=TEST_CONFIG,
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
            NodeDef(id="b", name="B", type="bash", script="echo b", depends_on=["a"]),
            NodeDef(id="c", name="C", type="bash", script="echo c", depends_on=["a", "b"]),
        ],
    )
    result = generate_mermaid(workflow)
    assert "a --> b" in result
    assert "a --> c" in result
    assert "b --> c" in result


def test_mermaid_renders_conditional_edges():
    """Conditional edge produces a -->|condition| b; default produces a -->|default| b."""
    workflow = WorkflowDef(
        name="test",
        config=TEST_CONFIG,
        nodes=[
            NodeDef(
                id="a",
                name="A",
                type="bash",
                script="echo a",
                edges=[
                    EdgeDef(target="b", condition="success"),
                    EdgeDef(target="c", default=True),
                ],
            ),
            NodeDef(id="b", name="B", type="bash", script="echo b"),
            NodeDef(id="c", name="C", type="bash", script="echo c"),
        ],
    )
    result = generate_mermaid(workflow)
    assert "a -->|success| b" in result
    assert "a -->|default| c" in result


def test_mermaid_uses_id_when_name_absent():
    """When node has no name, uses id as label."""
    workflow = WorkflowDef(
        name="test",
        config=TEST_CONFIG,
        nodes=[
            NodeDef(id="node_x", name="node_x", type="bash", script="echo x"),  # name==id
        ],
    )
    result = generate_mermaid(workflow)
    assert "node_x[node_x]" in result


def test_mermaid_gen_rejects_non_workflow_input():
    """Type error on wrong arg type."""
    with pytest.raises(AttributeError):
        generate_mermaid("not a workflow")  # type: ignore
