"""Tests for DAG topological sorting with Kahn's algorithm."""
import pytest
from dag_executor.graph import CycleDetectedError, topological_sort_with_layers
from dag_executor.schema import NodeDef


class TestTopologicalSortWithLayers:
    """Test topological sort with parallel layer grouping."""

    def test_linear_chain(self) -> None:
        """Linear chain A -> B -> C produces 3 sequential layers."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=[]),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["B"]),
        ]
        layers = topological_sort_with_layers(nodes)
        assert layers == [["A"], ["B"], ["C"]]

    def test_parallel_nodes(self) -> None:
        """Parallel nodes A, B (no deps) grouped in same layer."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=[]),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=[]),
        ]
        layers = topological_sort_with_layers(nodes)
        # Both nodes have no dependencies, should be in same layer
        assert len(layers) == 1
        assert set(layers[0]) == {"A", "B"}

    def test_diamond_dependency(self) -> None:
        """Diamond dependency A -> B,C -> D resolves correctly."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=[]),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["A"]),
            NodeDef(id="D", name="Node D", type="bash", script="echo D", depends_on=["B", "C"]),
        ]
        layers = topological_sort_with_layers(nodes)
        assert len(layers) == 3
        assert layers[0] == ["A"]
        assert set(layers[1]) == {"B", "C"}  # Parallel execution layer
        assert layers[2] == ["D"]

    def test_cycle_detection(self) -> None:
        """Cycle A -> B -> A rejected with cycle path in error."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=["B"]),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
        ]
        with pytest.raises(CycleDetectedError) as exc_info:
            topological_sort_with_layers(nodes)
        error_msg = str(exc_info.value)
        # Verify error message contains cycle path information
        assert "cycle" in error_msg.lower()
        assert "A" in error_msg or "B" in error_msg

    def test_single_node(self) -> None:
        """Single-node workflow produces single layer."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=[]),
        ]
        layers = topological_sort_with_layers(nodes)
        assert layers == [["A"]]

    def test_complex_multipath(self) -> None:
        """Complex multi-path DAG with mixed serial/parallel execution."""
        # Topology:
        #     A
        #    / \
        #   B   C
        #   |   |\
        #   D   E F
        #    \ /
        #     G
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", depends_on=[]),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["A"]),
            NodeDef(id="D", name="Node D", type="bash", script="echo D", depends_on=["B"]),
            NodeDef(id="E", name="Node E", type="bash", script="echo E", depends_on=["C"]),
            NodeDef(id="F", name="Node F", type="bash", script="echo F", depends_on=["C"]),
            NodeDef(id="G", name="Node G", type="bash", script="echo G", depends_on=["D", "E"]),
        ]
        layers = topological_sort_with_layers(nodes)
        assert len(layers) == 4
        assert layers[0] == ["A"]
        assert set(layers[1]) == {"B", "C"}
        # D depends on B, E and F depend on C - they can all run in parallel
        assert set(layers[2]) == {"D", "E", "F"}
        assert layers[3] == ["G"]

    def test_empty_nodes(self) -> None:
        """Empty nodes array handled gracefully."""
        nodes = []
        layers = topological_sort_with_layers(nodes)
        assert layers == []


class TestConditionalEdges:
    """Test topological sort with conditional edges."""

    def test_node_with_conditional_edges_all_targets_in_correct_layers(self) -> None:
        """Node with conditional edges to 3 targets: all targets ordered after source."""
        from dag_executor.schema import EdgeDef, ModelTier

        nodes = [
            NodeDef(
                id="review",
                name="Review",
                type="prompt",
                prompt="Review code",
                model=ModelTier.OPUS,
                edges=[
                    EdgeDef(target="approve", condition='review.verdict == "approve"'),
                    EdgeDef(target="revise", condition='review.verdict == "revise"'),
                    EdgeDef(target="escalate", default=True)
                ]
            ),
            NodeDef(id="approve", name="Approve", type="bash", script="echo approved"),
            NodeDef(id="revise", name="Revise", type="bash", script="echo revise"),
            NodeDef(id="escalate", name="Escalate", type="bash", script="echo escalate"),
        ]
        layers = topological_sort_with_layers(nodes)

        # Review should be in first layer
        assert "review" in layers[0]
        # All edge targets (approve, revise, escalate) should be in second layer
        assert set(layers[1]) == {"approve", "revise", "escalate"}

    def test_conditional_edges_with_depends_on(self) -> None:
        """Node with both depends_on and edges works correctly."""
        from dag_executor.schema import EdgeDef, ModelTier

        nodes = [
            NodeDef(id="setup", name="Setup", type="bash", script="echo setup"),
            NodeDef(
                id="review",
                name="Review",
                type="prompt",
                prompt="Review",
                model=ModelTier.OPUS,
                depends_on=["setup"],
                edges=[
                    EdgeDef(target="pass", condition='review.ok'),
                    EdgeDef(target="fail", default=True)
                ]
            ),
            NodeDef(id="pass", name="Pass", type="bash", script="echo pass"),
            NodeDef(id="fail", name="Fail", type="bash", script="echo fail"),
        ]
        layers = topological_sort_with_layers(nodes)

        assert layers[0] == ["setup"]
        assert layers[1] == ["review"]
        assert set(layers[2]) == {"pass", "fail"}

    def test_conditional_edge_target_nonexistent(self) -> None:
        """Conditional edge pointing to non-existent target raises ValueError."""
        from dag_executor.schema import EdgeDef, ModelTier

        nodes = [
            NodeDef(
                id="review",
                name="Review",
                type="prompt",
                prompt="Review",
                model=ModelTier.OPUS,
                edges=[
                    EdgeDef(target="nonexistent", condition='review.ok'),
                    EdgeDef(target="escalate", default=True)
                ]
            ),
            NodeDef(id="escalate", name="Escalate", type="bash", script="echo escalate"),
        ]

        with pytest.raises(ValueError) as exc_info:
            topological_sort_with_layers(nodes)
        assert "nonexistent" in str(exc_info.value)
