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
from typing import Any, Dict, List, Optional, Tuple

from .queries import get_run, get_connection


logger = logging.getLogger(__name__)


SYSTEM_PROMPT_BASE = """
You are a workflow orchestrator assistant for run {run_id} (workflow: {workflow_name}, status: {status}, conversation: {conversation_id}).

Recent events (last 10):
{events_json}

Channel state (most recent value per channel):
{channels_json}

Known paths:
- Workspace dir for this run: {workspace_path}
- Workflow definitions live in: {workflows_dir}

Your default mode is EXPLAIN, not investigate. The events + channel state above
are the primary source of truth. For 90% of operator questions ("why did X
fail?", "what is the workflow doing?", "what does this status mean?") the
answer is already above — just read it and respond. Tool calls are an
escalation, not a first move.

Workspace semantics:
- Every run gets a workspace dir. Many workflows (e.g. `bug`, `validate-epic`)
  are not repo-investigation workflows — their workspace is empty by design,
  and that is NOT a setup error. Do not attempt to populate or "fix" an
  empty workspace.
- Workspace contains a checked-out git tree only when the workflow YAML
  declared `config.git`. If you opened the workspace and found nothing, the
  workflow simply doesn't need a repo to do its job.

You can query run details via: curl http://127.0.0.1:{port}/api/workflows/{run_id}/...
"""

SYSTEM_PROMPT_READONLY_FOOTER = """
Tool allowlist: Bash, Read, Grep, Glob. No Write, no Edit. Your role is analyst only — observe, report, explain. Do not modify state.

Investigation scope rules (HARD — violations waste minutes of operator time):
1. NEVER run `find /`, `find ~`, `find $HOME`, or any other unbounded
   filesystem walk. These are the #1 source of multi-minute hangs. If you
   need to find a file, you already know where to look — see "Known paths"
   above. Outside those, the only acceptable search root is `$PROJECT_ROOT`
   (the operator's dev tree).
2. Default to answering from the events + channel state already in this
   prompt. Reach for shell only when the operator asks for evidence the
   prompt doesn't contain (e.g. "show me the YAML for this gate", "what
   does the bash node script say").
3. If you must `cd`, prefer the run's workspace, then the workflows dir,
   then `$PROJECT_ROOT`. Anywhere else needs explicit operator justification.
"""

SYSTEM_PROMPT_EDITS_FOOTER = """
Tool allowlist: Bash, Read, Write, Edit, Grep, Glob. You may propose and apply fixes when the operator explicitly asks.

Investigation scope rules (HARD — violations waste minutes of operator time):
1. NEVER run `find /`, `find ~`, `find $HOME`, or any other unbounded
   filesystem walk. These are the #1 source of multi-minute hangs. If you
   need to find a file, you already know where to look — see "Known paths"
   above. Outside those, the only acceptable search root is `$PROJECT_ROOT`.
2. Default to answering from the events + channel state already in this
   prompt. Reach for shell only when the operator asks for evidence the
   prompt doesn't contain.

Edit scope rules (follow these — there is no filesystem sandbox):
1. Look at "Known paths" above. The workspace path is your edit scope when
   it contains a checked-out tree. If the workspace is empty (workflow has
   no `config.git`), edits should target the workflows dir or
   `$PROJECT_ROOT/skills` — never wider.
2. NEVER edit files under `packages/dag-dashboard/src/` — that is the
   dashboard's own source; modifying it corrupts the running process you
   are talking to.
3. Do NOT run `git commit`, `git push`, `git reset`, `git checkout <branch>`,
   or any other command that mutates git refs. The operator commits. After
   edits, summarize what you changed and why so the operator can review.
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
        allow_edits: bool = False,
        workflows_dirs: Optional[List[Path]] = None,
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
        # When True the orchestrator gets Write + Edit + no-git-commit rules
        # in the system prompt. See SYSTEM_PROMPT_EDITS_FOOTER for scope.
        self.allow_edits = allow_edits
        # Workflows directories (the YAML source for every workflow this
        # dashboard can run). Injected into the system prompt so the agent
        # never has to `find /` looking for it. None / empty falls back to
        # a placeholder string that documents the unset state.
        self.workflows_dirs: List[Path] = list(workflows_dirs or [])
        
        self.process: Optional[subprocess.Popen[bytes]] = None
        # Queue items are (content, run_id) tuples. run_id is the workflow
        # run that initiated this turn and drives SSE channel routing when
        # the reply streams back. We thread it through per-turn because a
        # single conversation can be reused across runs (continuation), so
        # the spawn-time run_id may be stale by the time the next user
        # message arrives.
        self.message_queue: "Queue[Tuple[str, str]]" = Queue()
        self.stdin_thread: Optional[threading.Thread] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.stderr_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_active = time.time()

        # The run_id attached to the turn currently flowing through the
        # stdout reader. Set when the stdin writer dequeues a message,
        # used by the reader when broadcasting tokens + final reply. Falls
        # back to self.run_id for the pre-first-turn status broadcast.
        self._current_run_id: str = run_id
        
    def _build_system_prompt(self) -> str:
        """Build system prompt string with run context.

        Returns the rendered prompt so it can be passed inline via --system-prompt.
        The claude 2.x CLI does not accept --system-prompt-file; only the inline
        form exists, so we render a string here rather than a temp file.

        The prompt includes:
        - Recent events (last 10) as JSON — so the orchestrator can reason
          about what just happened.
        - Channel state VALUES (not just keys) — so a workflow writing a
          ``workspace: /path/to/worktree`` channel lets the orchestrator
          scope its edits to that directory. Capped at ~8 KB of JSON so a
          pathological workflow with large channel payloads doesn't blow
          the context window.
        - Either a read-only or an edits-enabled footer depending on the
          ``allow_edits`` config flag.
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

        # Fetch channel state — values, not just keys, so the LLM can see
        # path-like values for scoping edits. Order newest-first so if we
        # truncate we keep the most recent context.
        cursor.execute(
            """
            SELECT channel_key, value_json, updated_at
            FROM channel_states
            WHERE run_id = ?
            ORDER BY updated_at DESC
            """,
            (self.run_id,),
        )
        channels_raw = cursor.fetchall()
        conn.close()

        channels: Dict[str, Any] = {}
        for key, value_json, _updated_at in channels_raw:
            if key in channels:
                continue  # ORDER BY newest → first occurrence wins
            try:
                channels[key] = json.loads(value_json) if value_json else None
            except (TypeError, json.JSONDecodeError):
                channels[key] = value_json
        channels_json = json.dumps(channels, indent=2, default=str)
        # Soft cap: if the serialized payload exceeds 8 KB, fall back to
        # keys-only so we don't spend the entire context window on channel
        # dumps. The LLM can then query via curl for specifics.
        if len(channels_json) > 8192:
            channels_json = json.dumps(
                {"_truncated": True, "keys": list(channels.keys())}, indent=2
            )

        # Resolve known paths for the prompt. The workspace path comes from
        # the `workspace` channel (written by the executor at run start);
        # workflows_dir comes from the dashboard's settings, plumbed through
        # OrchestratorManager. Both are best-effort — if missing we emit
        # human-readable placeholders so the agent doesn't try to dereference
        # the literal `{workspace_path}` template.
        workspace_path_str = self._workspace_path_for_prompt(channels)
        workflows_dir_str = (
            str(self.workflows_dirs[0])
            if self.workflows_dirs
            else "(not configured — ask the operator)"
        )

        footer = (
            SYSTEM_PROMPT_EDITS_FOOTER
            if self.allow_edits
            else SYSTEM_PROMPT_READONLY_FOOTER
        )
        return (
            SYSTEM_PROMPT_BASE.format(
                run_id=self.run_id,
                workflow_name=run.get("workflow_name", "unknown"),
                status=run.get("status", "unknown"),
                conversation_id=self.conversation_id,
                events_json=events_json,
                channels_json=channels_json,
                port=self.dashboard_port,
                workspace_path=workspace_path_str,
                workflows_dir=workflows_dir_str,
            )
            + footer
        )

    def _workspace_path_for_prompt(self, channels: Dict[str, Any]) -> str:
        """Return a human-readable description of the run's workspace path.

        Reads the `workspace` channel (set by the executor at run start) when
        present. Returns a placeholder string when the channel is missing or
        non-stringy so the prompt template never embeds a stale truthy-but-
        unusable value.
        """
        ws = channels.get("workspace") if isinstance(channels, dict) else None
        if isinstance(ws, str) and ws.strip():
            return ws
        if isinstance(ws, dict):
            # Some workflows nest the path; accept common shapes.
            for key in ("path", "value", "dir"):
                v = ws.get(key)
                if isinstance(v, str) and v.strip():
                    return v
        return "(not set — workspace channel absent)"

    def _get_workspace_cwd(self) -> Optional[str]:
        """Get workspace path from channel_states to set as cwd.

        Returns the workspace path if present and the directory exists,
        otherwise None (preserves current behavior for workflows without workspaces).
        """
        from pathlib import Path
        import json

        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT value_json
                FROM channel_states
                WHERE run_id = ? AND channel_key = 'workspace'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (self.run_id,),
            )
            row = cursor.fetchone()
            conn.close()

            if not row or not row[0]:
                return None

            # Parse workspace path from channel value
            value = json.loads(row[0])
            workspace_path = value if isinstance(value, str) else value.get("value") if isinstance(value, dict) else None

            if workspace_path and Path(workspace_path).exists():
                logger.info(f"Setting orchestrator cwd to workspace: {workspace_path}")
                return workspace_path
            elif workspace_path:
                logger.warning(f"Workspace path {workspace_path} does not exist, falling back to default cwd")

        except Exception as e:
            logger.warning(f"Failed to query workspace channel: {e}")

        return None

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

        # Tool allowlist: analyst-only by default, edit-capable when the
        # operator opted in via config.orchestrator_allow_edits. The system
        # prompt carries matching scope rules + a no-git-commit instruction;
        # this flag controls the CLI enforcement.
        allowed_tools = (
            "Bash,Read,Write,Edit,Grep,Glob"
            if self.allow_edits
            else "Bash,Read,Grep,Glob"
        )

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
            "--allowedTools", allowed_tools,
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

        # Query workspace channel to set cwd if available
        workspace_cwd = self._get_workspace_cwd()

        # Spawn subprocess
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
            cwd=workspace_cwd if workspace_cwd else None,
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
                    content, turn_run_id = self.message_queue.get(timeout=0.5)
                except Empty:
                    continue

                # Publish the per-turn run_id before writing to stdin so the
                # stdout reader broadcasts the reply back to the right SSE
                # channel even if tokens arrive faster than the stdin flush
                # (unlikely but cheap to guard).
                self._current_run_id = turn_run_id

                # Encode as stream-json user event. The claude 2.x CLI expects
                # the payload's ``message`` field to be a full message object
                # (role + content), not a bare string — bare strings produce
                # "Expected message role 'user', got 'undefined'" and abort.
                event = {
                    "type": "user",
                    "message": {"role": "user", "content": content},
                }
                line = json.dumps(event) + "\n"

                try:
                    self.process.stdin.write(line.encode('utf-8'))
                    self.process.stdin.flush()
                    logger.debug(
                        f"Sent message to orchestrator {self.conversation_id} "
                        f"(run {turn_run_id}): {content[:50]}..."
                    )
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
                    # Publish tokens and final assistant messages back to the
                    # SSE channel for the run_id that initiated THIS turn.
                    # Persistence is handled by claude itself — it writes the
                    # full transcript to ~/.claude/projects/.../<uuid>.jsonl,
                    # which is our source of truth (see session_transcript).
                    if event_type == "stream_event":
                        inner = event.get("event") or {}
                        if inner.get("type") == "content_block_delta":
                            delta = inner.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    asyncio.run_coroutine_threadsafe(
                                        self.broadcaster.publish(
                                            self._current_run_id,
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
                        text_parts: List[str] = []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                        elif isinstance(content, str):
                            # Defensive: some CLI versions or tests emit a bare string.
                            text_parts.append(content)
                        text = "".join(text_parts)
                        if text:
                            now = datetime.now(timezone.utc).isoformat()
                            asyncio.run_coroutine_threadsafe(
                                self.broadcaster.publish(
                                    self._current_run_id,
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
            # No partial-flush on exit: claude persists every token it
            # emitted to its session JSONL, so a mid-stream crash already
            # has an on-disk transcript for /chat/history to read.
            if self.process and self.process.stdout:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass

    def send_message(self, content: str, run_id: str) -> None:
        """Queue a user message to be routed to the orchestrator.

        ``run_id`` is the workflow run that originated this turn. It
        drives SSE channel routing for the reply, which matters because
        a single conversation can be reused across multiple runs — the
        run captured at spawn time is stale by the time the user sends
        a follow-up from a different run page.
        """
        self.message_queue.put((content, run_id))
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
