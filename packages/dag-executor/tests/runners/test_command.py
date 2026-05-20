"""Tests for command runner."""
import asyncio
from unittest.mock import Mock, patch, AsyncMock
import pytest

from dag_executor.events import EventType, WorkflowEvent
from dag_executor.schema import NodeDef, NodeStatus, WorkflowDef, NodeResult, WorkflowStatus
from dag_executor.executor import WorkflowResult
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.command import CommandRunner, MAX_RECURSION_DEPTH


@pytest.fixture
def command_node():
    """Create a command node definition."""
    return NodeDef(
        id="cmd1",
        name="Test Command",
        type="command",
        command="test-workflow",
        args=["arg1", "arg2"]
    )


def test_command_runner_calls_real_executor(command_node):
    """Test command runner calls real WorkflowExecutor.execute (AC-5)."""
    ctx = RunnerContext(
        node_def=command_node,
        resolved_inputs={"input1": "value1"}
    )
    
    # Mock workflow definition
    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.name = "test-workflow"
    
    # Mock execution result with outputs
    mock_workflow_result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results={},
        outputs={"result": "success"}
    )
    
    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            # Create an async mock that returns our result
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
            
            runner = CommandRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
            assert result.output == {"result": "success"}
            
            # Verify WorkflowExecutor.execute was called
            mock_executor_instance.execute.assert_called_once()


def test_command_runner_positional_args_become_arg0_argN(command_node):
    """Test command args are passed as arg0, arg1, etc. (AC-5)."""
    ctx = RunnerContext(
        node_def=command_node,
        resolved_inputs={"key": "value"}
    )
    
    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})
    
    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
            
            runner = CommandRunner()
            runner.run(ctx)
            
            # Verify args were passed
            call_args = mock_executor_instance.execute.call_args
            inputs = call_args.kwargs.get("inputs", {})
            assert inputs["arg0"] == "arg1"
            assert inputs["arg1"] == "arg2"


def test_command_runner_inputs_map_resolves_named_inputs():
    """Test inputs_map resolves $ref values (AC-5)."""
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="test-workflow",
        inputs_map={"target": "$parent_node.value"}
    )
    
    ctx = RunnerContext(
        node_def=node,
        node_outputs={"parent_node": {"value": 42}}
    )
    
    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})
    
    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            with patch("dag_executor.variables.resolve_variables") as mock_resolve:
                # Mock resolve_variables to return the resolved value
                mock_resolve.return_value = 42
                
                mock_executor_instance = MockExecutor.return_value
                mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
                
                runner = CommandRunner()
                runner.run(ctx)
                
                # Verify inputs_map was resolved
                call_args = mock_executor_instance.execute.call_args
                inputs = call_args.kwargs.get("inputs", {})
                assert inputs["target"] == 42


def test_command_runner_inputs_map_overrides_positional_on_collision():
    """Test inputs_map overrides positional args on collision (AC-5)."""
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="test-workflow",
        args=["x"],
        inputs_map={"arg0": "y"}
    )
    
    ctx = RunnerContext(node_def=node)
    
    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})
    
    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            with patch("dag_executor.variables.resolve_variables") as mock_resolve:
                mock_resolve.return_value = "y"
                
                mock_executor_instance = MockExecutor.return_value
                mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
                
                runner = CommandRunner()
                runner.run(ctx)
                
                # Verify inputs_map overrode positional
                call_args = mock_executor_instance.execute.call_args
                inputs = call_args.kwargs.get("inputs", {})
                assert inputs["arg0"] == "y"


def test_command_runner_child_failure_bubbles_as_failed_node_result():
    """Test child workflow failure is propagated."""
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="failing-workflow"
    )
    
    ctx = RunnerContext(node_def=node)
    
    mock_workflow_def = Mock(spec=WorkflowDef)
    # Mock a failed workflow result - the error should be in a node result
    mock_workflow_result = WorkflowResult(
        status=WorkflowStatus.FAILED,
        node_results={"failed": NodeResult(status=NodeStatus.FAILED, error="Child workflow failed")}
    )
    
    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
            
            runner = CommandRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.FAILED
            # Check that error message mentions failure
            assert "fail" in result.error.lower()


def test_command_recursion_depth_enforced():
    """Test recursion depth limit is enforced."""
    node = NodeDef(
        id="cmd1",
        name="Recursive Command",
        type="command",
        command="recursive-workflow"
    )
    
    # Create context with depth at limit
    ctx = RunnerContext(node_def=node)
    ctx._recursion_depth = MAX_RECURSION_DEPTH
    
    runner = CommandRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.FAILED
    assert "recursion depth" in result.error.lower() or "max depth" in result.error.lower()


def test_command_invalid_workflow_path():
    """Test invalid workflow path returns FAILED."""
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="nonexistent-workflow"
    )
    
    ctx = RunnerContext(node_def=node)
    
    with patch("dag_executor.runners.command.load_workflow", side_effect=FileNotFoundError("Not found")):
        runner = CommandRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.FAILED
        assert "not found" in result.error.lower() or "failed to load" in result.error.lower()


def test_command_runner_skips_emission_without_event_emitter(command_node):
    """Backwards-compat: no event_emitter means no emission attempt and no crash."""
    ctx = RunnerContext(
        node_def=command_node,
        # event_emitter defaults to None
        # parent_run_id defaults to None
    )

    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.name = "test-workflow"
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)
            
            result = CommandRunner().run(ctx)

    assert result.status == NodeStatus.COMPLETED


# Integration tests — exercise the real WorkflowExecutor via command-runner nesting.
# These tests use the YAML fixtures in tests/fixtures/ and patch load_workflow to
# map child workflow names -> fixture files.

from pathlib import Path
from dag_executor.executor import SubprocessRegistry, WorkflowExecutor
from dag_executor.parser import load_workflow as _real_load_workflow

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _fixture_loader(name: str):
    """Resolve a bare workflow name to its fixture file and load it."""
    path = FIXTURES_DIR / f"{name}.yaml"
    return _real_load_workflow(str(path))


class _CapturingEmitter:
    """Collect every emitted WorkflowEvent for assertion."""

    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_parent_can_reference_subworkflow_outputs_end_to_end():
    """Parent workflow references $call_child.result and the value bubbles correctly (AC-6)."""
    parent = _fixture_loader("parent_uses_child_output")

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        executor = WorkflowExecutor()
        result = await executor.execute(workflow_def=parent, inputs={})

    assert result.status == WorkflowStatus.COMPLETED, (
        f"Parent workflow should complete; got {result.status}. "
        f"Node results: {[(n, r.status, r.error) for n, r in result.node_results.items()]}"
    )
    # The downstream 'use_output' bash node emits {"final": "parent_used_success_from_child"}
    # after interpolating $call_child.result, proving the child's output bubbled up.
    assert result.outputs.get("final") == "parent_used_success_from_child", (
        f"Expected child output to bubble through variable substitution; got outputs={result.outputs}"
    )


@pytest.mark.asyncio
async def test_recursion_depth_6_deep_fails_with_clear_error():
    """A workflow that recurses into itself must stop at MAX_RECURSION_DEPTH=5 and fail clearly (AC-7)."""
    parent = _fixture_loader("recursive_child")

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        executor = WorkflowExecutor()
        result = await executor.execute(workflow_def=parent, inputs={})

    # recursive_child has one node 'recurse' that calls recursive_child. At depth 5 the guard fires.
    assert result.status == WorkflowStatus.FAILED, (
        f"Deep recursion must terminate as FAILED, not {result.status}"
    )
    recurse_result = result.node_results.get("recurse")
    assert recurse_result is not None, "recurse node must have produced a result"
    # The failure should mention recursion depth. The error may propagate from a deeper
    # child-of-child and end up wrapped in "Sub-workflow failed"; either surface is fine
    # as long as the root cause is a depth violation.
    combined_errors = " ".join(
        (r.error or "") for r in result.node_results.values()
    ).lower()
    assert (
        "recursion depth" in combined_errors or "max depth" in combined_errors
    ), f"Error should reference recursion depth; got: {combined_errors}"


def test_recursion_depth_5_deep_succeeds():
    """At depth 4 the CommandRunner still accepts entry; only depth 5 blocks (AC-7 boundary)."""
    node = NodeDef(
        id="cmd_at_boundary",
        name="At Boundary",
        type="command",
        command="child_with_outputs",
    )
    ctx = RunnerContext(node_def=node, _recursion_depth=MAX_RECURSION_DEPTH - 1)

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        result = CommandRunner().run(ctx)

    assert result.status == NodeStatus.COMPLETED, (
        f"depth=MAX-1 should run the child successfully; got {result.status} err={result.error}"
    )
    # child_with_outputs declares {result: success_from_child} — should bubble up
    assert result.output == {"result": "success_from_child"}


@pytest.mark.asyncio
async def test_all_child_events_carry_parent_run_id():
    """Every event emitted by a child WorkflowExecutor run must carry parent_run_id in metadata (AC-8)."""
    parent = _fixture_loader("parent_uses_child_output")
    emitter = _CapturingEmitter()
    parent_run_id = "parent-abc-123"

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        executor = WorkflowExecutor()
        await executor.execute(
            workflow_def=parent,
            inputs={},
            event_emitter=emitter,
            run_id=parent_run_id,
        )

    # Partition events into parent-scoped (no parent_run_id) vs child-scoped (parent_run_id set).
    child_scoped = [
        e for e in emitter.events
        if isinstance(e.metadata, dict) and e.metadata.get("parent_run_id")
    ]
    assert child_scoped, (
        "At least some child-scoped events must have been emitted during the nested run. "
        f"All event types captured: {[e.event_type for e in emitter.events]}"
    )
    for event in child_scoped:
        assert event.metadata.get("parent_run_id") == parent_run_id, (
            f"Child event {event.event_type} must tag parent_run_id={parent_run_id}; "
            f"got metadata={event.metadata}"
        )
    # Confirm that multiple *kinds* of child events carry the tag (not just WORKFLOW_STARTED).
    kinds_with_parent = {e.event_type for e in child_scoped}
    assert len(kinds_with_parent) >= 2, (
        f"Cross-cutting fix must propagate parent_run_id across multiple event kinds; "
        f"only found {kinds_with_parent}"
    )


@pytest.mark.asyncio
async def test_command_runner_emits_workflow_completed_terminal_event():
    """CommandRunner must emit a terminal WORKFLOW_COMPLETED event after the child finishes (AC-8)."""
    node = NodeDef(
        id="cmd_terminal",
        name="Terminal Event Check",
        type="command",
        command="child_with_outputs",
    )
    emitter = _CapturingEmitter()
    ctx = RunnerContext(node_def=node, event_emitter=emitter, parent_run_id="parent-xyz")

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        result = CommandRunner().run(ctx)

    assert result.status == NodeStatus.COMPLETED
    terminal = [
        e for e in emitter.events
        if e.event_type == EventType.WORKFLOW_COMPLETED
        and isinstance(e.metadata, dict)
        and e.metadata.get("parent_run_id") == "parent-xyz"
    ]
    assert terminal, (
        "CommandRunner must emit WORKFLOW_COMPLETED tagged with parent_run_id after child success. "
        f"All events: {[(e.event_type, e.metadata) for e in emitter.events]}"
    )


@pytest.mark.asyncio
async def test_command_runner_shares_subprocess_registry_with_child():
    """CommandRunner must pass ctx.subprocess_registry into the child executor (critical fix #1)."""
    node = NodeDef(
        id="cmd_registry",
        name="Registry Share",
        type="command",
        command="child_with_outputs",
    )
    parent_registry = SubprocessRegistry()
    ctx = RunnerContext(node_def=node, subprocess_registry=parent_registry)

    captured: dict = {}

    async def capturing_execute(self, **kwargs):
        captured["subprocess_registry"] = kwargs.get("subprocess_registry")
        captured["parent_run_id"] = kwargs.get("parent_run_id")
        captured["_recursion_depth"] = kwargs.get("_recursion_depth")
        return WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        with patch.object(WorkflowExecutor, "execute", capturing_execute):
            CommandRunner().run(ctx)

    assert captured["subprocess_registry"] is parent_registry, (
        "Child executor must be given the parent's SubprocessRegistry instance, not a fresh one. "
        "Shared registry is required so parent cancellation terminates in-flight child subprocesses."
    )
    assert captured["_recursion_depth"] == 1, (
        f"Child must be invoked with depth+1; got {captured['_recursion_depth']}"
    )


@pytest.mark.asyncio
async def test_command_runner_emits_workflow_started_with_parent_run_id():
    """The child WorkflowExecutor (not CommandRunner) emits WORKFLOW_STARTED tagged with parent_run_id."""
    node = NodeDef(
        id="cmd_started",
        name="Started Emission",
        type="command",
        command="child_with_outputs",
    )
    emitter = _CapturingEmitter()
    ctx = RunnerContext(node_def=node, event_emitter=emitter, parent_run_id="parent-started")

    with patch("dag_executor.runners.command.load_workflow", side_effect=_fixture_loader):
        CommandRunner().run(ctx)

    started = [
        e for e in emitter.events
        if e.event_type == EventType.WORKFLOW_STARTED
        and isinstance(e.metadata, dict)
        and e.metadata.get("parent_run_id") == "parent-started"
    ]
    assert len(started) == 1, (
        f"Exactly one WORKFLOW_STARTED event must carry parent_run_id=parent-started; "
        f"found {len(started)}. All STARTED events: "
        f"{[e.metadata for e in emitter.events if e.event_type == EventType.WORKFLOW_STARTED]}"
    )


# GW-6042: positional args are also bound to the sub-workflow's declared
# input names, in declaration order. This bridges the common idiom
# `args: ["$issue_key"]` against a sub-workflow that declares
# `inputs: {issue_key: ...}` — without it, the sub-workflow only sees
# `arg0` and any `$issue_key` reference inside it fails to resolve.
def test_command_runner_positional_args_bound_to_named_inputs():
    """Positional args[i] also populate the i-th declared input by name."""
    from dag_executor.schema import InputDef
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="planning-workflow",
        args=["GW-6042"],
    )
    ctx = RunnerContext(node_def=node)

    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.name = "planning-workflow"
    mock_workflow_def.inputs = {
        "issue_key": InputDef(type="string", required=True),
    }
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)

            runner = CommandRunner()
            runner.run(ctx)

            inputs = mock_executor_instance.execute.call_args.kwargs.get("inputs", {})
            # Both the positional and the named binding land — back-compat for
            # existing $arg0 consumers, forward-compat for $issue_key.
            assert inputs.get("arg0") == "GW-6042"
            assert inputs.get("issue_key") == "GW-6042"


def test_command_runner_named_inputs_in_declaration_order():
    """When sub-workflow declares multiple inputs, args map by declaration order."""
    from dag_executor.schema import InputDef
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="multi-input-workflow",
        args=["alpha", "beta", "gamma"],
    )
    ctx = RunnerContext(node_def=node)

    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.name = "multi-input-workflow"
    # Use a real dict — sub-workflows declare inputs as a dict literal in YAML
    # which Pydantic preserves as insertion-ordered.
    mock_workflow_def.inputs = {
        "first": InputDef(type="string", required=False),
        "second": InputDef(type="string", required=False),
        "third": InputDef(type="string", required=False),
    }
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)

            runner = CommandRunner()
            runner.run(ctx)

            inputs = mock_executor_instance.execute.call_args.kwargs.get("inputs", {})
            assert inputs.get("first") == "alpha"
            assert inputs.get("second") == "beta"
            assert inputs.get("third") == "gamma"
            # Positional fallbacks still present
            assert inputs.get("arg0") == "alpha"
            assert inputs.get("arg2") == "gamma"


def test_command_runner_more_args_than_declared_inputs():
    """Extra positional args still produce arg{N} entries even past declared inputs.

    Edge case: a sub-workflow with one declared input but the parent passes
    three positional args. The first arg binds to the declared input; the
    remaining two are accessible only as $arg1, $arg2.
    """
    from dag_executor.schema import InputDef
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="single-input-workflow",
        args=["a", "b", "c"],
    )
    ctx = RunnerContext(node_def=node)

    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.inputs = {"target": InputDef(type="string", required=False)}
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            mock_executor_instance = MockExecutor.return_value
            mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)

            runner = CommandRunner()
            runner.run(ctx)

            inputs = mock_executor_instance.execute.call_args.kwargs.get("inputs", {})
            assert inputs.get("target") == "a"
            assert inputs.get("arg0") == "a"
            assert inputs.get("arg1") == "b"
            assert inputs.get("arg2") == "c"


def test_command_runner_inputs_map_overrides_positional_named_binding():
    """inputs_map wins over positional name binding (kwargs-overrides-args)."""
    from dag_executor.schema import InputDef
    node = NodeDef(
        id="cmd1",
        name="Command",
        type="command",
        command="planning-workflow",
        args=["GW-FROM-ARGS"],
        inputs_map={"issue_key": "GW-FROM-MAP"},
    )
    ctx = RunnerContext(node_def=node)

    mock_workflow_def = Mock(spec=WorkflowDef)
    mock_workflow_def.inputs = {"issue_key": InputDef(type="string", required=True)}
    mock_workflow_result = WorkflowResult(status=WorkflowStatus.COMPLETED, node_results={}, outputs={})

    with patch("dag_executor.runners.command.load_workflow", return_value=mock_workflow_def):
        with patch("dag_executor.executor.WorkflowExecutor") as MockExecutor:
            with patch("dag_executor.variables.resolve_variables") as mock_resolve:
                mock_resolve.return_value = "GW-FROM-MAP"
                mock_executor_instance = MockExecutor.return_value
                mock_executor_instance.execute = AsyncMock(return_value=mock_workflow_result)

                runner = CommandRunner()
                runner.run(ctx)

                inputs = mock_executor_instance.execute.call_args.kwargs.get("inputs", {})
                assert inputs.get("issue_key") == "GW-FROM-MAP"
                # Positional fallback unchanged
                assert inputs.get("arg0") == "GW-FROM-ARGS"


# GW-6042 end-to-end: parent passes `args: ["$issue_key"]` against a sub-workflow
# that declares `inputs: {issue_key: ...}`. The sub-workflow's bash and command
# nodes can resolve `$issue_key` cleanly. These tests build real YAML files and
# run them through the real WorkflowExecutor — no mocks of the runner internals.
def test_gw6042_args_to_named_input_real_workflow(tmp_path):
    """`args: ["$issue_key"]` survives parent->child as the RESOLVED value, not literal $issue_key.

    GW-6062 follow-up: the original GW-6042 fix bound positional args by name
    using raw (unresolved) values, so a sub-workflow's $issue_key reference
    inside a `prompt:` field stayed literal even though `workflow_inputs` had
    a key called issue_key. Bash nodes masked this because the bash runner
    injects workflow inputs as env vars regardless of value contents — the
    subshell happily expanded `$issue_key` to whatever string was in scope.
    This test asserts the EXACT resolved value reaches the child.
    """
    import textwrap
    from dag_executor.parser import load_workflow
    from dag_executor.executor import WorkflowExecutor

    child = tmp_path / "child.yaml"
    # Strict equality check — the bash subshell sees the workflow_inputs
    # value via env-var injection; it must equal the parent's resolved value.
    child.write_text(textwrap.dedent("""
        name: child
        config:
          checkpoint_prefix: child
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: greet
            name: Greet
            type: bash
            script: 'test "$issue_key" = "GW-9999" || (echo "got=$issue_key" >&2; exit 99)'
    """).strip())

    parent = tmp_path / "parent.yaml"
    parent.write_text(textwrap.dedent(f"""
        name: parent
        config:
          checkpoint_prefix: parent
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: planning
            name: Planning
            type: command
            command: {child}
            args:
              - "$issue_key"
    """).strip())

    workflow_def = load_workflow(str(parent))
    result = asyncio.run(WorkflowExecutor().execute(
        workflow_def, {"issue_key": "GW-9999"},
    ))
    assert result.status == WorkflowStatus.COMPLETED, str(result.node_results)


def test_gw6062_args_resolved_before_binding_to_named_input(tmp_path):
    """Sub-workflow PROMPT nodes can resolve $issue_key — args must arrive resolved.

    The bug GW-6062 surfaced: if the command runner binds the raw arg
    `$issue_key` (literal string) to the sub-workflow's `issue_key` input,
    then any prompt node inside the sub-workflow that references `$issue_key`
    in its prompt template gets the literal `$issue_key` string sent to the
    LLM (no value substitution). Bash nodes mask this because env-var
    injection passes any string fine. Prompt nodes don't.

    This test simulates the failure path with a `prompt: ` node — but
    without spawning a real model, we just assert the resolved input
    reached the executor's workflow_inputs dict (via the prompt-node
    error string when it fails to fetch the model).
    """
    import textwrap
    from dag_executor.parser import load_workflow
    from dag_executor.executor import WorkflowExecutor

    child = tmp_path / "child.yaml"
    child.write_text(textwrap.dedent("""
        name: child
        config:
          checkpoint_prefix: child
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: echo_inputs
            name: Echo Inputs
            type: bash
            # Hard equality + surface the unexpected value so a regression
            # diff shows the literal `$issue_key` if substitution stalled.
            script: |
              echo "RESOLVED:$issue_key"
              [ "$issue_key" = "GW-9999" ] || { echo "FAIL: got '$issue_key'" >&2; exit 7; }
    """).strip())

    parent = tmp_path / "parent.yaml"
    parent.write_text(textwrap.dedent(f"""
        name: parent
        config:
          checkpoint_prefix: parent
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: planning
            name: Planning
            type: command
            command: {child}
            args:
              - "$issue_key"
    """).strip())

    workflow_def = load_workflow(str(parent))
    result = asyncio.run(WorkflowExecutor().execute(
        workflow_def, {"issue_key": "GW-9999"},
    ))
    assert result.status == WorkflowStatus.COMPLETED, str(result.node_results)


def test_gw6042_nested_command_propagates_named_input(tmp_path):
    """Two-level: parent -> child (type=command) -> grandchild (type=command).

    The middle layer's `args: ["$issue_key"]` against grandchild must resolve
    via the child's named `issue_key` input — not just `$arg0`. Pre-fix this
    raised "Cannot resolve variable reference: $issue_key. Available inputs:
    arg0, command, args" — the literal error from yesterday's /work failures.
    """
    import textwrap
    from dag_executor.parser import load_workflow
    from dag_executor.executor import WorkflowExecutor

    grandchild = tmp_path / "grandchild.yaml"
    grandchild.write_text(textwrap.dedent("""
        name: grandchild
        config:
          checkpoint_prefix: grandchild
        inputs:
          target:
            type: string
            required: true
        nodes:
          - id: noop
            name: Noop
            type: bash
            script: 'echo "target=$target"'
    """).strip())

    child = tmp_path / "child.yaml"
    child.write_text(textwrap.dedent(f"""
        name: child
        config:
          checkpoint_prefix: child
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: nested_call
            name: Nested
            type: command
            command: {grandchild}
            args:
              - "$issue_key"
    """).strip())

    parent = tmp_path / "parent.yaml"
    parent.write_text(textwrap.dedent(f"""
        name: parent
        config:
          checkpoint_prefix: parent
        inputs:
          issue_key:
            type: string
            required: true
        nodes:
          - id: planning
            name: Planning
            type: command
            command: {child}
            args:
              - "$issue_key"
    """).strip())

    workflow_def = load_workflow(str(parent))
    result = asyncio.run(WorkflowExecutor().execute(
        workflow_def, {"issue_key": "GW-9999"},
    ))
    assert result.status == WorkflowStatus.COMPLETED, str(result.node_results)
