"""Bash runner for executing bash script nodes."""
import asyncio
import os
from datetime import datetime, timezone
from typing import Any, List

import json

from dag_executor.artifacts import detect_artifacts
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


def _env_str(value: object) -> str:
    """Render a channel/input value for the subprocess environment.

    Strings pass through. Everything else goes to JSON so downstream bash
    pipelines see valid JSON (not Python's repr of a dict with single quotes
    and True/False) when they do `echo "$channel" | jq ...`.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


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
        script = ctx.resolved_inputs.get("script", ctx.node_def.script)
        if script is None:
            raise ValueError("script field is required for type=bash")

        # Build environment variables that the script can reference directly.
        # Three sources are layered in, later sources win on collision:
        #   1. resolved_inputs (script/prompt/params/...) under DAG_<UPPER>
        #   2. declared `reads:` state channels, under both DAG_<UPPER> and the
        #      lowercase channel name — the lowercase form lets authors write
        #      `$children_list` naturally (matches the YAML) while the
        #      DAG_-prefixed form preserves the long-standing convention.
        #   3. workflow inputs (required because the resolver skips reads:
        #      names; without env passthrough `$children_list` would expand
        #      to empty string in the subshell).
        env = os.environ.copy()
        for key, value in ctx.resolved_inputs.items():
            env[f"DAG_{key.upper()}"] = _env_str(value)

        def _export_channel(name: str, value: Any) -> None:
            rendered = _env_str(value)
            env[f"DAG_{name.upper()}"] = rendered
            env[name] = rendered

        # Workflow inputs are always in scope (the resolver handles these via
        # substitution, but bash scripts that use DAG_<UPPER> still need them).
        for key, value in ctx.workflow_inputs.items():
            _export_channel(key, value)

        # `reads:` channel values — pulled from the channel_store when the
        # node declares them. `ctx.workflow_inputs` doesn't include channels,
        # so we read directly.
        channel_store = getattr(ctx, "channel_store", None)
        for channel_name in (ctx.node_def.reads or []):
            if channel_store is None:
                continue
            try:
                value, _version = channel_store.read(channel_name)
            except KeyError:
                continue
            _export_channel(channel_name, value)

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
                ctx.subprocess_registry.register(process)

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
                    ctx.subprocess_registry.deregister(process)

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Script execution failed: {str(e)}"
            )
