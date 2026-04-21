"""Bash runner for executing bash script nodes."""
import os
import subprocess
from datetime import datetime, timezone

from dag_executor.artifacts import detect_artifacts
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("bash")
class BashRunner(BaseRunner):
    """Runner for bash script execution nodes.
    
    Passes variables as DAG_ prefixed environment variables (not inline substitution).
    Enforces timeout and output size limits.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a bash script node.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and output
        """
        script = ctx.node_def.script
        if script is None:
            raise ValueError("script field is required for type=bash")
        
        # Build environment with DAG_ prefixed variables
        env = os.environ.copy()
        for key, value in ctx.resolved_inputs.items():
            env[f"DAG_{key.upper()}"] = str(value)
        
        # Execute bash script
        try:
            result = subprocess.run(
                ["bash", "-c", script],
                env=env,
                capture_output=True,
                text=True,
                timeout=ctx.node_def.timeout or 300  # Default 5 min timeout
            )
            
            # Check output size limit
            total_output_size = len(result.stdout) + len(result.stderr)
            if total_output_size > ctx.max_output_bytes:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=f"Output size limit exceeded: {total_output_size} bytes > {ctx.max_output_bytes} bytes"
                )
            
            # Check exit code
            if result.returncode != 0:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=result.stderr or f"Script exited with code {result.returncode}",
                    output={"stdout": result.stdout, "stderr": result.stderr}
                )

            # Emit artifact events for successful completion
            if ctx.event_emitter is not None:
                for artifact in detect_artifacts(result.stdout + "\n" + result.stderr):
                    ctx.event_emitter.emit(WorkflowEvent(
                        event_type=EventType.ARTIFACT_CREATED,
                        workflow_id=ctx.workflow_id,
                        node_id=ctx.node_def.id,
                        metadata=artifact,
                        timestamp=datetime.now(timezone.utc),
                    ))

            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            )
            
        except subprocess.TimeoutExpired:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Script execution timed out after {ctx.node_def.timeout} seconds"
            )
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Script execution failed: {str(e)}"
            )
