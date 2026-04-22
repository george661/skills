"""Skill runner for executing skill nodes."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from dag_executor.artifacts import detect_artifacts
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("skill")
class SkillRunner(BaseRunner):
    """Runner for skill execution nodes.
    
    Validates skill path is within skills directory and executes via subprocess.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a skill node.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with execution status and output
        """
        # Wrap async implementation in asyncio.run to preserve sync interface
        return asyncio.run(self._run_async(ctx))

    async def _run_async(self, ctx: RunnerContext) -> NodeResult:
        """Async implementation of skill execution with line streaming.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with execution status and output
        """
        # Extract skill configuration from validated NodeDef
        skill_path = ctx.node_def.skill
        if skill_path is None:
            raise ValueError("skill field is required for type=skill")
        params = ctx.node_def.params or {}

        # Validate skill path
        if ctx.skills_dir is None:
            return NodeResult(
                status=NodeStatus.FAILED,
                error="skills_dir not configured in runner context"
            )

        try:
            resolved_path = self._validate_skill_path(skill_path, ctx.skills_dir)
        except ValueError as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )

        timeout = ctx.node_def.timeout or 300  # Default 5 min timeout

        try:
            # Create subprocess with pipes for stdin/stdout/stderr
            process = await asyncio.create_subprocess_exec(
                "python3", str(resolved_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Write params JSON to stdin and close it
            params_json = json.dumps(params)
            if process.stdin is not None:
                process.stdin.write(params_json.encode('utf-8'))
                await process.stdin.drain()
                process.stdin.close()

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
                        error=f"Skill execution timed out after {timeout} seconds"
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
                        error=stderr or f"Skill exited with code {process.returncode}"
                    )

                # Try to parse JSON output
                try:
                    output = json.loads(stdout)
                except json.JSONDecodeError:
                    # Non-JSON output, return as raw text
                    output = {"stdout": stdout}

                # Emit artifact events for successful completion
                if ctx.event_emitter is not None:
                    combined = stdout + "\n" + stderr
                    for artifact in detect_artifacts(combined):
                        ctx.event_emitter.emit(WorkflowEvent(
                            event_type=EventType.ARTIFACT_CREATED,
                            workflow_id=ctx.workflow_id,
                            node_id=ctx.node_def.id,
                            metadata=artifact,
                            timestamp=datetime.now(timezone.utc),
                        ))

                return NodeResult(
                    status=NodeStatus.COMPLETED,
                    output=output
                )
            finally:
                # Deregister from subprocess registry
                if ctx.subprocess_registry is not None:
                    ctx.subprocess_registry.deregister(process)

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Skill execution failed: {str(e)}"
            )
    
    def _validate_skill_path(self, skill_path: str, skills_dir: Path) -> Path:
        """Validate and resolve skill path.
        
        Args:
            skill_path: Relative path to skill file
            skills_dir: Root skills directory
            
        Returns:
            Resolved absolute path
            
        Raises:
            ValueError: If path is invalid or outside skills directory
        """
        # Resolve the candidate path
        if Path(skill_path).is_absolute():
            resolved = Path(skill_path).resolve()
        else:
            resolved = (skills_dir / skill_path).resolve()

        skills_dir_resolved = skills_dir.resolve()

        # Verify resolved path is within skills_dir (prevents .. traversal and sibling-dir attacks)
        if not resolved.is_relative_to(skills_dir_resolved):
            raise ValueError(f"Path traversal detected - skill path outside skills directory: {skill_path}")

        return resolved
