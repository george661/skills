"""Pydantic v2 models for DAG executor workflow definitions."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from pydantic.functional_validators import BeforeValidator
from typing_extensions import Annotated


class NodeStatus(str, Enum):
    """Execution status of a workflow node."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


class WorkflowStatus(str, Enum):
    """Overall execution status of a workflow."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class NodeResult(BaseModel):
    """Result of a node execution."""
    status: NodeStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Node(BaseModel):
    """A single node in a workflow DAG."""
    id: str = Field(..., description="Unique node identifier")
    name: str = Field(..., description="Human-readable node name")
    runner: str = Field(..., description="Runner type (e.g., 'bash', 'python', 'http')")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Node input parameters")
    depends_on: List[str] = Field(default_factory=list, description="List of node IDs this node depends on")
    status: NodeStatus = Field(default=NodeStatus.PENDING, description="Current execution status")
    result: Optional[NodeResult] = Field(default=None, description="Execution result when completed")


class Workflow(BaseModel):
    """A complete workflow definition with nodes and execution state."""
    id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Human-readable workflow name")
    nodes: List[Node] = Field(..., description="List of nodes in the workflow")
    status: WorkflowStatus = Field(default=WorkflowStatus.PENDING, description="Overall workflow status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional workflow metadata")

# ============================================================================
# Workflow Definition Models (for YAML parsing)
# ============================================================================

class TriggerRule(str, Enum):
    """Defines when a node should execute based on upstream results."""
    ALL_SUCCESS = "all_success"  # All dependencies must succeed
    ONE_SUCCESS = "one_success"  # At least one dependency must succeed
    ALL_DONE = "all_done"  # All dependencies must complete (success or fail)


class ModelTier(str, Enum):
    """LLM model tier for prompt nodes."""
    OPUS = "opus"
    SONNET = "sonnet"
    LOCAL = "local"


class DispatchMode(str, Enum):
    """Execution dispatch mode for nodes."""
    INLINE = "inline"  # Execute in current process
    LOCAL = "local"  # Execute in separate local process


class OnFailure(str, Enum):
    """Action to take when a node fails."""
    STOP = "stop"  # Stop workflow execution
    CONTINUE = "continue"  # Continue workflow, mark node as failed
    SKIP_DOWNSTREAM = "skip_downstream"  # Skip nodes that depend on this one


class OutputFormat(str, Enum):
    """Output format for node results."""
    JSON = "json"
    TEXT = "text"
    YAML = "yaml"


class ReducerStrategy(str, Enum):
    """Strategy for merging outputs from multiple nodes into workflow state."""
    OVERWRITE = "overwrite"  # Replace current with new (default)
    APPEND = "append"  # Append to list
    EXTEND = "extend"  # Extend list with list
    MAX = "max"  # Take maximum value
    MIN = "min"  # Take minimum value
    MERGE_DICT = "merge_dict"  # Merge dict values
    CUSTOM = "custom"  # Use custom function


class RetryConfig(BaseModel):
    """Configuration for node retry behavior."""
    model_config = {"extra": "forbid"}

    max_attempts: int = Field(..., gt=0, description="Maximum retry attempts (must be > 0)")
    delay_ms: int = Field(default=0, ge=0, description="Delay between retries in milliseconds")
    retry_on: Optional[List[str]] = Field(
        default=None,
        description="List of error patterns to retry on (substring match). If None, retry all failures."
    )


class ReducerDef(BaseModel):
    """State reducer definition for merging outputs from multiple nodes.

    The dict key in WorkflowDef.state is the state key name.
    This model only defines the merge strategy and optional custom function.
    """
    model_config = {"extra": "forbid"}

    strategy: ReducerStrategy = Field(..., description="Reducer strategy to use")
    function: Optional[str] = Field(
        default=None,
        description="Dotted path to custom reducer function (required for strategy=custom)"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate strategy-function requirements."""
        if self.strategy == ReducerStrategy.CUSTOM and self.function is None:
            raise ValueError("function field is required when strategy=custom")
        if self.strategy != ReducerStrategy.CUSTOM and self.function is not None:
            raise ValueError("function field is only allowed when strategy=custom")


class ChannelFieldDef(BaseModel):
    """Channel field definition with type hint, optional reducer, and optional default.

    This model unifies type information with reducer configuration for state channels.
    Supports bare string reducer shorthand (e.g., reducer: "append") via field_validator.
    """
    model_config = {"extra": "forbid"}

    type: str = Field(..., description="Channel type (e.g., list, float, dict, string)")
    reducer: Optional[ReducerDef] = Field(
        default=None,
        description="Reducer for merging values. None = LastValueChannel (conflict on parallel write)"
    )
    default: Optional[Any] = Field(
        default=None,
        description="Default value to write to channel after creation"
    )

    @field_validator("reducer", mode="before")
    @classmethod
    def _convert_bare_string_reducer(cls, v: Any) -> Any:
        """Accept bare string like 'append' and convert to ReducerDef(strategy='append')."""
        if isinstance(v, str):
            return {"strategy": v}
        return v


def _state_field_discriminator(v: Any) -> str:
    """Discriminator for StateFieldDef union type.

    Returns 'channel' for ChannelFieldDef (has 'type' key), 'reducer' for ReducerDef.
    """
    if isinstance(v, dict):
        if "type" in v:
            return "channel"
        return "reducer"
    if isinstance(v, ChannelFieldDef):
        return "channel"
    return "reducer"


# Union type for state field definitions (backwards compatible)
StateFieldDef = Annotated[
    Union[ChannelFieldDef, ReducerDef],
    BeforeValidator(_state_field_discriminator)
]


class InputDef(BaseModel):
    """Workflow input parameter definition."""
    model_config = {"extra": "forbid"}
    
    type: str = Field(..., description="Input type (string, boolean, number, etc.)")
    required: bool = Field(..., description="Whether this input is required")
    default: Optional[Any] = Field(default=None, description="Default value if not provided")
    pattern: Optional[str] = Field(default=None, description="Regex pattern for validation")


class OutputDef(BaseModel):
    """Workflow output definition."""
    model_config = {"extra": "forbid"}
    
    node: str = Field(..., description="Source node ID for this output")
    field: Optional[str] = Field(default=None, description="Specific field to extract from node output")


# Node type-specific configuration models

class SkillNodeConfig(BaseModel):
    """Configuration for skill execution nodes."""
    model_config = {"extra": "forbid"}
    
    skill: str = Field(..., description="Path to skill file")
    params: Dict[str, Any] = Field(default_factory=dict, description="Skill parameters")


class CommandNodeConfig(BaseModel):
    """Configuration for command execution nodes."""
    model_config = {"extra": "forbid"}
    
    command: str = Field(..., description="Command name to execute")
    args: List[Any] = Field(default_factory=list, description="Command arguments")


class PromptNodeConfig(BaseModel):
    """Configuration for LLM prompt nodes."""
    model_config = {"extra": "forbid"}
    
    prompt: Optional[str] = Field(default=None, description="Direct prompt text")
    prompt_file: Optional[str] = Field(default=None, description="Path to prompt file")
    model: ModelTier = Field(..., description="LLM model tier to use")
    
    def model_post_init(self, __context: Any) -> None:
        """Validate prompt/prompt_file mutual exclusivity."""
        if self.prompt is not None and self.prompt_file is not None:
            raise ValueError("prompt and prompt_file are mutually exclusive")
        if self.prompt is None and self.prompt_file is None:
            raise ValueError("Either prompt or prompt_file must be provided")


class BashNodeConfig(BaseModel):
    """Configuration for bash script nodes."""
    model_config = {"extra": "forbid"}
    
    script: str = Field(..., description="Bash script to execute")


class GateNodeConfig(BaseModel):
    """Configuration for gate/condition nodes."""
    model_config = {"extra": "forbid"}

    condition: str = Field(..., description="Condition expression to evaluate")


class InterruptConfig(BaseModel):
    """Configuration for interrupt nodes (human-in-the-loop)."""
    model_config = {"extra": "forbid"}

    message: str = Field(..., description="Message to display to the user")
    resume_key: str = Field(..., description="Key to inject resume value into workflow inputs")
    channels: List[str] = Field(default=["terminal"], description="Channels to surface interrupt on")
    timeout: Optional[int] = Field(default=None, description="Optional timeout in seconds")


class EdgeDef(BaseModel):
    """Conditional edge definition for dynamic routing.

    Supports both single-target and multi-target (fan-out) edges:
    - Single: EdgeDef(target="b", condition=...)
    - Multi: EdgeDef(targets=["b", "c"], condition=...)

    NOTE: simpleeval condition expressions use Python syntax, not JSON.
    - Python: True, False, None
    - JSON: true, false, null
    When comparing boolean outputs from JSON-producing nodes, use Python booleans:
      ✓ Correct: "node.field == True"
      ✗ Wrong:   "node.field == true"  (NameError: name 'true' is not defined)
    """
    model_config = {"extra": "forbid"}

    target: Optional[str] = Field(default=None, description="Target node ID (single-target)")
    targets: Optional[List[str]] = Field(default=None, description="Target node IDs (multi-target fan-out)")
    condition: Optional[str] = Field(default=None, description="simpleeval condition expression (Python syntax, not JSON)")
    default: bool = Field(default=False, description="Default fallback edge")

    def model_post_init(self, __context: Any) -> None:
        """Validate edge constraints."""
        # Exactly one of target or targets must be set
        if self.target is None and self.targets is None:
            raise ValueError("Either target or targets must be specified")
        if self.target is not None and self.targets is not None:
            raise ValueError("target and targets are mutually exclusive")

        # Validate multi-target list
        if self.targets is not None:
            if len(self.targets) == 0:
                raise ValueError("targets list cannot be empty")
            if len(self.targets) != len(set(self.targets)):
                raise ValueError("targets list contains duplicate IDs")

        # Validate condition-default mutual exclusivity
        if self.condition is not None and self.default is True:
            raise ValueError("condition and default are mutually exclusive")
        if self.condition is None and self.default is False:
            raise ValueError("Edge must have either condition or default=True")


class NodeDef(BaseModel):
    """Node definition for workflow YAML."""
    model_config = {"extra": "forbid"}
    
    # Core fields
    id: str = Field(..., description="Unique node identifier")
    name: str = Field(..., description="Human-readable node name")
    type: str = Field(..., description="Node type (skill, command, prompt, bash, gate)")
    
    # Common optional fields
    depends_on: List[str] = Field(default_factory=list, description="Node IDs this depends on")
    when: Optional[str] = Field(default=None, description="Conditional execution expression")
    trigger_rule: TriggerRule = Field(default=TriggerRule.ALL_SUCCESS, description="Trigger rule")
    dispatch: Optional[DispatchMode] = Field(default=None, description="Dispatch mode")
    label: Optional[str] = Field(default=None, description="Label for grouping/filtering")
    checkpoint: Optional[bool] = Field(default=None, description="Enable checkpointing")
    retry: Optional[RetryConfig] = Field(default=None, description="Retry configuration")
    on_failure: OnFailure = Field(default=OnFailure.STOP, description="Failure handling")
    timeout: Optional[int] = Field(default=None, description="Timeout in seconds")
    output_format: Optional[OutputFormat] = Field(default=None, description="Output format")
    read_state: Optional[List[str]] = Field(default=None, description="State keys this node reads (None = full state)")

    # Channel subscriptions
    reads: Optional[List[str]] = Field(default=None, description="Channel keys this node reads (None = infer from depends_on)")
    writes: Optional[List[str]] = Field(default=None, description="Channel keys this node writes (None = infer from outputs)")

    # Node type-specific fields (flattened for YAML simplicity)
    # Skill node
    skill: Optional[str] = Field(default=None, description="Skill path (for type=skill)")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Skill params (for type=skill)")
    
    # Command node
    command: Optional[str] = Field(default=None, description="Command name (for type=command)")
    args: Optional[List[Any]] = Field(default=None, description="Command args (for type=command)")
    inputs_map: Optional[Dict[str, str]] = Field(default=None, description="Named input mappings (for type=command)")

    # Prompt node
    prompt: Optional[str] = Field(default=None, description="Prompt text (for type=prompt)")
    prompt_file: Optional[str] = Field(default=None, description="Prompt file (for type=prompt)")
    model: Optional[ModelTier] = Field(default=None, description="Model tier (for type=prompt)")
    strict_model: bool = Field(default=False, description="Block model_override (for type=prompt)")
    
    # Bash node
    script: Optional[str] = Field(default=None, description="Bash script (for type=bash)")
    
    # Gate node
    condition: Optional[str] = Field(default=None, description="Gate condition (for type=gate) or interrupt condition (for type=interrupt)")

    # Interrupt node
    message: Optional[str] = Field(default=None, description="Interrupt message (for type=interrupt)")
    resume_key: Optional[str] = Field(default=None, description="Resume key (for type=interrupt)")
    channels: Optional[List[str]] = Field(default=None, description="Interrupt channels (for type=interrupt)")
    # timeout already defined above in common fields

    # Conditional edges
    edges: Optional[List["EdgeDef"]] = Field(default=None, description="Conditional edges for dynamic routing")

    def model_post_init(self, __context: Any) -> None:
        """Validate type-specific required fields."""
        if self.type == "skill":
            if self.skill is None:
                raise ValueError("skill field is required for type=skill")
        elif self.type == "command":
            if self.command is None:
                raise ValueError("command field is required for type=command")
        elif self.type == "prompt":
            if self.prompt is None and self.prompt_file is None:
                raise ValueError("Either prompt or prompt_file is required for type=prompt")
            if self.prompt is not None and self.prompt_file is not None:
                raise ValueError("prompt and prompt_file are mutually exclusive for type=prompt")
            # model is optional — can be set at workflow level via default_model
        elif self.type == "bash":
            if self.script is None:
                raise ValueError("script field is required for type=bash")
        elif self.type == "gate":
            if self.condition is None:
                raise ValueError("condition field is required for type=gate")
        elif self.type == "interrupt":
            if self.message is None:
                raise ValueError("message field is required for type=interrupt")
            if self.resume_key is None:
                raise ValueError("resume_key field is required for type=interrupt")

        # Validate edges if present
        if self.edges is not None:
            default_count = sum(1 for edge in self.edges if edge.default)
            if default_count != 1:
                raise ValueError("Exactly one edge must have default=True")


class LabelsConfig(BaseModel):
    """Label lifecycle configuration for workflow execution."""
    model_config = {"extra": "forbid"}

    on_failure: Optional[str] = Field(default=None, description="Label to apply when workflow fails")


class ExitHookDef(BaseModel):
    """Definition for a workflow exit hook — runs on completion or failure.

    Inspired by Argo Workflows' exit hooks: guaranteed cleanup actions
    that execute regardless of workflow outcome.

    Example YAML:
        config:
          on_exit:
            - id: cleanup_worktree
              type: bash
              script: "git worktree remove ..."
              run_on: [completed, failed]
            - id: reset_labels
              type: bash
              script: "..."
              run_on: [failed]
    """
    model_config = {"extra": "forbid"}

    id: str = Field(..., description="Unique exit hook identifier")
    name: Optional[str] = Field(default=None, description="Human-readable name")
    type: str = Field(..., description="Runner type (bash, skill)")
    script: Optional[str] = Field(default=None, description="Bash script (for type=bash)")
    skill: Optional[str] = Field(default=None, description="Skill path (for type=skill)")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Skill params")
    run_on: List[str] = Field(
        default_factory=lambda: ["completed", "failed"],
        description="Workflow statuses that trigger this hook (completed, failed, paused)"
    )
    timeout: int = Field(default=60, description="Timeout in seconds")

    @model_validator(mode="after")
    def validate_exit_hook(self) -> "ExitHookDef":
        """Validate exit hook configuration."""
        # Validate type field
        if self.type not in ("bash", "skill"):
            raise ValueError(f"type must be 'bash' or 'skill', got '{self.type}'")

        # Validate run_on values
        valid_statuses = {"completed", "failed", "paused"}
        for status in self.run_on:
            if status not in valid_statuses:
                raise ValueError(
                    f"run_on values must be one of {valid_statuses}, got '{status}'"
                )
        return self


class SlackNotificationConfig(BaseModel):
    """Slack notification configuration."""
    model_config = {"extra": "forbid"}

    events: List[str] = Field(
        default=["gate_pending", "workflow_failed", "workflow_completed"],
        description="List of event names that trigger notifications"
    )
    channel: Optional[str] = Field(
        default=None,
        description="Slack channel ID (used with bot_token_env)"
    )
    webhook_url_env: Optional[str] = Field(
        default=None,
        description="Environment variable name containing webhook URL"
    )
    bot_token_env: Optional[str] = Field(
        default=None,
        description="Environment variable name containing bot token"
    )

    @model_validator(mode='after')
    def validate_slack_config(self) -> "SlackNotificationConfig":
        """Validate Slack configuration."""
        # Validate event names
        valid_events = {
            "gate_pending",
            "workflow_failed",
            "workflow_completed",
            "workflow_started",
            "node_failed",
            "node_completed"
        }
        for event in self.events:
            if event not in valid_events:
                raise ValueError(
                    f"Unknown event name '{event}'. Valid options: {', '.join(sorted(valid_events))}"
                )

        # Validate exactly one transport mechanism
        has_webhook = self.webhook_url_env is not None
        has_bot_token = self.bot_token_env is not None

        if not has_webhook and not has_bot_token:
            raise ValueError("Either webhook_url_env or bot_token_env must be specified")
        if has_webhook and has_bot_token:
            raise ValueError("Cannot specify both webhook_url_env and bot_token_env")

        return self


class NotificationsConfig(BaseModel):
    """Workflow notification configuration."""
    model_config = {"extra": "forbid"}

    slack: Optional[SlackNotificationConfig] = Field(
        default=None,
        description="Slack notification configuration"
    )


class WorkflowConfig(BaseModel):
    """Workflow-level configuration."""
    model_config = {"extra": "forbid"}

    checkpoint_prefix: str = Field(..., description="Prefix for checkpoint files")
    worktree: bool = Field(default=False, description="Use worktree isolation")
    labels: LabelsConfig = Field(default_factory=LabelsConfig, description="Label lifecycle configuration")
    on_exit: List[ExitHookDef] = Field(
        default_factory=list,
        description="Exit hooks — guaranteed cleanup actions on workflow completion or failure"
    )
    notifications: Optional[NotificationsConfig] = Field(
        default=None,
        description="Notification configuration"
    )


class WorkflowDef(BaseModel):
    """Complete workflow definition for YAML parsing."""
    model_config = {"extra": "forbid"}

    name: str = Field(..., description="Workflow name")
    config: WorkflowConfig = Field(..., description="Workflow configuration")
    default_model: Optional[ModelTier] = Field(default=None, description="Default model for prompt nodes")
    inputs: Dict[str, InputDef] = Field(default_factory=dict, description="Input definitions")
    nodes: List[NodeDef] = Field(..., min_length=1, description="Workflow nodes (at least one required)")
    outputs: Dict[str, OutputDef] = Field(default_factory=dict, description="Output definitions")
    state: Dict[str, Union[ChannelFieldDef, ReducerDef]] = Field(
        default_factory=dict,
        description="State field definitions (ChannelFieldDef or ReducerDef for backwards compat)"
    )

    # Private attribute to store YAML line numbers (not part of the schema)
    # Avoids memory leak from id()-based dict keys (id() recycles after GC)
    _node_lines: Dict[str, int] = PrivateAttr(default_factory=dict)


# Rebuild models to resolve forward references
NodeDef.model_rebuild()
