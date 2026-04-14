"""Command runner for recursive workflow execution nodes."""
from typing import Any, Dict

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner
from dag_executor.parser import load_workflow

# Maximum recursion depth for command nodes
MAX_RECURSION_DEPTH = 5


def _execute_workflow_stub(workflow_def: Any, inputs: Dict[str, Any]) -> NodeResult:
    """Stub for workflow execution (to be implemented with full executor).
    
    This is a placeholder that will be replaced when execute_workflow is implemented.
    """
    # TODO: Replace with actual execute_workflow call once implemented
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"message": "Workflow execution stub - not yet implemented"}
    )


@register_runner("command")
class CommandRunner(BaseRunner):
    """Runner for command execution nodes.
    
    Loads and executes sub-workflows recursively with depth limiting.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a command node.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and sub-workflow output
        """
        # Check recursion depth
        current_depth = getattr(ctx, "_recursion_depth", 0)
        if current_depth >= MAX_RECURSION_DEPTH:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded"
            )
        
        command = ctx.node_def.command
        assert command is not None, "command field is required (validated by schema)"
        args = ctx.node_def.args or []
        
        # Load sub-workflow
        try:
            workflow_def = load_workflow(command)
        except FileNotFoundError as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Failed to load workflow '{command}': {str(e)}"
            )
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Failed to load workflow '{command}': {str(e)}"
            )
        
        # Build inputs for sub-workflow from args and resolved inputs
        sub_workflow_inputs = {}
        
        # Add args as positional inputs
        for i, arg in enumerate(args):
            sub_workflow_inputs[f"arg{i}"] = arg
        
        # Add resolved inputs
        sub_workflow_inputs.update(ctx.resolved_inputs)
        
        # Execute sub-workflow with incremented depth
        # TODO: When execute_workflow is fully implemented, pass depth via context
        try:
            result = _execute_workflow_stub(workflow_def, sub_workflow_inputs)
            return result
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Sub-workflow execution failed: {str(e)}"
            )
