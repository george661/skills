"""Prompt runner for LLM invocation nodes."""
import subprocess
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
        
        # Execute CLI
        try:
            result = subprocess.run(
                cmd,
                input=prompt_input,
                capture_output=True,
                text=True,
                timeout=ctx.node_def.timeout or 600  # Default 10 min timeout for LLM
            )
            
            if result.returncode != 0:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=result.stderr or f"CLI exited with code {result.returncode}"
                )
            
            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={"response": result.stdout}
            )
            
        except subprocess.TimeoutExpired:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Prompt execution timed out after {ctx.node_def.timeout} seconds"
            )
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Prompt execution failed: {str(e)}"
            )
