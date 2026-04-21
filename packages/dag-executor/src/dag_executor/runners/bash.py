"""Bash runner for executing bash script nodes."""
import asyncio
import os
from datetime import datetime, timezone
from typing import List

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
        # Wrap async implementation in asyncio.run to preserve sync interface
        return asyncio.run(self._run_async(ctx))

    async def _run_async(self, ctx: RunnerContext) -> NodeResult:
        """Async implementation of bash script execution with line streaming.

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

        timeout = ctx.node_def.timeout or 300  # Default 5 min timeout

        try:
            # Create subprocess with pipes for stdout/stderr
            process = await asyncio.create_subprocess_exec(
                "bash", "-c", script,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Register with subprocess registry if available
            if ctx.subprocess_registry is not None:
                ctx.subprocess_registry.register(process)  # type: ignore[arg-type]

            try:
                # Assert streams are not None (guaranteed by PIPE)
                assert process.stdout is not None
                assert process.stderr is not None

                # Track cumulative output and sequence number
                stdout_lines: List[str] = []
                stderr_lines: List[str] = []
                total_bytes = 0
                sequence = 0
                size_exceeded = False

                async def read_stream(stream: asyncio.StreamReader, stream_name: str, lines_list: List[str]) -> None:
                    """Read lines from a stream and emit events."""
                    nonlocal total_bytes, sequence, size_exceeded

                    while True:
                        line_bytes = await stream.readline()
                        if not line_bytes:
                            break

                        # Check size limit before decoding
                        total_bytes += len(line_bytes)
                        if total_bytes > ctx.max_output_bytes:
                            size_exceeded = True
                            break

                        # Decode and store
                        line = line_bytes.decode('utf-8', errors='replace')
                        lines_list.append(line)

                        # Emit event if emitter is present
                        if ctx.event_emitter:
                            ctx.event_emitter.emit(WorkflowEvent(
                                event_type=EventType.NODE_LOG_LINE,
                                workflow_id=ctx.workflow_id,
                                node_id=ctx.node_def.id,
                                timestamp=datetime.now(timezone.utc),
                                metadata={
                                    "sequence": sequence,
                                    "stream": stream_name,
                                    "line": line.rstrip('\n')
                                }
                            ))
                            sequence += 1

                # Read both streams concurrently with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            read_stream(process.stdout, "stdout", stdout_lines),
                            read_stream(process.stderr, "stderr", stderr_lines),
                            process.wait()
                        ),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    # Kill process on timeout
                    process.kill()
                    await process.wait()
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Script execution timed out after {timeout} seconds"
                    )

                # Check if size limit was exceeded
                if size_exceeded:
                    process.kill()
                    await process.wait()
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Output size limit exceeded: {total_bytes} bytes > {ctx.max_output_bytes} bytes"
                    )

                # Combine output
                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)

                # Check exit code
                if process.returncode != 0:
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=stderr or f"Script exited with code {process.returncode}",
                        output={"stdout": stdout, "stderr": stderr}
                    )

                # Emit artifact events for successful completion
                if ctx.event_emitter is not None:
                    for artifact in detect_artifacts(stdout + "\n" + stderr):
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
                        "stdout": stdout,
                        "stderr": stderr
                    }
                )
            finally:
                # Deregister from subprocess registry
                if ctx.subprocess_registry is not None:
                    ctx.subprocess_registry.deregister(process)  # type: ignore[arg-type]

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Script execution failed: {str(e)}"
            )
