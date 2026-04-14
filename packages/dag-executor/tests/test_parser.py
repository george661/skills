"""Tests for YAML workflow parser."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from dag_executor.parser import load_workflow, load_workflow_from_string
from dag_executor.schema import WorkflowDef, TriggerRule, ModelTier, OnFailure


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestLoadWorkflow:
    """Test load_workflow function."""
    
    def test_load_valid_workflow(self) -> None:
        """Test loading a valid workflow from YAML."""
        workflow = load_workflow(str(FIXTURES_DIR / "valid_workflow.yaml"))
        
        assert isinstance(workflow, WorkflowDef)
        assert workflow.name == "Test Workflow"
        assert workflow.config.checkpoint_prefix == "test-wf"
        assert workflow.config.worktree is True
        assert workflow.config.labels.on_failure == "workflow-failed"
    
    def test_valid_workflow_inputs(self) -> None:
        """Test that inputs are parsed correctly."""
        workflow = load_workflow(str(FIXTURES_DIR / "valid_workflow.yaml"))
        
        assert "user_id" in workflow.inputs
        assert workflow.inputs["user_id"].required is True
        assert workflow.inputs["user_id"].type == "string"
        
        assert "dry_run" in workflow.inputs
        assert workflow.inputs["dry_run"].required is False
        assert workflow.inputs["dry_run"].default is False
        
        assert "email_pattern" in workflow.inputs
        assert workflow.inputs["email_pattern"].pattern is not None
    
    def test_valid_workflow_nodes(self) -> None:
        """Test that all node types are parsed correctly."""
        workflow = load_workflow(str(FIXTURES_DIR / "valid_workflow.yaml"))
        
        assert len(workflow.nodes) == 5
        
        # Skill node
        skill_node = next(n for n in workflow.nodes if n.id == "fetch-user")
        assert skill_node.type == "skill"
        assert skill_node.skill == "/skills/db/get-user.skill.md"
        assert skill_node.params is not None
        
        # Bash node
        bash_node = next(n for n in workflow.nodes if n.id == "validate-email")
        assert bash_node.type == "bash"
        assert "EMAIL" in bash_node.script
        assert bash_node.retry is not None
        assert bash_node.retry.max_attempts == 2
        
        # Command node
        cmd_node = next(n for n in workflow.nodes if n.id == "send-notification")
        assert cmd_node.type == "command"
        assert cmd_node.command == "notify"
        assert len(cmd_node.args) == 2
        assert cmd_node.when is not None
        assert cmd_node.trigger_rule == TriggerRule.ALL_SUCCESS
        assert cmd_node.on_failure == OnFailure.CONTINUE
        
        # Prompt node
        prompt_node = next(n for n in workflow.nodes if n.id == "generate-report")
        assert prompt_node.type == "prompt"
        assert prompt_node.prompt is not None
        assert prompt_node.model == ModelTier.SONNET
        assert prompt_node.trigger_rule == TriggerRule.ONE_SUCCESS
        
        # Gate node
        gate_node = next(n for n in workflow.nodes if n.id == "approval-gate")
        assert gate_node.type == "gate"
        assert gate_node.condition == "approved == true"
        assert gate_node.timeout == 3600
    
    def test_valid_workflow_outputs(self) -> None:
        """Test that outputs are parsed correctly."""
        workflow = load_workflow(str(FIXTURES_DIR / "valid_workflow.yaml"))
        
        assert "report" in workflow.outputs
        assert workflow.outputs["report"].node == "generate-report"
        
        assert "user_email" in workflow.outputs
        assert workflow.outputs["user_email"].node == "fetch-user"
        assert workflow.outputs["user_email"].field == "email"
    
    def test_file_not_found(self) -> None:
        """Test that FileNotFoundError is raised for missing files."""
        with pytest.raises(FileNotFoundError):
            load_workflow("/nonexistent/path.yaml")
    
    def test_invalid_yaml_syntax(self) -> None:
        """Test that invalid YAML syntax is rejected."""
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            load_workflow_from_string("invalid: yaml: [broken")
        assert "yaml" in str(exc_info.value).lower() or "parse" in str(exc_info.value).lower()
    
    def test_empty_nodes_rejected(self) -> None:
        """Test that workflows with empty nodes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            load_workflow(str(FIXTURES_DIR / "invalid_empty_nodes.yaml"))
        error_str = str(exc_info.value).lower()
        assert "nodes" in error_str
    
    def test_missing_config_rejected(self) -> None:
        """Test that workflows without config are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            load_workflow(str(FIXTURES_DIR / "invalid_missing_config.yaml"))
        error_str = str(exc_info.value).lower()
        assert "config" in error_str
    
    def test_duplicate_node_ids_rejected(self) -> None:
        """Test that duplicate node IDs are detected and rejected."""
        with pytest.raises(ValueError) as exc_info:
            load_workflow(str(FIXTURES_DIR / "invalid_duplicate_ids.yaml"))
        error_str = str(exc_info.value).lower()
        assert "duplicate" in error_str and "node" in error_str
    
    def test_prompt_mutual_exclusivity(self) -> None:
        """Test that prompt and prompt_file mutual exclusivity is enforced."""
        with pytest.raises(ValidationError) as exc_info:
            load_workflow(str(FIXTURES_DIR / "invalid_prompt_both.yaml"))
        error_str = str(exc_info.value).lower()
        assert "prompt" in error_str
    
    def test_missing_required_field_error(self) -> None:
        """Test that missing required fields produce actionable errors."""
        yaml_str = """
name: Test
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: Missing Type
    script: echo test
"""
        with pytest.raises(ValidationError) as exc_info:
            load_workflow_from_string(yaml_str)
        error_str = str(exc_info.value).lower()
        assert "type" in error_str or "required" in error_str


class TestLoadWorkflowFromString:
    """Test load_workflow_from_string function."""
    
    def test_load_from_string(self) -> None:
        """Test loading workflow from YAML string."""
        yaml_str = """
name: String Test
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: Test Node
    type: bash
    script: echo hello
"""
        workflow = load_workflow_from_string(yaml_str)
        assert workflow.name == "String Test"
        assert len(workflow.nodes) == 1
        assert workflow.nodes[0].id == "node1"
    
    def test_empty_string_rejected(self) -> None:
        """Test that empty string is rejected."""
        with pytest.raises((ValueError, ValidationError)):
            load_workflow_from_string("")
    
    def test_invalid_structure(self) -> None:
        """Test that invalid structure produces clear error."""
        yaml_str = """
name: Test
nodes: not_a_list
"""
        with pytest.raises(ValidationError) as exc_info:
            load_workflow_from_string(yaml_str)
        error_str = str(exc_info.value)
        assert "nodes" in error_str or "list" in error_str.lower()
