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
