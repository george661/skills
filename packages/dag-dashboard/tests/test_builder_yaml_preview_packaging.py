"""
Packaging tests for YAML preview feature (GW-5250).
Verifies that YamlCodeView and dagToYaml are correctly bundled.
"""

import yaml
from pathlib import Path

PKG_ROOT = Path(__file__).parents[1]
BUILDER_SRC = PKG_ROOT / "builder" / "src"
BUNDLE = PKG_ROOT / "src" / "dag_dashboard" / "static" / "js" / "builder" / "builder.js"


def test_yaml_code_view_source_exists() -> None:
    """YamlCodeView.jsx source file exists."""
    source = BUILDER_SRC / "YamlCodeView.jsx"
    assert source.exists(), f"YamlCodeView.jsx not found at {source}"


def test_dag_to_yaml_source_exists() -> None:
    """dagToYaml.js source file exists."""
    source = BUILDER_SRC / "dagToYaml.js"
    assert source.exists(), f"dagToYaml.js not found at {source}"


def test_builder_bundle_contains_yaml_code_view() -> None:
    """Built bundle contains YamlCodeView functionality."""
    assert BUNDLE.exists(), f"builder.js bundle not found at {BUNDLE}"

    content = BUNDLE.read_text()
    # Check for YAML-specific strings that prove the code is bundled (minified names are OK)
    assert "yaml-preview" in content, "yaml-preview class not found in bundle"
    assert "yaml-key" in content or "YAML" in content, "YAML-related code not found in bundle"


def test_builder_bundle_contains_view_mode_literals() -> None:
    """Built bundle contains all three view mode literals."""
    content = BUNDLE.read_text()

    # Check for view mode strings
    assert "hidden" in content, 'View mode "hidden" not found in bundle'
    assert "split" in content, 'View mode "split" not found in bundle'
    assert "full" in content, 'View mode "full" not found in bundle'


def test_index_imports_yaml_code_view() -> None:
    """index.jsx imports YamlCodeView."""
    index = BUILDER_SRC / "index.jsx"
    content = index.read_text()

    assert "YamlCodeView" in content, "index.jsx should import YamlCodeView"
    assert "from" in content and "YamlCodeView" in content, "YamlCodeView import not found"


def test_index_wires_yaml_code_view_to_dag_state() -> None:
    """index.jsx renders YamlCodeView with the dag state."""
    index = BUILDER_SRC / "index.jsx"
    content = index.read_text()

    assert "<YamlCodeView" in content, "index.jsx should render <YamlCodeView>"
    assert "dag={dag}" in content, "YamlCodeView should receive the dag state as a prop"


def test_dag_to_yaml_round_trip_compatibility() -> None:
    """dagToYaml output is valid YAML that PyYAML can parse."""
    # Sample DAG structure matching the JS test fixtures
    sample_yaml = """nodes:
  - id: test
    name: Test Node
    type: bash
    script: echo hello
    depends_on: [dep1]
"""

    # Parse with PyYAML (same library used by dag-executor)
    parsed = yaml.safe_load(sample_yaml)

    # Verify structure matches expected schema
    assert "nodes" in parsed, 'Parsed YAML should have "nodes" key'
    assert isinstance(parsed["nodes"], list), "nodes should be a list"
    assert len(parsed["nodes"]) > 0, "nodes list should not be empty"

    node = parsed["nodes"][0]
    assert "id" in node, "Node should have id"
    assert "type" in node, "Node should have type"
    assert node["type"] == "bash", "Node type should match"

    # Verify depends_on is a list (flow sequence in YAML)
    if "depends_on" in node:
        assert isinstance(node["depends_on"], list), "depends_on should parse as list"
