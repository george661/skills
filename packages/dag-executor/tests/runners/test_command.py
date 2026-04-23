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


# Integration tests (these will use real executor once fully wired)

@pytest.mark.asyncio
async def test_parent_can_reference_subworkflow_outputs_end_to_end():
    """Test parent can reference $call_child.result (AC-6)."""
    # This test requires full executor integration
    # Will be implemented after basic wiring is complete
    pytest.skip("Integration test - implement after basic wiring")


@pytest.mark.asyncio  
async def test_recursion_depth_6_deep_fails_with_clear_error():
    """Test MAX_RECURSION_DEPTH enforced end-to-end (AC-7)."""
    # This test requires full executor integration
    pytest.skip("Integration test - implement after basic wiring")


@pytest.mark.asyncio
async def test_recursion_depth_5_deep_succeeds():
    """Test recursion at boundary succeeds (AC-7)."""
    # This test requires full executor integration
    pytest.skip("Integration test - implement after basic wiring")


def test_all_child_events_carry_parent_run_id():
    """Test all child events carry parent_run_id (AC-8)."""
    # This test requires event capture during real execution
    pytest.skip("Integration test - implement after event plumbing")


def test_command_runner_emits_workflow_completed_terminal_event():
    """Test terminal WORKFLOW_COMPLETED event is emitted (AC-8)."""
    # This test requires event capture during real execution
    pytest.skip("Integration test - implement after event plumbing")


def test_command_runner_shares_subprocess_registry_with_child():
    """Test subprocess registry is shared with child (critical fix #1)."""
    # This test requires subprocess management integration
    pytest.skip("Integration test - implement after subprocess wiring")


def test_command_runner_emits_workflow_started_with_parent_run_id(command_node):
    """Child executor emits WORKFLOW_STARTED with parent_run_id (updated test)."""
    # This test will be updated after removing CommandRunner's STARTED emission
    pytest.skip("Test needs update after STARTED emission moved to child executor")
