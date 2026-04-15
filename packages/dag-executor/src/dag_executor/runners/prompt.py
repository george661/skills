"""Prompt runner for LLM invocation nodes."""
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("prompt")
class PromptRunner(BaseRunner):
    """Runner for LLM prompt nodes.
    
    Invokes Claude Code CLI via dispatch-local.sh with model tier.
    MVP: local dispatch only.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a prompt node.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and LLM response
        """
        node = ctx.node_def
        if node.model is None:
            raise ValueError("model field is required for type=prompt")
        
        # Build CLI command
        dispatch_script = Path.home() / ".claude" / "dispatch-local.sh"
        cmd = [str(dispatch_script), "--model", node.model.value]
        
        # Handle prompt vs prompt_file
        prompt_input = None
        if node.prompt is not None:
            # Inline prompt - pass via stdin or temp file
            prompt_input = node.prompt
        elif node.prompt_file is not None:
            # Prompt file - pass file path as argument
            cmd.extend(["--file", node.prompt_file])
        
        # Execute CLI with streaming support
        try:
            # Use Popen for line-by-line streaming
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if prompt_input else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Write input if provided
            if prompt_input and process.stdin:
                process.stdin.write(prompt_input)
                process.stdin.close()

            # Stream output line by line
            output_lines = []
            if process.stdout:
                for line in process.stdout:
                    output_lines.append(line)
                    # Emit stream token event if emitter is available
                    if ctx.event_emitter:
                        from dag_executor.events import EventType, WorkflowEvent
                        ctx.event_emitter.emit(WorkflowEvent(
                            event_type=EventType.NODE_STREAM_TOKEN,
                            workflow_id="",  # Will be set by executor context
                            node_id=ctx.node_def.id,
                            metadata={"token": line.rstrip('\n')},
                            timestamp=datetime.now(timezone.utc)
                        ))

            # Wait for process completion with timeout
            timeout = ctx.node_def.timeout or 600  # Default 10 min timeout for LLM
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill process on timeout
                process.kill()
                process.wait()
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=f"Prompt execution timed out after {timeout} seconds"
                )

            # Collect stderr
            stderr = process.stderr.read() if process.stderr else ""

            if returncode != 0:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=stderr or f"CLI exited with code {returncode}"
                )

            # Combine all output lines
            full_output = "".join(output_lines)

            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={"response": full_output}
            )

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Prompt execution failed: {str(e)}"
            )
