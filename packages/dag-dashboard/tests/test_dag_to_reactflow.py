"""Tests for dag-to-reactflow.js conversion utility."""
from pathlib import Path
import subprocess
import json
import time
import pytest


STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def has_node() -> bool:
    """Check if node is available."""
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not has_node(), reason="node not available")
def test_dag_to_reactflow_roundtrip() -> None:
    """Test DAG -> React Flow -> DAG conversion."""
    dag_to_rf_path = STATIC_DIR / "js" / "dag-to-reactflow.js"
    assert dag_to_rf_path.exists()
    
    # 3-node DAG fixture
    dag = {
        "nodes": [
            {"id": "1", "type": "bash", "config": {"command": "echo a"}},
            {"id": "2", "type": "skill", "config": {"skill": "test"}, "depends_on": ["1"]},
            {"id": "3", "type": "command", "config": {"cmd": "ls"}, "depends_on": ["2"]},
        ]
    }
    
    # Load the JS module and call dagToReactFlow
    code = f"""
    const fs = require('fs');
    eval(fs.readFileSync('{dag_to_rf_path}', 'utf8'));
    const dag = {json.dumps(dag)};
    const rf = dagToReactFlow(dag);
    console.log(JSON.stringify(rf));
    """
    
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    rf_output = json.loads(result.stdout)
    
    # Check React Flow output
    assert "nodes" in rf_output
    assert "edges" in rf_output
    assert len(rf_output["nodes"]) == 3
    assert len(rf_output["edges"]) == 2  # 1->2, 2->3
    
    # Verify edges match depends_on
    edge_pairs = {(e["source"], e["target"]) for e in rf_output["edges"]}
    assert ("1", "2") in edge_pairs
    assert ("2", "3") in edge_pairs
    
    # Test reverse conversion
    code2 = f"""
    const fs = require('fs');
    eval(fs.readFileSync('{dag_to_rf_path}', 'utf8'));
    const rf = {json.dumps(rf_output)};
    const dag_back = reactFlowToDag(rf);
    console.log(JSON.stringify(dag_back));
    """
    
    result2 = subprocess.run(["node", "-e", code2], capture_output=True, text=True, check=True)
    dag_back = json.loads(result2.stdout)
    
    # Check roundtrip (ignore positions)
    assert len(dag_back["nodes"]) == 3
    for orig, back in zip(dag["nodes"], dag_back["nodes"]):
        assert orig["id"] == back["id"]
        assert orig["type"] == back["type"]


@pytest.mark.skipif(not has_node(), reason="node not available")
def test_dagre_layout_50_node_perf() -> None:
    """Test 50-node layout completes in <500ms."""
    dag_to_rf_path = STATIC_DIR / "js" / "dag-to-reactflow.js"
    assert dag_to_rf_path.exists()
    
    # Generate 50-node linear-ish DAG
    nodes = [{"id": str(i), "type": "bash", "config": {"command": f"echo {i}"}} for i in range(50)]
    for i in range(1, 50):
        nodes[i]["depends_on"] = [str(i-1)]
    
    dag = {"nodes": nodes}
    
    code = f"""
    const fs = require('fs');
    eval(fs.readFileSync('{dag_to_rf_path}', 'utf8'));
    const dag = {json.dumps(dag)};
    const start = Date.now();
    const rf = dagToReactFlow(dag);
    const elapsed = Date.now() - start;
    console.log(JSON.stringify({{elapsed, nodeCount: rf.nodes.length}}));
    """
    
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    
    assert output["nodeCount"] == 50
    assert output["elapsed"] < 500, f"Layout took {output['elapsed']}ms, expected <500ms"
    
    # Also verify all nodes have positions assigned
    rf_output_code = f"""
    const fs = require('fs');
    eval(fs.readFileSync('{dag_to_rf_path}', 'utf8'));
    const dag = {json.dumps(dag)};
    const rf = dagToReactFlow(dag);
    console.log(JSON.stringify(rf));
    """
    result2 = subprocess.run(["node", "-e", rf_output_code], capture_output=True, text=True, check=True)
    rf = json.loads(result2.stdout)
    
    for node in rf["nodes"]:
        assert "position" in node
        assert "x" in node["position"]
        assert "y" in node["position"]


def test_depends_on_builds_edges_static() -> None:
    """Static check: depends_on field is used to build edges."""
    dag_to_rf_js = (STATIC_DIR / "js" / "dag-to-reactflow.js").read_text()
    assert "depends_on" in dag_to_rf_js
