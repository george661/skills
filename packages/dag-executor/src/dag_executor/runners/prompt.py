"""Prompt runner for LLM invocation nodes."""
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from dag_executor.artifacts import detect_artifacts
from dag_executor.conversations import (
    get_active_session,
    mint_session,
    transition_session,
    append_message,
    build_conversation_message_appended_event,
)
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.model_resolver import resolve_model
from dag_executor.schema import ContextMode, ModelTier, NodeResult, NodeStatus, OutputFormat
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner

logger = logging.getLogger(__name__)


def _resolve_session(ctx: RunnerContext) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve session ID for this prompt execution.

    Returns tuple of (session_id, transition_reason, parent_session_id).
    - If ctx.conversation_id or ctx.db_path is None: return (None, None, None) - skip session logic
    - If context=SHARED: resume active session or mint new if none exists
    - If context=FRESH: transition to new session, deactivating old one

    Args:
        ctx: Runner execution context

    Returns:
        (session_id, transition_reason, parent_session_id) where transition_reason is None for SHARED,
        "fresh-context" for FRESH transitions, and parent_session_id is the old active session ID
        during FRESH transitions (None otherwise)
    """
    # Skip session logic if no conversation context
    if ctx.conversation_id is None or ctx.db_path is None:
        return None, None, None

    node = ctx.node_def
    context_mode = node.context if hasattr(node, 'context') else ContextMode.SHARED

    if context_mode == ContextMode.SHARED:
        # Resume active session or mint new if none exists
        active_session = get_active_session(ctx.db_path, ctx.conversation_id)
        if active_session is None:
            # First prompt in conversation - mint new session
            new_session = mint_session(ctx.db_path, ctx.conversation_id)
            return new_session.id, None, None
        return active_session.id, None, None

    elif context_mode == ContextMode.FRESH:
        # Get current active session (should exist)
        active_session = get_active_session(ctx.db_path, ctx.conversation_id)
        if active_session is None:
            # No active session - mint first one
            new_session = mint_session(ctx.db_path, ctx.conversation_id)
            return new_session.id, None, None
        # Transition to new session - capture old session ID as parent
        parent_session_id = active_session.id
        new_session = transition_session(
            ctx.db_path,
            old_session_id=active_session.id,
            reason="fresh-context"
        )
        return new_session.id, "fresh-context", parent_session_id

    return None, None, None


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

        # Resolve session for conversation continuity
        session_id, transition_reason, parent_session_id = _resolve_session(ctx)

        # Dispatcher is installed by scripts/install.sh into ~/.claude/hooks/.
        dispatch_script = Path.home() / ".claude" / "hooks" / "dispatch-local.sh"
        cmd = [str(dispatch_script), "--model", resolved_model.value]

        # Add session ID if conversation context is present
        if session_id is not None:
            cmd.extend(["--session-id", session_id])

        # Handle prompt vs prompt_file. Inline prompts go via stdin (avoids arg
        # length limits); prompt_file is passed through --file.
        prompt_input = None

        # prompt_file takes precedence (never resolved, always direct file reference)
        if node.prompt_file is not None:
            cmd.extend(["--file", node.prompt_file])
        elif node.prompt is not None:
            # Use resolved prompt from executor if available, else fall back to node.prompt
            resolved_prompt = ctx.resolved_inputs.get("prompt") if ctx.resolved_inputs else None
            effective_prompt = resolved_prompt if resolved_prompt is not None else node.prompt
            cmd.append("--prompt-stdin")
            prompt_input = effective_prompt

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

            # Append messages to conversation if session context is present
            if session_id is not None and ctx.conversation_id is not None and ctx.db_path is not None:
                try:
                    # Append user message
                    # When node.prompt_file is set, read actual file contents instead of storing a stub
                    if prompt_input is not None:
                        effective_prompt = prompt_input
                    elif node.prompt_file:
                        effective_prompt = Path(node.prompt_file).read_text()
                    else:
                        effective_prompt = ""
                    msg_in = append_message(
                        db_path=ctx.db_path,
                        role="user",
                        content=effective_prompt,
                        conversation_id=ctx.conversation_id,
                        session_id=session_id,
                        run_id=ctx.workflow_id,
                        execution_id=None,  # node.id references nodes, not node_executions
                    )
                    msg_in_id = msg_in.id

                    # Emit event for user message
                    if ctx.event_emitter is not None:
                        event_in = build_conversation_message_appended_event(
                            run_id=ctx.workflow_id,
                            node_id=node.id,
                            conversation_id=ctx.conversation_id,
                            session_id=session_id,
                            role="user",
                            message_id=msg_in_id,
                            transition_reason=transition_reason,
                            parent_session_id=parent_session_id,
                        )
                        ctx.event_emitter.emit(WorkflowEvent(
                            event_type=EventType.CONVERSATION_MESSAGE_APPENDED,
                            workflow_id=ctx.workflow_id,
                            node_id=node.id,
                            metadata=event_in["payload"],
                            timestamp=datetime.now(timezone.utc),
                        ))

                    # Append assistant message
                    msg_out = append_message(
                        db_path=ctx.db_path,
                        role="assistant",
                        content=full_output,
                        conversation_id=ctx.conversation_id,
                        session_id=session_id,
                        run_id=ctx.workflow_id,
                        execution_id=None,  # node.id references nodes, not node_executions
                    )
                    msg_out_id = msg_out.id

                    # Emit event for assistant message
                    if ctx.event_emitter is not None:
                        event_out = build_conversation_message_appended_event(
                            run_id=ctx.workflow_id,
                            node_id=node.id,
                            conversation_id=ctx.conversation_id,
                            session_id=session_id,
                            role="assistant",
                            message_id=msg_out_id,
                            parent_session_id=parent_session_id,
                        )
                        ctx.event_emitter.emit(WorkflowEvent(
                            event_type=EventType.CONVERSATION_MESSAGE_APPENDED,
                            workflow_id=ctx.workflow_id,
                            node_id=node.id,
                            metadata=event_out["payload"],
                            timestamp=datetime.now(timezone.utc),
                        ))

                except Exception as e:
                    # Log but don't fail the node - session data is secondary to LLM response
                    logger.warning(f"Failed to append conversation message: {e}")

            # GW-5308: If output_format is JSON, spread parsed fields into output dict
            # while preserving the raw text in "response" for backward compatibility
            output_dict = {}
            if node.output_format == OutputFormat.JSON:
                try:
                    parsed = json.loads(full_output)
                    if isinstance(parsed, dict):
                        # Spread parsed fields first
                        output_dict.update(parsed)
                except (json.JSONDecodeError, ValueError) as e:
                    # Invalid JSON - log and fall back to text-only behavior
                    logger.debug(f"Failed to parse JSON output: {e}")

            # Always set response last to guarantee backward compat
            # (raw text wins if parsed JSON contains a "response" key)
            output_dict["response"] = full_output

            # GW-5308: AC-14 — Populate writes keys
            # For each key in node.writes, ensure it exists in output_dict.
            # In JSON mode, setdefault preserves already-spread fields.
            # In text mode, setdefault populates the key with full_output.
            for key in (node.writes or []):
                output_dict.setdefault(key, full_output)

            return NodeResult(
                status=NodeStatus.COMPLETED,
                output=output_dict
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
