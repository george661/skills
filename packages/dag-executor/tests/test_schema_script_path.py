"""Tests for script_path field on BashNodeConfig and NodeDef."""
import pytest
from dag_executor.schema import BashNodeConfig, NodeDef


class TestBashNodeConfigScriptPath:
    """Tests for script_path field on BashNodeConfig."""

    def test_bash_node_script_path_only(self):
        """BashNodeConfig with script_path only should parse."""
        config = BashNodeConfig(script_path="x.sh")
        assert config.script_path == "x.sh"
        assert config.script is None

    def test_bash_node_script_only(self):
        """BashNodeConfig with script only should still work (regression)."""
        config = BashNodeConfig(script="echo hi")
        assert config.script == "echo hi"
        assert not hasattr(config, 'script_path') or config.script_path is None

    def test_bash_node_script_and_script_path_mutually_exclusive(self):
        """BashNodeConfig with both script and script_path should raise ValueError."""
        with pytest.raises(ValueError, match="script and script_path are mutually exclusive"):
            BashNodeConfig(script="echo hi", script_path="x.sh")

    def test_bash_node_neither_script_nor_script_path(self):
        """BashNodeConfig with neither script nor script_path should raise ValueError."""
        with pytest.raises(ValueError, match="Either script or script_path must be provided"):
            BashNodeConfig()


class TestNodeDefScriptPath:
    """Tests for script_path field on NodeDef."""

    def test_node_def_bash_with_script_path(self):
        """NodeDef with type=bash and script_path should parse."""
        node = NodeDef(
            id="test",
            name="Test",
            type="bash",
            script_path="x.sh"
        )
        assert node.script_path == "x.sh"
        assert node.script is None

    def test_node_def_bash_script_path_mutual_exclusion(self):
        """NodeDef with type=bash and both script and script_path should raise ValueError."""
        with pytest.raises(ValueError, match="script and script_path are mutually exclusive"):
            NodeDef(
                id="test",
                name="Test",
                type="bash",
                script="echo hi",
                script_path="x.sh"
            )

    def test_node_def_bash_no_script_no_script_path(self):
        """NodeDef with type=bash and neither script nor script_path should raise ValueError."""
        with pytest.raises(ValueError, match="Either script or script_path is required for type=bash"):
            NodeDef(
                id="test",
                name="Test",
                type="bash"
            )

    def test_node_def_script_path_only_on_bash(self):
        """NodeDef with script_path on non-bash type should raise ValueError."""
        with pytest.raises(ValueError, match="script_path field is only allowed on type=bash nodes"):
            NodeDef(
                id="test",
                name="Test",
                type="prompt",
                prompt="Hello",
                script_path="x.sh"
            )
