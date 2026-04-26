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
    Streams stdout/stderr line-by-line as NODE_LOG_LINE events while preserving
    final JSON parse of accumulated stdout.
    """

    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a skill node.

        Args:
            ctx: Runner execution context

        Returns:
            NodeResult with execution status and output
        """
        # Wrap async implementation in asyncio.run to preserve sync interface.
        # Safe because executor.py invokes runners via loop.run_in_executor
        # (thread pool), so each call runs in a thread without a live event loop.
        return asyncio.run(self._run_async(ctx))

    async def _run_async(self, ctx: RunnerContext) -> NodeResult:
        """Async implementation of skill execution with line streaming."""
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

        # Build the subprocess command based on skill file extension.
        # Historically SkillRunner only invoked python3 with params on stdin.
        # That silently broke every TypeScript skill (which needs `npx tsx`
        # and reads params from argv[2]), and those are the overwhelming
        # majority of skills in ~/.claude/skills. GW-5356 follow-up #4:
        # detect the language by suffix and route appropriately.
        params_json = json.dumps(params)
        suffix = resolved_path.suffix.lower()
        if suffix == ".ts":
            # TS skills: `npx tsx <path> '<json>'`. Params via argv[2].
            cmd = ["npx", "tsx", str(resolved_path), params_json]
            send_params_on_stdin = False
        elif suffix == ".sh":
            # Bash skills: `bash <path> '<json>'`. argv[1] is the JSON.
            cmd = ["bash", str(resolved_path), params_json]
            send_params_on_stdin = False
        else:
            # Python (and anything else with a shebang) keeps the
            # stdin-JSON convention.
            cmd = ["python3", str(resolved_path)]
            send_params_on_stdin = True

        try:
            # Create async subprocess with pipes for stdin/stdout/stderr
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Register with subprocess registry if available
            if ctx.subprocess_registry is not None:
                ctx.subprocess_registry.register(process)

            try:
                # Assert streams are not None (guaranteed by PIPE)
                assert process.stdin is not None
                assert process.stdout is not None
                assert process.stderr is not None

                # Send params on stdin only for the python path — TS/bash
                # skills received params as argv. Always close stdin so the
                # skill doesn't hang waiting for input.
                if send_params_on_stdin:
                    try:
                        process.stdin.write(params_json.encode("utf-8"))
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        # Skill may exit before reading stdin; that's fine —
                        # we'll see returncode/stderr below.
                        pass
                try:
                    process.stdin.close()
                except Exception:
                    pass

                # Track cumulative output and sequence number
                stdout_lines: List[str] = []
                stderr_lines: List[str] = []
                total_bytes = 0
                sequence = 0
                size_exceeded = False

                async def read_stream(
                    stream: asyncio.StreamReader,
                    stream_name: str,
                    lines_list: List[str],
                ) -> None:
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
                        line = line_bytes.decode("utf-8", errors="replace")
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
                                    "line": line.rstrip("\n"),
                                },
                            ))
                            sequence += 1

                # Read both streams concurrently with timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            read_stream(process.stdout, "stdout", stdout_lines),
                            read_stream(process.stderr, "stderr", stderr_lines),
                            process.wait(),
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Skill execution timed out after {timeout} seconds",
                    )

                # Check if size limit was exceeded
                if size_exceeded:
                    process.kill()
                    await process.wait()
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=(
                            f"Output size limit exceeded: {total_bytes} bytes > "
                            f"{ctx.max_output_bytes} bytes"
                        ),
                    )

                # Combine output
                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)

                # Check exit code
                if process.returncode != 0:
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=stderr or f"Skill exited with code {process.returncode}",
                    )

                # Try to parse JSON output from accumulated stdout (unchanged semantics)
                try:
                    output = json.loads(stdout)
                except json.JSONDecodeError:
                    # Non-JSON output, return as raw text
                    output = {"stdout": stdout}

                # Emit artifact events for successful completion
                if ctx.event_emitter is not None:
                    combined = (stdout or "") + "\n" + (stderr or "")
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
                    output=output,
                )
            finally:
                # Deregister from subprocess registry
                if ctx.subprocess_registry is not None:
                    ctx.subprocess_registry.deregister(process)

        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Skill execution failed: {str(e)}",
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
