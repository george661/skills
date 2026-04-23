"""Tests that NodeLibrary is properly bundled into builder.js"""

import os
from pathlib import Path


def test_builder_bundle_contains_node_library():
    """Verify NodeLibrary-specific constants appear in compiled bundle"""
    builder_js = Path(__file__).parent.parent / 'src' / 'dag_dashboard' / 'static' / 'js' / 'builder' / 'builder.js'

    if not builder_js.exists():
        # Bundle not built yet in dev — skip or fail
        raise FileNotFoundError(
            f"Bundle not found at {builder_js}. Run 'cd builder && npm run build' first."
        )
    
    bundle_content = builder_js.read_text()
    
    # Unique NodeLibrary markers
    assert 'archon-node-library-width' in bundle_content, \
        "Bundle should contain localStorage key for NodeLibrary width"
    
    assert 'Node Library' in bundle_content, \
        "Bundle should contain 'Node Library' header text"


def test_builder_bundle_mounts_node_library():
    """Verify bundle includes API endpoints NodeLibrary fetches from"""
    builder_js = Path(__file__).parent.parent / 'src' / 'dag_dashboard' / 'static' / 'js' / 'builder' / 'builder.js'

    if not builder_js.exists():
        raise FileNotFoundError(
            f"Bundle not found at {builder_js}. Run 'cd builder && npm run build' first."
        )
    
    bundle_content = builder_js.read_text()
    
    # NodeLibrary fetches these endpoints
    assert '/api/definitions' in bundle_content, \
        "Bundle should reference /api/definitions for commands"
    
    assert '/api/skills' in bundle_content, \
        "Bundle should reference /api/skills"


def test_index_html_loads_node_library_css():
    """Verify index.html links to node-library.css"""
    index_html = Path(__file__).parent.parent / 'src' / 'dag_dashboard' / 'static' / 'index.html'
    
    if not index_html.exists():
        raise FileNotFoundError(f"index.html not found at {index_html}")
    
    html_content = index_html.read_text()
    
    assert 'node-library.css' in html_content, \
        "index.html should load node-library.css stylesheet"
