"""Tests for workflow definition models (for YAML parsing)."""
import pytest
from pydantic import ValidationError

from dag_executor.schema import (
    TriggerRule,
    ModelTier,
    DispatchMode,
    OnFailure,
    OutputFormat,
    RetryConfig,
    InputDef,
    OutputDef,
    SkillNodeConfig,
    CommandNodeConfig,
    PromptNodeConfig,
    BashNodeConfig,
    GateNodeConfig,
    NodeDef,
    WorkflowConfig,
    WorkflowDef,
)


class TestEnums:
    """Test enum definitions."""
    
    def test_trigger_rule_values(self) -> None:
        """Test TriggerRule enum values."""
        assert TriggerRule.ALL_SUCCESS == "all_success"
        assert TriggerRule.ONE_SUCCESS == "one_success"
        assert TriggerRule.ALL_DONE == "all_done"
    
    def test_model_tier_values(self) -> None:
        """Test ModelTier enum values."""
        assert ModelTier.OPUS == "opus"
        assert ModelTier.SONNET == "sonnet"
        assert ModelTier.HAIKU == "haiku"
        assert ModelTier.LOCAL == "local"
    
    def test_dispatch_mode_values(self) -> None:
        """Test DispatchMode enum values."""
        assert DispatchMode.INLINE == "inline"
        assert DispatchMode.LOCAL == "local"
    
    def test_on_failure_values(self) -> None:
        """Test OnFailure enum values."""
        assert OnFailure.STOP == "stop"
        assert OnFailure.CONTINUE == "continue"
        assert OnFailure.SKIP_DOWNSTREAM == "skip_downstream"
    
    def test_output_format_values(self) -> None:
        """Test OutputFormat enum values."""
        assert OutputFormat.JSON == "json"
        assert OutputFormat.TEXT == "text"
        assert OutputFormat.YAML == "yaml"


class TestRetryConfig:
    """Test RetryConfig model."""
    
    def test_valid_retry_config(self) -> None:
        """Test creating valid retry config."""
        retry = RetryConfig(max_attempts=3, delay_ms=1000)
        assert retry.max_attempts == 3
        assert retry.delay_ms == 1000
    
    def test_retry_config_defaults(self) -> None:
        """Test retry config with defaults."""
        retry = RetryConfig(max_attempts=2)
        assert retry.max_attempts == 2
        assert retry.delay_ms == 0
    
    def test_invalid_max_attempts(self) -> None:
        """Test that max_attempts must be positive."""
        with pytest.raises(ValidationError) as exc_info:
            RetryConfig(max_attempts=0)
        assert "max_attempts" in str(exc_info.value)


class TestInputDef:
    """Test InputDef model."""
    
    def test_required_input(self) -> None:
        """Test required input definition."""
        input_def = InputDef(type="string", required=True)
        assert input_def.type == "string"
        assert input_def.required is True
        assert input_def.default is None
    
    def test_optional_input_with_default(self) -> None:
        """Test optional input with default value."""
        input_def = InputDef(type="boolean", required=False, default=False)
        assert input_def.type == "boolean"
        assert input_def.required is False
        assert input_def.default is False
    
    def test_input_with_pattern(self) -> None:
        """Test input with regex pattern validation."""
        input_def = InputDef(
            type="string",
            required=True,
            pattern="^[a-z]+$"
        )
        assert input_def.pattern == "^[a-z]+$"
    
    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            InputDef(type="string", required=True, unknown_field="value")  # type: ignore
        assert "extra" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()


class TestNodeTypeConfigs:
    """Test node type-specific config models."""
    
    def test_skill_node_config(self) -> None:
        """Test SkillNodeConfig model."""
        config = SkillNodeConfig(
            skill="/skills/test.md",
            params={"arg1": "value1"}
        )
        assert config.skill == "/skills/test.md"
        assert config.params == {"arg1": "value1"}
    
    def test_command_node_config(self) -> None:
        """Test CommandNodeConfig model."""
        config = CommandNodeConfig(
            command="test-cmd",
            args=["arg1", "arg2"]
        )
        assert config.command == "test-cmd"
        assert config.args == ["arg1", "arg2"]
    
    def test_prompt_node_with_prompt(self) -> None:
        """Test PromptNodeConfig with direct prompt."""
        config = PromptNodeConfig(
            prompt="Test prompt",
            model=ModelTier.SONNET
        )
        assert config.prompt == "Test prompt"
        assert config.prompt_file is None
        assert config.model == ModelTier.SONNET
    
    def test_prompt_node_with_file(self) -> None:
        """Test PromptNodeConfig with prompt file."""
        config = PromptNodeConfig(
            prompt_file="/path/to/prompt.md",
            model=ModelTier.OPUS
        )
        assert config.prompt is None
        assert config.prompt_file == "/path/to/prompt.md"
    
    def test_prompt_node_mutual_exclusivity(self) -> None:
        """Test that prompt and prompt_file are mutually exclusive."""
        with pytest.raises(ValidationError) as exc_info:
            PromptNodeConfig(
                prompt="Direct prompt",
                prompt_file="/path/to/file.md",
                model=ModelTier.SONNET
            )
        error_str = str(exc_info.value).lower()
        assert "prompt" in error_str or "mutually exclusive" in error_str or "one of" in error_str
    
    def test_prompt_node_requires_one(self) -> None:
        """Test that prompt or prompt_file is required."""
        with pytest.raises(ValidationError) as exc_info:
            PromptNodeConfig(model=ModelTier.SONNET)  # type: ignore
        error_str = str(exc_info.value).lower()
        assert "prompt" in error_str or "required" in error_str
    
    def test_bash_node_config(self) -> None:
        """Test BashNodeConfig model."""
        config = BashNodeConfig(script="echo hello")
        assert config.script == "echo hello"
    
    def test_gate_node_config(self) -> None:
        """Test GateNodeConfig model."""
        config = GateNodeConfig(condition="approved == true")
        assert config.condition == "approved == true"


class TestNodeDef:
    """Test NodeDef model."""
    
    def test_skill_node(self) -> None:
        """Test creating a skill node definition."""
        node = NodeDef(
            id="skill1",
            name="Test Skill",
            type="skill",
            skill="/skills/test.md",
            params={"arg": "value"}
        )
        assert node.id == "skill1"
        assert node.type == "skill"
        assert node.skill == "/skills/test.md"
    
    def test_command_node(self) -> None:
        """Test creating a command node definition."""
        node = NodeDef(
            id="cmd1",
            name="Test Command",
            type="command",
            command="test",
            args=["arg1"]
        )
        assert node.id == "cmd1"
        assert node.type == "command"
        assert node.command == "test"
    
    def test_prompt_node(self) -> None:
        """Test creating a prompt node definition."""
        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="Test prompt",
            model=ModelTier.SONNET
        )
        assert node.id == "prompt1"
        assert node.type == "prompt"
        assert node.prompt == "Test prompt"
    
    def test_bash_node(self) -> None:
        """Test creating a bash node definition."""
        node = NodeDef(
            id="bash1",
            name="Test Bash",
            type="bash",
            script="echo test"
        )
        assert node.id == "bash1"
        assert node.type == "bash"
        assert node.script == "echo test"
    
    def test_gate_node(self) -> None:
        """Test creating a gate node definition."""
        node = NodeDef(
            id="gate1",
            name="Test Gate",
            type="gate",
            condition="ready == true"
        )
        assert node.id == "gate1"
        assert node.type == "gate"
        assert node.condition == "ready == true"
    
    def test_node_with_dependencies(self) -> None:
        """Test node with dependencies."""
        node = NodeDef(
            id="node2",
            name="Dependent Node",
            type="bash",
            script="echo test",
            depends_on=["node1"]
        )
        assert node.depends_on == ["node1"]
    
    def test_node_with_retry(self) -> None:
        """Test node with retry configuration."""
        node = NodeDef(
            id="node3",
            name="Retry Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=1000)
        )
        assert node.retry is not None
        assert node.retry.max_attempts == 3
    
    def test_node_with_trigger_rule(self) -> None:
        """Test node with trigger rule."""
        node = NodeDef(
            id="node4",
            name="Trigger Node",
            type="bash",
            script="echo test",
            trigger_rule=TriggerRule.ONE_SUCCESS
        )
        assert node.trigger_rule == TriggerRule.ONE_SUCCESS
    
    def test_node_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected on nodes."""
        with pytest.raises(ValidationError) as exc_info:
            NodeDef(
                id="node1",
                name="Test",
                type="bash",
                script="echo test",
                unknown_field="value"  # type: ignore
            )
        error_str = str(exc_info.value).lower()
        assert "extra" in error_str or "unknown" in error_str


class TestDispatchEnforcement:
    """Verify dispatch semantics for node types that always run in-process.

    PRP-PLAT-010 Task 12 / AC-18: bash, gate, and interrupt nodes never shell
    out, so `dispatch: local` is nonsensical and must be rejected loudly.
    `dispatch: inline` is accepted as a no-op confirmation. PRP-PLAT-006 will
    give dispatch first-class runtime semantics on prompt/skill/command nodes.
    """

    @pytest.mark.parametrize("node_type,extra", [
        ("bash", {"script": "echo test"}),
        ("gate", {"condition": "ready == true"}),
        ("interrupt", {"message": "approve?", "resume_key": "ok"}),
    ])
    def test_dispatch_local_rejected_on_inprocess_types(self, node_type, extra):
        with pytest.raises(ValidationError) as exc_info:
            NodeDef(
                id="n",
                name="Test",
                type=node_type,
                dispatch=DispatchMode.LOCAL,
                **extra,
            )
        assert "dispatch: local is not valid" in str(exc_info.value)

    @pytest.mark.parametrize("node_type,extra", [
        ("bash", {"script": "echo test"}),
        ("gate", {"condition": "ready == true"}),
        ("interrupt", {"message": "approve?", "resume_key": "ok"}),
    ])
    def test_dispatch_inline_accepted_on_inprocess_types(self, node_type, extra):
        node = NodeDef(
            id="n",
            name="Test",
            type=node_type,
            dispatch=DispatchMode.INLINE,
            **extra,
        )
        assert node.dispatch == DispatchMode.INLINE


class TestWorkflowConfig:
    """Test WorkflowConfig model."""
    
    def test_minimal_config(self) -> None:
        """Test minimal workflow config."""
        config = WorkflowConfig(checkpoint_prefix="test")
        assert config.checkpoint_prefix == "test"
        assert config.worktree is False
        assert config.labels.on_failure is None

    def test_full_config(self) -> None:
        """Test full workflow config."""
        from dag_executor.schema import LabelsConfig
        config = WorkflowConfig(
            checkpoint_prefix="test-wf",
            worktree=True,
            labels=LabelsConfig(on_failure="failed")
        )
        assert config.checkpoint_prefix == "test-wf"
        assert config.worktree is True
        assert config.labels.on_failure == "failed"


class TestWorkflowDef:
    """Test WorkflowDef model."""
    
    def test_minimal_workflow(self) -> None:
        """Test minimal workflow definition."""
        workflow = WorkflowDef(
            name="Test Workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="bash",
                    script="echo test"
                )
            ]
        )
        assert workflow.name == "Test Workflow"
        assert len(workflow.nodes) == 1
        assert workflow.inputs == {}
        assert workflow.outputs == {}
    
    def test_workflow_with_inputs(self) -> None:
        """Test workflow with input definitions."""
        workflow = WorkflowDef(
            name="Test Workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            inputs={
                "user_id": InputDef(type="string", required=True),
                "dry_run": InputDef(type="boolean", required=False, default=False)
            },
            nodes=[
                NodeDef(id="node1", name="Test", type="bash", script="echo test")
            ]
        )
        assert len(workflow.inputs) == 2
        assert workflow.inputs["user_id"].required is True
        assert workflow.inputs["dry_run"].default is False
    
    def test_workflow_with_outputs(self) -> None:
        """Test workflow with output definitions."""
        workflow = WorkflowDef(
            name="Test Workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(id="node1", name="Test", type="bash", script="echo test")
            ],
            outputs={
                "result": OutputDef(node="node1")
            }
        )
        assert len(workflow.outputs) == 1
        assert workflow.outputs["result"].node == "node1"
    
    def test_empty_nodes_rejected(self) -> None:
        """Test that workflows with empty nodes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WorkflowDef(
                name="Empty Workflow",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[]
            )
        error_str = str(exc_info.value).lower()
        assert "nodes" in error_str or "at least" in error_str or "empty" in error_str
