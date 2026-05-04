"""Orchestrator relay: manages a long-lived Claude subprocess per conversation."""
import asyncio
import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Any

from .queries import get_run, get_connection, insert_chat_message


logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """
You are a read-only workflow orchestrator analyst for run {run_id} (workflow: {workflow_name}, status: {status}, conversation: {conversation_id}).

Recent events (last 10):
{events_json}

Available channels: {channel_keys_csv}

You can query run details via: curl http://127.0.0.1:{port}/api/workflows/{run_id}/...

Tool allowlist: Bash, Read, Grep, Glob. No Write, no Edit. Your role is analyst only — observe, report, explain. Do not modify state.
"""


class OrchestratorRelay:
    """Manages a single Claude subprocess for a workflow conversation.
    
    Spawns two threads:
    - stdin_writer: reads from message_queue and writes stream-json user events
    - stdout_reader: reads stdout lines, parses stream-json, publishes via broadcaster
    """
    
    def __init__(
        self,
        conversation_id: str,
        run_id: str,
        db_path: Path,
        broadcaster: Any,
        model: Optional[str],
        event_loop: asyncio.AbstractEventLoop,
        dashboard_port: int,
        session_uuid: Optional[str] = None,
    ):
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.db_path = db_path
        self.broadcaster = broadcaster
        # model=None means "inherit from ANTHROPIC_MODEL env". We forward --model
        # only when explicitly set, because hardcoded defaults like
        # "claude-opus-4-7" don't resolve under CLAUDE_CODE_USE_BEDROCK=1 where
        # the model id must be a Bedrock inference profile (e.g.
        # "global.anthropic.claude-opus-4-7[1m]").
        self.model = model
        self.event_loop = event_loop
        self.dashboard_port = dashboard_port
        self.session_uuid = session_uuid
        
        self.process: Optional[subprocess.Popen[bytes]] = None
        self.message_queue: "Queue[str]" = Queue()
        self.stdin_thread: Optional[threading.Thread] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_active = time.time()

        # Streaming buffer: accumulates text_delta tokens during a turn so
        # we can persist a partial record if the subprocess dies mid-reply
        # (TTL eviction, crash, SIGKILL). Reset when a final "assistant"
        # event lands or when we flush on exit.
        self._pending_text_parts: list[str] = []
        self._pending_started_at: Optional[str] = None
        
    def _build_system_prompt(self) -> str:
        """Build system prompt string with run context.

        Returns the rendered prompt so it can be passed inline via --system-prompt.
        The claude 2.x CLI does not accept --system-prompt-file; only the inline
        form exists, so we render a string here rather than a temp file.
        """
        run = get_run(self.db_path, self.run_id)
        if not run:
            raise ValueError(f"Run {self.run_id} not found")

        # Fetch last 10 events from DB
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_type, payload, created_at FROM events WHERE run_id = ? ORDER BY created_at DESC LIMIT 10",
            (self.run_id,)
        )
        events = [
            {"event_type": row[0], "payload": row[1], "created_at": row[2]}
            for row in cursor.fetchall()
        ]
        events_json = json.dumps(events, indent=2)

        # Fetch distinct channel keys
        cursor.execute(
            "SELECT DISTINCT channel_key FROM channel_states WHERE run_id = ?",
            (self.run_id,)
        )
        channel_keys = [row[0] for row in cursor.fetchall()]
        channel_keys_csv = ",".join(channel_keys)
        conn.close()

        return SYSTEM_PROMPT_TEMPLATE.format(
            run_id=self.run_id,
            workflow_name=run.get("workflow_name", "unknown"),
            status=run.get("status", "unknown"),
            conversation_id=self.conversation_id,
            events_json=events_json,
            channel_keys_csv=channel_keys_csv,
            port=self.dashboard_port,
        )
    
    def start(self) -> None:
        """Spawn the Claude subprocess and start reader/writer threads.

        Command construction follows the claude 2.x CLI contract:
        - ``--print`` is required for ``--input-format=stream-json`` (non-interactive).
        - ``--verbose`` is required with ``--output-format=stream-json``.
        - ``--system-prompt`` takes an inline string; no ``-file`` variant exists.
        - ``--model`` is omitted unless explicitly configured so the process
          inherits ANTHROPIC_MODEL (necessary for Bedrock which rejects bare
          model names like "claude-opus-4-7").
        """
        if self.process is not None:
            logger.warning(f"Orchestrator for {self.conversation_id} already started")
            return

        system_prompt = self._build_system_prompt()

        cmd = [
            "claude",
            "--bare",
            "--print",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",  # Emit content_block_delta for token streaming
            "--replay-user-messages",
            "--permission-mode", "dontAsk",
            "--system-prompt", system_prompt,
            "--allowedTools", "Bash,Read,Grep,Glob",
        ]

        if self.model:
            cmd.extend(["--model", self.model])

        if self.session_uuid:
            cmd.extend(["--resume", self.session_uuid])
        else:
            # Generate new session UUID
            import uuid
            self.session_uuid = str(uuid.uuid4())
            cmd.extend(["--session-id", self.session_uuid])
        
        logger.info(f"Spawning orchestrator for {self.conversation_id}: {' '.join(cmd)}")
        
        # Spawn subprocess
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
        
        # Start threads. The stderr drain is critical: claude runs with
        # --verbose, which produces a steady byte-stream to stderr. The OS
        # pipe buffer is ~64 KB on macOS/Linux; once it fills the subprocess
        # blocks on its next stderr write and the whole orchestrator freezes
        # mid-reply. Drain it continuously.
        self.stdin_thread = threading.Thread(target=self._stdin_writer, daemon=True)
        self.stdout_thread = threading.Thread(target=self._stdout_reader, daemon=True)
        self.stderr_thread = threading.Thread(target=self._stderr_drain, daemon=True)

        self.stdin_thread.start()
        self.stdout_thread.start()
        self.stderr_thread.start()

        logger.info(f"Orchestrator {self.conversation_id} started with PID {self.process.pid}")
    
    def _stdin_writer(self) -> None:
        """Thread that reads from message_queue and writes to subprocess stdin."""
        if not self.process or not self.process.stdin:
            return
        
        try:
            while not self.stop_event.is_set():
                try:
                    message = self.message_queue.get(timeout=0.5)
                except Empty:
                    continue
                
                # Encode as stream-json user event. The claude 2.x CLI expects
                # the payload's ``message`` field to be a full message object
                # (role + content), not a bare string — bare strings produce
                # "Expected message role 'user', got 'undefined'" and abort.
                event = {
                    "type": "user",
                    "message": {"role": "user", "content": message},
                }
                line = json.dumps(event) + "\n"
                
                try:
                    self.process.stdin.write(line.encode('utf-8'))
                    self.process.stdin.flush()
                    logger.debug(f"Sent message to orchestrator {self.conversation_id}: {message[:50]}...")
                except (BrokenPipeError, IOError) as e:
                    logger.error(f"Failed to write to orchestrator {self.conversation_id}: {e}")
                    break
                
        except Exception as e:
            logger.error(f"stdin_writer thread error for {self.conversation_id}: {e}")
        finally:
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass

    def _stderr_drain(self) -> None:
        """Thread that drains subprocess stderr to prevent pipe-buffer deadlock.

        With --verbose, claude writes a steady stream of diagnostic lines to
        stderr. If nothing reads them, the OS pipe buffer (~64 KB) fills and
        the subprocess blocks on its next stderr write — freezing the reply
        mid-stream. Forward each line to the relay logger at DEBUG level so
        the bytes are consumed and occasionally surfaced when someone is
        actually looking.
        """
        if not self.process or not self.process.stderr:
            return
        try:
            for line in iter(self.process.stderr.readline, b''):
                if self.stop_event.is_set():
                    break
                if not line:
                    continue
                try:
                    decoded = line.decode('utf-8', errors='replace').rstrip()
                    if decoded:
                        logger.debug(
                            f"[orchestrator {self.conversation_id} stderr] {decoded}"
                        )
                except Exception:
                    # Never let a decode error crash the drain — any error
                    # here means the pipe fills and the subprocess freezes.
                    pass
        except Exception as e:
            logger.error(f"stderr_drain thread error for {self.conversation_id}: {e}")
        finally:
            if self.process and self.process.stderr:
                try:
                    self.process.stderr.close()
                except Exception:
                    pass

    def _stdout_reader(self) -> None:
        """Thread that reads stdout and publishes events via broadcaster."""
        if not self.process or not self.process.stdout:
            return
        
        try:
            for line in iter(self.process.stdout.readline, b''):
                if self.stop_event.is_set():
                    break
                
                if not line:
                    continue
                
                try:
                    # Handle both bytes (real subprocess) and str (mocked StringIO)
                    line_str: str
                    if isinstance(line, bytes):
                        line_str = line.decode('utf-8')
                    else:
                        line_str = line
                    event = json.loads(line_str)
                    event_type = event.get("type")

                    # Publish tokens and final assistant messages.
                    #
                    # Event shapes emitted by claude 2.x --output-format=stream-json:
                    #   - {"type":"stream_event","event":{"type":"content_block_delta",
                    #       "delta":{"type":"text_delta","text":"..."}}}   ← streaming tokens
                    #   - {"type":"assistant","message":{"content":[
                    #       {"type":"text","text":"..."},{"type":"tool_use",...}]}}
                    #   - {"type":"system","subtype":"init"|"status",...}  ← skip
                    #   - {"type":"user",...}  ← --replay-user-messages echo, skip
                    #   - {"type":"result",...}  ← turn-end, skip
                    if event_type == "stream_event":
                        inner = event.get("event") or {}
                        if inner.get("type") == "content_block_delta":
                            delta = inner.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    # Buffer for partial-flush-on-exit; stamp
                                    # the turn start so a crash-flushed row
                                    # has a stable created_at.
                                    if not self._pending_text_parts:
                                        self._pending_started_at = (
                                            datetime.now(timezone.utc).isoformat()
                                        )
                                    self._pending_text_parts.append(text)
                                    asyncio.run_coroutine_threadsafe(
                                        self.broadcaster.publish(
                                            self.run_id,
                                            {
                                                "type": "chat_message_token",
                                                "content": text,
                                                "conversation_id": self.conversation_id,
                                            },
                                        ),
                                        self.event_loop,
                                    )
                    elif event_type == "assistant":
                        # Concatenate all text blocks in the message; skip tool_use blocks.
                        msg = event.get("message") or {}
                        content = msg.get("content") or []
                        text_parts: list[str] = []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                        elif isinstance(content, str):
                            # Defensive: some CLI versions or tests emit a bare string.
                            text_parts.append(content)
                        text = "".join(text_parts)
                        if text:
                            # Final assistant message supersedes the streaming
                            # buffer — drop any accumulated tokens so
                            # _flush_partial doesn't double-persist on shutdown.
                            self._pending_text_parts = []
                            self._pending_started_at = None
                            # Persist the assistant reply so a page reload
                            # (GET /api/workflows/{run_id}/chat/history) shows
                            # it alongside the operator messages. Operator
                            # turns are persisted in chat_routes.post_chat;
                            # the assistant side lives in the relay because
                            # that's where the reply is assembled.
                            now = datetime.now(timezone.utc).isoformat()
                            try:
                                insert_chat_message(
                                    self.db_path,
                                    execution_id=None,
                                    role="agent",
                                    content=text,
                                    created_at=now,
                                    run_id=self.run_id,
                                    conversation_id=self.conversation_id,
                                    session_id=self.session_uuid,
                                )
                            except Exception as e:
                                # Persistence is best-effort — never drop the
                                # SSE broadcast because the DB write failed.
                                logger.error(
                                    f"Failed to persist assistant message for "
                                    f"{self.conversation_id}: {e}"
                                )
                            asyncio.run_coroutine_threadsafe(
                                self.broadcaster.publish(
                                    self.run_id,
                                    {
                                        "type": "chat_message",
                                        "role": "assistant",
                                        "content": text,
                                        "conversation_id": self.conversation_id,
                                        "created_at": now,
                                    },
                                ),
                                self.event_loop,
                            )
                    # Skip system/user/result/tool_use/etc.

                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON stdout line from orchestrator {self.conversation_id}: {line!r}")
                except Exception as e:
                    logger.error(f"Error processing stdout line for {self.conversation_id}: {e}")
            
        except Exception as e:
            logger.error(f"stdout_reader thread error for {self.conversation_id}: {e}")
        finally:
            # If the subprocess died (or we're being torn down) mid-stream,
            # persist whatever tokens we accumulated so the partial reply
            # survives a reload instead of disappearing silently.
            self._flush_partial_if_any(reason="stream_ended_without_final_assistant")
            if self.process and self.process.stdout:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass

    def _flush_partial_if_any(self, *, reason: str) -> None:
        """Persist buffered tokens as a partial chat_messages row, then reset.

        Called from the stdout reader's finally block so any accumulated
        stream is preserved when the subprocess exits without emitting a
        final "assistant" event (TTL eviction, crash, SIGKILL). Tagged
        metadata.partial=true so the UI (or any consumer) can render an
        "interrupted" affordance.
        """
        if not self._pending_text_parts:
            return
        text = "".join(self._pending_text_parts)
        started_at = self._pending_started_at or datetime.now(timezone.utc).isoformat()
        # Reset state BEFORE the DB call so a re-entrant error doesn't loop.
        self._pending_text_parts = []
        self._pending_started_at = None
        try:
            insert_chat_message(
                self.db_path,
                execution_id=None,
                role="agent",
                content=text,
                created_at=started_at,
                run_id=self.run_id,
                conversation_id=self.conversation_id,
                session_id=self.session_uuid,
                metadata={"partial": True, "reason": reason},
            )
            logger.info(
                f"Flushed partial orchestrator reply for {self.conversation_id} "
                f"({len(text)} chars, reason={reason})"
            )
        except Exception as e:
            logger.error(
                f"Failed to flush partial reply for {self.conversation_id}: {e}"
            )

    def send_message(self, message: str) -> None:
        """Queue a user message to be sent to the orchestrator."""
        self.message_queue.put(message)
        self.last_active = time.time()
    
    def stop(self) -> None:
        """Gracefully stop the orchestrator subprocess."""
        if not self.process:
            return
        
        logger.info(f"Stopping orchestrator {self.conversation_id}")
        self.stop_event.set()
        
        # Terminate process
        try:
            self.process.terminate()
            # Wait up to 5 seconds
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning(f"Orchestrator {self.conversation_id} did not terminate, killing")
            self.process.kill()
            self.process.wait()
        except Exception as e:
            logger.error(f"Error stopping orchestrator {self.conversation_id}: {e}")
        
        # Wait for threads
        if self.stdin_thread and self.stdin_thread.is_alive():
            self.stdin_thread.join(timeout=2)
        if self.stdout_thread and self.stdout_thread.is_alive():
            self.stdout_thread.join(timeout=2)
        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=2)

        self.process = None
        logger.info(f"Orchestrator {self.conversation_id} stopped")
    
    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def get_idle_seconds(self) -> float:
        """Get seconds since last activity."""
        return time.time() - self.last_active
