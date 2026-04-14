"""Core DAG workflow executor with layer-parallel execution."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from simpleeval import SimpleEval  # type: ignore

from dag_executor.graph import topological_sort_with_layers
from dag_executor.runners import get_runner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import (
    NodeDef, NodeResult, NodeStatus, OnFailure, TriggerRule,
    WorkflowDef, WorkflowStatus
)
from dag_executor.variables import resolve_variables


@dataclass
class ExecutionContext:
    """Tracks execution state across the workflow.
    
    Attributes:
        node_outputs: Map of node_id -> output dict from completed nodes
        node_statuses: Map of node_id -> current NodeStatus
        node_results: Map of node_id -> full NodeResult
        workflow_inputs: Global workflow inputs
        concurrency_limit: Max concurrent node executions
        stopped: Set to True when workflow should halt (on_failure=stop)
        skipped_nodes: Set of node IDs marked for skipping
    """
    node_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    node_statuses: Dict[str, NodeStatus] = field(default_factory=dict)
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    workflow_inputs: Dict[str, Any] = field(default_factory=dict)
    concurrency_limit: int = 10
    stopped: bool = False
    skipped_nodes: Set[str] = field(default_factory=set)


class WorkflowResult:
    """Result of workflow execution.
    
    Uses BaseModel-like structure for consistency with other schema models.
    """
    def __init__(
        self,
        status: WorkflowStatus,
        node_results: Dict[str, NodeResult],
        outputs: Optional[Dict[str, Any]] = None
    ):
        self.status = status
        self.node_results = node_results
        self.outputs = outputs or {}


class WorkflowExecutor:
    """Executes workflow DAGs with layer-parallel node execution."""
    
    DEFAULT_TIMEOUTS = {
        "prompt": 300,
        "command": 300,
        "bash": 60,
        "skill": 60,
        "gate": 30,
    }
    
    async def execute(
        self,
        workflow_def: WorkflowDef,
        inputs: Dict[str, Any],
        concurrency_limit: int = 10
    ) -> WorkflowResult:
        """Execute workflow from start to completion.
        
        Args:
            workflow_def: Workflow definition to execute
            inputs: Workflow input values
            concurrency_limit: Maximum concurrent node executions
        
        Returns:
            WorkflowResult with execution status and node results
        """
        # Initialize execution context
        ctx = ExecutionContext(
            workflow_inputs=inputs,
            concurrency_limit=concurrency_limit
        )
        
        # Get topologically sorted layers
        layers = topological_sort_with_layers(workflow_def.nodes)
        
        # Build node map for quick lookup
        nodes_map = {node.id: node for node in workflow_def.nodes}
        
        # Execute layers sequentially, nodes within layer in parallel
        for layer in layers:
            if ctx.stopped:
                # Mark remaining nodes as skipped
                for node_id in layer:
                    if node_id not in ctx.node_results:
                        ctx.node_results[node_id] = NodeResult(
                            status=NodeStatus.SKIPPED,
                            error="Workflow stopped due to upstream failure"
                        )
                        ctx.node_statuses[node_id] = NodeStatus.SKIPPED
                continue
            
            await self._execute_layer(layer, nodes_map, ctx)
            
            # Check if any node triggered a stop
            if ctx.stopped:
                continue
        
        # Compute final workflow status
        final_status = self._compute_workflow_status(ctx)
        
        # Extract workflow outputs
        outputs = self._extract_outputs(workflow_def, ctx)
        
        return WorkflowResult(
            status=final_status,
            node_results=ctx.node_results,
            outputs=outputs
        )
    
    async def _execute_layer(
        self,
        layer_node_ids: List[str],
        nodes_map: Dict[str, NodeDef],
        ctx: ExecutionContext
    ) -> None:
        """Execute all nodes in a layer concurrently.
        
        Args:
            layer_node_ids: Node IDs in this layer
            nodes_map: Map of node_id -> NodeDef
            ctx: Execution context
        """
        # Create tasks for all nodes in layer
        tasks = []
        for node_id in layer_node_ids:
            node_def = nodes_map[node_id]
            task = self._execute_node(node_def, ctx, nodes_map)
            tasks.append(task)
        
        # Execute all nodes in parallel
        await asyncio.gather(*tasks)
    
    async def _execute_node(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext,
        nodes_map: Dict[str, NodeDef]
    ) -> None:
        """Execute a single node with all pre/post checks.
        
        Args:
            node_def: Node definition to execute
            ctx: Execution context
            nodes_map: Map of node_id -> NodeDef (for failure handling)
        """
        node_id = node_def.id
        
        # Check if already skipped
        if node_id in ctx.skipped_nodes:
            ctx.node_results[node_id] = NodeResult(
                status=NodeStatus.SKIPPED,
                error="Marked for skipping"
            )
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            return
        
        # Evaluate when condition
        if not self._evaluate_when(node_def, ctx):
            ctx.node_results[node_id] = NodeResult(status=NodeStatus.SKIPPED)
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            return
        
        # Check trigger rule
        if not self._check_trigger_rule(node_def, ctx):
            ctx.node_results[node_id] = NodeResult(
                status=NodeStatus.SKIPPED,
                error="Trigger rule not satisfied"
            )
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            return
        
        # Mark as running
        ctx.node_statuses[node_id] = NodeStatus.RUNNING
        started_at = datetime.utcnow()
        
        try:
            # Resolve variables in node definition
            resolved_inputs = self._resolve_node_inputs(node_def, ctx)
            
            # Get runner
            runner_class = get_runner(node_def.type)
            if not runner_class:
                raise RuntimeError(f"No runner registered for node type: {node_def.type}")
            
            runner = runner_class()
            
            # Create runner context
            runner_ctx = RunnerContext(
                node_def=node_def,
                resolved_inputs=resolved_inputs,
                node_outputs=ctx.node_outputs,
                workflow_inputs=ctx.workflow_inputs,
                max_output_bytes=10 * 1024 * 1024
            )
            
            # Get timeout for this node
            timeout = self._get_node_timeout(node_def)
            
            # Execute in thread pool with timeout
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=ctx.concurrency_limit) as pool:
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(pool, runner.run, runner_ctx),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    result = NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Node execution timed out after {timeout}s"
                    )
        
        except Exception as e:
            result = NodeResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )
        
        # Set timestamps
        completed_at = datetime.utcnow()
        result.started_at = started_at
        result.completed_at = completed_at
        
        # Check output size
        if result.output:
            output_size = len(json.dumps(result.output))
            if output_size > 10 * 1024 * 1024:
                # Truncate output
                result.output = {"_truncated": True, "_size_bytes": output_size}
                result.error = (result.error or "") + f" (Output truncated: {output_size} bytes)"
        
        # Store result
        ctx.node_results[node_id] = result
        ctx.node_statuses[node_id] = result.status
        
        # Store output for downstream variable resolution
        if result.status == NodeStatus.COMPLETED and result.output:
            ctx.node_outputs[node_id] = result.output
        
        # Handle failure
        if result.status == NodeStatus.FAILED:
            await self._handle_failure(node_def, ctx, nodes_map)
    
    def _evaluate_when(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> bool:
        """Evaluate when condition for a node.
        
        Args:
            node_def: Node definition
            ctx: Execution context
        
        Returns:
            True if node should execute, False to skip
        """
        if node_def.when is None:
            return True
        
        # Handle string literals
        when_expr = node_def.when.strip()
        if when_expr.lower() in ("true", "1"):
            return True
        if when_expr.lower() in ("false", "0", ""):
            return False
        
        # Prepare evaluation context with workflow inputs and node outputs
        eval_context = {**ctx.workflow_inputs}
        
        # Flatten node outputs into context
        for node_id, output in ctx.node_outputs.items():
            if isinstance(output, dict):
                for key, value in output.items():
                    eval_context[f"{node_id}.{key}"] = value
            else:
                eval_context[node_id] = output
        
        # Evaluate expression
        evaluator = SimpleEval(names=eval_context)
        try:
            result = evaluator.eval(when_expr)
            return bool(result)
        except Exception:
            # If evaluation fails, skip the node
            return False
    
    def _check_trigger_rule(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> bool:
        """Check if trigger rule is satisfied.
        
        Args:
            node_def: Node definition
            ctx: Execution context
        
        Returns:
            True if trigger rule satisfied, False to skip
        """
        if not node_def.depends_on:
            # No dependencies, always execute
            return True
        
        # Get upstream statuses
        upstream_statuses = [
            ctx.node_statuses.get(dep_id, NodeStatus.PENDING)
            for dep_id in node_def.depends_on
        ]
        
        # Apply trigger rule
        if node_def.trigger_rule == TriggerRule.ALL_SUCCESS:
            # All must be completed
            return all(status == NodeStatus.COMPLETED for status in upstream_statuses)
        
        elif node_def.trigger_rule == TriggerRule.ONE_SUCCESS:
            # At least one must be completed
            return any(status == NodeStatus.COMPLETED for status in upstream_statuses)
        
        elif node_def.trigger_rule == TriggerRule.ALL_DONE:
            # All must be in terminal state
            terminal_states = {NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED}
            return all(status in terminal_states for status in upstream_statuses)
        
        return True
    
    def _resolve_node_inputs(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> Dict[str, Any]:
        """Resolve variable references in node inputs.

        Args:
            node_def: Node definition
            ctx: Execution context

        Returns:
            Resolved inputs dict
        """
        # Collect all relevant fields to resolve
        inputs_to_resolve: Dict[str, Any] = {}

        # Add type-specific fields
        if node_def.script:
            inputs_to_resolve["script"] = node_def.script
        if node_def.command:
            inputs_to_resolve["command"] = node_def.command
        if node_def.args:
            inputs_to_resolve["args"] = node_def.args
        if node_def.params:
            inputs_to_resolve["params"] = node_def.params
        if node_def.prompt:
            inputs_to_resolve["prompt"] = node_def.prompt
        if node_def.condition:
            inputs_to_resolve["condition"] = node_def.condition

        # Resolve variables
        resolved = resolve_variables(
            inputs_to_resolve,
            ctx.node_outputs,
            ctx.workflow_inputs
        )

        return resolved  # type: ignore[no-any-return]
    
    async def _handle_failure(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext,
        nodes_map: Dict[str, NodeDef]
    ) -> None:
        """Handle node failure according to on_failure policy.
        
        Args:
            node_def: Failed node definition
            ctx: Execution context
            nodes_map: Map of node_id -> NodeDef
        """
        if node_def.on_failure == OnFailure.STOP:
            # Stop workflow execution
            ctx.stopped = True
        
        elif node_def.on_failure == OnFailure.CONTINUE:
            # Do nothing, execution continues
            pass
        
        elif node_def.on_failure == OnFailure.SKIP_DOWNSTREAM:
            # Mark all downstream nodes as skipped
            self._mark_downstream_skipped(node_def.id, nodes_map, ctx)
    
    def _mark_downstream_skipped(
        self,
        failed_node_id: str,
        nodes_map: Dict[str, NodeDef],
        ctx: ExecutionContext
    ) -> None:
        """Recursively mark all downstream nodes as skipped.
        
        Args:
            failed_node_id: ID of the failed node
            nodes_map: Map of node_id -> NodeDef
            ctx: Execution context
        """
        # Find all nodes that depend on this node
        for node_id, node_def in nodes_map.items():
            if failed_node_id in node_def.depends_on:
                ctx.skipped_nodes.add(node_id)
                # Recursively mark its dependents
                self._mark_downstream_skipped(node_id, nodes_map, ctx)
    
    def _get_node_timeout(self, node_def: NodeDef) -> float:
        """Get timeout for a node.
        
        Args:
            node_def: Node definition
        
        Returns:
            Timeout in seconds
        """
        if node_def.timeout:
            return float(node_def.timeout)
        
        # Use default based on node type
        return float(self.DEFAULT_TIMEOUTS.get(node_def.type, 60))
    
    def _compute_workflow_status(self, ctx: ExecutionContext) -> WorkflowStatus:
        """Compute final workflow status.
        
        Args:
            ctx: Execution context
        
        Returns:
            Final workflow status
        """
        statuses = ctx.node_statuses.values()
        
        if any(status == NodeStatus.FAILED for status in statuses):
            return WorkflowStatus.FAILED
        
        if all(status in {NodeStatus.COMPLETED, NodeStatus.SKIPPED} for status in statuses):
            return WorkflowStatus.COMPLETED
        
        return WorkflowStatus.FAILED
    
    def _extract_outputs(
        self,
        workflow_def: WorkflowDef,
        ctx: ExecutionContext
    ) -> Dict[str, Any]:
        """Extract workflow outputs from node results.
        
        Args:
            workflow_def: Workflow definition
            ctx: Execution context
        
        Returns:
            Workflow outputs dict
        """
        outputs = {}
        
        for output_name, output_def in workflow_def.outputs.items():
            source_node = output_def.node
            if source_node in ctx.node_outputs:
                node_output = ctx.node_outputs[source_node]
                
                if output_def.field:
                    # Extract specific field
                    if isinstance(node_output, dict) and output_def.field in node_output:
                        outputs[output_name] = node_output[output_def.field]
                else:
                    # Use entire output
                    outputs[output_name] = node_output
        
        return outputs
