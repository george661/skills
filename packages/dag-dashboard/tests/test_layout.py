"""Tests for DAG layout computation."""
import time
from typing import Any, Dict, List

import pytest

from dag_dashboard.layout import compute_layout, topological_sort_with_layers


def test_topological_sort_linear():
    """Test topological sort on a linear chain (A→B→C)."""
    nodes = [
        {"node_name": "A", "depends_on": []},
        {"node_name": "B", "depends_on": ["A"]},
        {"node_name": "C", "depends_on": ["B"]},
    ]
    
    layers = topological_sort_with_layers(nodes)
    
    assert layers[0] == ["A"]
    assert layers[1] == ["B"]
    assert layers[2] == ["C"]


def test_topological_sort_parallel():
    """Test topological sort on a parallel workflow (A→[B,C]→D diamond)."""
    nodes = [
        {"node_name": "A", "depends_on": []},
        {"node_name": "B", "depends_on": ["A"]},
        {"node_name": "C", "depends_on": ["A"]},
        {"node_name": "D", "depends_on": ["B", "C"]},
    ]
    
    layers = topological_sort_with_layers(nodes)
    
    assert layers[0] == ["A"]
    assert set(layers[1]) == {"B", "C"}  # B and C on same layer
    assert layers[2] == ["D"]


def test_topological_sort_wide_fanout():
    """Test topological sort on a wide fan-out (A→[B,C,D,E])."""
    nodes = [
        {"node_name": "A", "depends_on": []},
        {"node_name": "B", "depends_on": ["A"]},
        {"node_name": "C", "depends_on": ["A"]},
        {"node_name": "D", "depends_on": ["A"]},
        {"node_name": "E", "depends_on": ["A"]},
    ]
    
    layers = topological_sort_with_layers(nodes)
    
    assert layers[0] == ["A"]
    assert set(layers[1]) == {"B", "C", "D", "E"}


def test_compute_layout_linear():
    """Test layout computation for a linear workflow."""
    nodes = [
        {
            "id": "run1:A",
            "run_id": "run1",
            "node_name": "A",
            "status": "completed",
            "depends_on": [],
            "started_at": "2024-01-01T00:00:00Z",
            "finished_at": "2024-01-01T00:01:00Z",
        },
        {
            "id": "run1:B",
            "run_id": "run1",
            "node_name": "B",
            "status": "running",
            "depends_on": ["A"],
            "started_at": "2024-01-01T00:01:00Z",
            "finished_at": None,
        },
        {
            "id": "run1:C",
            "run_id": "run1",
            "node_name": "C",
            "status": "pending",
            "depends_on": ["B"],
            "started_at": None,
            "finished_at": None,
        },
    ]
    
    layout = compute_layout(nodes)
    
    assert len(layout["nodes"]) == 3
    assert len(layout["edges"]) == 2
    
    # Verify nodes have positions and layers
    node_a = next(n for n in layout["nodes"] if n["node_name"] == "A")
    node_b = next(n for n in layout["nodes"] if n["node_name"] == "B")
    node_c = next(n for n in layout["nodes"] if n["node_name"] == "C")
    
    assert node_a["layer"] == 0
    assert node_b["layer"] == 1
    assert node_c["layer"] == 2
    
    # Verify y positions increase with layers
    assert node_a["y"] < node_b["y"] < node_c["y"]
    
    # Verify edges
    edges = layout["edges"]
    assert any(e["source"] == "A" and e["target"] == "B" for e in edges)
    assert any(e["source"] == "B" and e["target"] == "C" for e in edges)


def test_compute_layout_diamond():
    """Test layout computation for a diamond workflow (A→[B,C]→D)."""
    nodes = [
        {
            "id": "run1:A",
            "run_id": "run1",
            "node_name": "A",
            "status": "completed",
            "depends_on": [],
        },
        {
            "id": "run1:B",
            "run_id": "run1",
            "node_name": "B",
            "status": "running",
            "depends_on": ["A"],
        },
        {
            "id": "run1:C",
            "run_id": "run1",
            "node_name": "C",
            "status": "running",
            "depends_on": ["A"],
        },
        {
            "id": "run1:D",
            "run_id": "run1",
            "node_name": "D",
            "status": "pending",
            "depends_on": ["B", "C"],
        },
    ]
    
    layout = compute_layout(nodes)
    
    assert len(layout["nodes"]) == 4
    assert len(layout["edges"]) == 4  # A→B, A→C, B→D, C→D
    
    # Verify B and C are on the same layer
    node_b = next(n for n in layout["nodes"] if n["node_name"] == "B")
    node_c = next(n for n in layout["nodes"] if n["node_name"] == "C")
    
    assert node_b["layer"] == node_c["layer"]


def test_compute_layout_performance_50_nodes():
    """Test that 50-node DAG layout completes in < 500ms."""
    # Create a 50-node linear chain
    nodes = []
    for i in range(50):
        node_name = f"node_{i}"
        depends_on = [f"node_{i-1}"] if i > 0 else []
        nodes.append({
            "id": f"run1:{node_name}",
            "run_id": "run1",
            "node_name": node_name,
            "status": "pending",
            "depends_on": depends_on,
        })
    
    start = time.time()
    layout = compute_layout(nodes)
    elapsed_ms = (time.time() - start) * 1000
    
    assert len(layout["nodes"]) == 50
    assert len(layout["edges"]) == 49
    assert elapsed_ms < 500, f"Layout took {elapsed_ms:.2f}ms, should be < 500ms"


def test_compute_layout_empty():
    """Test layout computation with no nodes."""
    layout = compute_layout([])

    assert layout["nodes"] == []
    assert layout["edges"] == []


def test_compute_failure_path_no_failures():
    """Test compute_failure_path returns empty set when all nodes completed."""
    from dag_dashboard.layout import compute_failure_path

    nodes = [
        {"node_name": "A", "status": "completed", "depends_on": []},
        {"node_name": "B", "status": "completed", "depends_on": ["A"]},
        {"node_name": "C", "status": "completed", "depends_on": ["B"]},
    ]

    failure_path = compute_failure_path(nodes)
    assert failure_path == set()


def test_compute_failure_path_marks_failed_and_downstream():
    """Test failure path marks failed node and skipped downstream nodes."""
    from dag_dashboard.layout import compute_failure_path

    # Diamond DAG: A completed, B failed, C depends on A (completed), D depends on B (pending)
    nodes = [
        {"node_name": "A", "status": "completed", "depends_on": []},
        {"node_name": "B", "status": "failed", "depends_on": ["A"]},
        {"node_name": "C", "status": "completed", "depends_on": ["A"]},
        {"node_name": "D", "status": "pending", "depends_on": ["B"]},
    ]

    failure_path = compute_failure_path(nodes)

    # B is failed, D is downstream of B and pending → both on failure path
    assert "B" in failure_path
    assert "D" in failure_path
    # A and C are not on failure path
    assert "A" not in failure_path
    assert "C" not in failure_path


def test_compute_failure_path_multiple_failures():
    """Test failure path with multiple failed branches."""
    from dag_dashboard.layout import compute_failure_path

    # Two independent branches: A→B (B failed), C→D (D failed), E→F (both completed)
    nodes = [
        {"node_name": "A", "status": "completed", "depends_on": []},
        {"node_name": "B", "status": "failed", "depends_on": ["A"]},
        {"node_name": "C", "status": "completed", "depends_on": []},
        {"node_name": "D", "status": "failed", "depends_on": ["C"]},
        {"node_name": "E", "status": "completed", "depends_on": []},
        {"node_name": "F", "status": "completed", "depends_on": ["E"]},
    ]

    failure_path = compute_failure_path(nodes)

    # B and D are both failed → both on failure path
    assert "B" in failure_path
    assert "D" in failure_path
    # Others are not
    assert "A" not in failure_path
    assert "C" not in failure_path
    assert "E" not in failure_path
    assert "F" not in failure_path


def test_compute_layout_includes_failure_path_flag():
    """Test compute_layout adds failure_path boolean to nodes."""
    nodes = [
        {
            "id": "run1:A",
            "run_id": "run1",
            "node_name": "A",
            "status": "completed",
            "depends_on": [],
        },
        {
            "id": "run1:B",
            "run_id": "run1",
            "node_name": "B",
            "status": "failed",
            "depends_on": ["A"],
        },
        {
            "id": "run1:C",
            "run_id": "run1",
            "node_name": "C",
            "status": "skipped",
            "depends_on": ["B"],
        },
    ]

    layout = compute_layout(nodes)

    # Find nodes by name
    nodes_by_name = {n["node_name"]: n for n in layout["nodes"]}

    # A completed → not on failure path
    assert nodes_by_name["A"]["failure_path"] is False
    # B failed → on failure path
    assert nodes_by_name["B"]["failure_path"] is True
    # C skipped and depends on B → on failure path
    assert nodes_by_name["C"]["failure_path"] is True
