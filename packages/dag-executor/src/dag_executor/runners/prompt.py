"""Prompt runner for LLM invocation nodes."""
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dag_executor.artifacts import detect_artifacts
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.model_resolver import resolve_model
from dag_executor.schema import ModelTier, NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("prompt")
class PromptRunner(BaseRunner):
    """Runner for LLM prompt nodes.

    Invokes Claude Code CLI via dispatch-local.sh in raw-prompt mode. The model
    tier (opus/sonnet/haiku/local) is resolved to a concrete model by the
    dispatcher via model-routing.json, so workflows only need to declare intent.
    """

    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a prompt node.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with execution status and LLM response
        """
        node = ctx.node_def

        # Resolve model using 4-tier resolution: override > node > workflow default > local
        if ctx.workflow_def is not None:
            resolved_model = resolve_model(node, ctx.workflow_def, ctx.workflow_inputs)
        else:
            # Fallback for single-node test contexts without workflow_def
            resolved_model = node.model or ModelTier.LOCAL

        # Dispatcher is installed by scripts/install.sh into ~/.claude/hooks/.
        dispatch_script = Path.home() / ".claude" / "hooks" / "dispatch-local.sh"
        cmd = [str(dispatch_script), "--model", resolved_model.value]

        # Handle prompt vs prompt_file. Inline prompts go via stdin (avoids arg
        # length limits); prompt_file is passed through --file.
        prompt_input = None
        if node.prompt is not None:
            cmd.append("--prompt-stdin")
            prompt_input = node.prompt
        elif node.prompt_file is not None:
            cmd.extend(["--file", node.prompt_file])
        
        # Execute CLI with streaming support
        process = None
        try:
            # Use Popen for line-by-line streaming
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if prompt_input else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Register with subprocess registry so cancel can SIGTERM it
            if ctx.subprocess_registry is not None:
                ctx.subprocess_registry.register(process)

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
                            workflow_id=ctx.workflow_id,
                            node_id=ctx.node_def.id,
                            metadata={"token": line.rstrip('\n')},
                            timestamp=datetime.now(timezone.utc)
                        ))

            # Wait for process completion with timeout
            # NOTE: Timeout only applies after stdout draining completes. If the process generates
            # more output than the pipe buffer can hold without being consumed, the timeout countdown
            # does not begin until the for-loop above finishes reading all output.
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

            # Emit artifact events for successful completion
            if ctx.event_emitter is not None:
                for artifact in detect_artifacts(full_output):
                    ctx.event_emitter.emit(WorkflowEvent(
                        event_type=EventType.ARTIFACT_CREATED,
                        workflow_id=ctx.workflow_id,
                        node_id=ctx.node_def.id,
                        metadata=artifact,
                        timestamp=datetime.now(timezone.utc),
                    ))

            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={"response": full_output}
            )

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Prompt execution failed: {str(e)}"
            )
        finally:
            # Always deregister from subprocess registry, even on exception
            if process is not None and ctx.subprocess_registry is not None:
                ctx.subprocess_registry.deregister(process)
