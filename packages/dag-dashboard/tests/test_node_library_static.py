"""Test NodeLibrary.jsx source file.

Note: NodeLibrary was ported from a classic-React script to an ESM module inside
the builder bundle (GW-5333). The old node-library.js file is deleted. These tests
now read from builder/src/NodeLibrary.jsx.
"""
import pytest
from pathlib import Path


def test_node_library_has_categories() -> None:
    """Test that NodeLibrary.jsx contains all three category labels."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should have category labels
    assert "Node types" in content or "Node Types" in content
    assert "Commands" in content
    assert "Skills" in content


def test_node_library_has_search_input() -> None:
    """Test that NodeLibrary.jsx has a search input."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should have input for search
    assert 'type="text"' in content or 'type="search"' in content
    assert "placeholder" in content.lower()


def test_node_library_has_draggable_items() -> None:
    """Test that NodeLibrary.jsx marks items as draggable."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should set draggable attribute
    assert "draggable" in content


def test_node_library_uses_drag_data_transfer() -> None:
    """Test that NodeLibrary.jsx uses dataTransfer for drag data."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should use dataTransfer API
    assert "dataTransfer" in content
    assert "setData" in content
    assert "application/x-dag-node" in content


def test_node_library_persists_width_to_localstorage() -> None:
    """Test that NodeLibrary.jsx persists width to localStorage."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should use localStorage for width persistence
    assert "localStorage" in content
    assert "archon-node-library-width" in content


def test_node_library_fetches_definitions() -> None:
    """Test that NodeLibrary.jsx fetches from /api/definitions."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should fetch commands from definitions endpoint
    assert "/api/definitions" in content


def test_node_library_fetches_skills() -> None:
    """Test that NodeLibrary.jsx fetches from /api/skills."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should fetch skills from skills endpoint
    assert "/api/skills" in content


def test_node_library_has_resize_handle() -> None:
    """Test that NodeLibrary.jsx has a resize handle."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should have resize handle with mouse event handlers
    assert "onMouseDown" in content or "mousedown" in content
    assert "onMouseMove" in content or "mousemove" in content


def test_node_library_has_six_node_types() -> None:
    """Test that NodeLibrary.jsx defines all 6 runner types."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should have all 6 runner types in a constant or list
    assert "bash" in content
    assert "command" in content
    assert "gate" in content
    assert "interrupt" in content
    assert "prompt" in content
    assert "skill" in content


def test_node_library_is_esm_module() -> None:
    """Test that NodeLibrary.jsx is an ESM module (not classic React)."""
    node_library_path = Path(__file__).parent.parent / "builder" / "src" / "NodeLibrary.jsx"
    content = node_library_path.read_text()
    
    # Should import React (ESM style)
    assert "import React from 'react'" in content
    
    # Should export default (not module.exports)
    assert "export default NodeLibrary" in content
    
    # Should NOT use global React or module.exports
    assert "module.exports" not in content
