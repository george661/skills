"""Orchestrator relay: manages a long-lived Claude subprocess per conversation."""
import asyncio
import json
import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from typing import Optional, Any

from .queries import get_run


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
        model: str,
        event_loop: asyncio.AbstractEventLoop,
        dashboard_port: int,
        session_uuid: Optional[str] = None,
    ):
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.db_path = db_path
        self.broadcaster = broadcaster
        self.model = model
        self.event_loop = event_loop
        self.dashboard_port = dashboard_port
        self.session_uuid = session_uuid
        
        self.process: Optional[subprocess.Popen] = None
        self.message_queue: Queue = Queue()
        self.stdin_thread: Optional[threading.Thread] = None
        self.stdout_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.last_active = time.time()
        
    def _build_system_prompt(self) -> Path:
        """Build system prompt file with run context."""
        run = get_run(self.db_path, self.run_id)
        if not run:
            raise ValueError(f"Run {self.run_id} not found")
        
        # TODO: Fetch last 10 events and channel keys from DB
        # For now, use placeholders
        events_json = json.dumps([], indent=2)
        channel_keys_csv = ""
        
        content = SYSTEM_PROMPT_TEMPLATE.format(
            run_id=self.run_id,
            workflow_name=run.get("workflow_name", "unknown"),
            status=run.get("status", "unknown"),
            conversation_id=self.conversation_id,
            events_json=events_json,
            channel_keys_csv=channel_keys_csv,
            port=self.dashboard_port,
        )
        
        # Write to temp file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.system-prompt.txt',
            delete=False,
            prefix=f"orchestrator-{self.conversation_id}-"
        )
        temp_file.write(content)
        temp_file.close()
        
        return Path(temp_file.name)
    
    def start(self) -> None:
        """Spawn the Claude subprocess and start reader/writer threads."""
        if self.process is not None:
            logger.warning(f"Orchestrator for {self.conversation_id} already started")
            return
        
        # Build system prompt
        system_prompt_path = self._build_system_prompt()
        
        # Build command
        cmd = [
            "claude",
            "--bare",
            "--model", self.model,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--replay-user-messages",
            "--permission-mode", "dontAsk",
            "--system-prompt-file", str(system_prompt_path),
            "--allowedTools", "Bash,Read,Grep,Glob",
            "--verbose",
        ]
        
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
        
        # Start threads
        self.stdin_thread = threading.Thread(target=self._stdin_writer, daemon=True)
        self.stdout_thread = threading.Thread(target=self._stdout_reader, daemon=True)
        
        self.stdin_thread.start()
        self.stdout_thread.start()
        
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
                
                # Encode as stream-json user event
                event = {"type": "user", "message": message}
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
                    if isinstance(line, bytes):
                        line = line.decode('utf-8')
                    event = json.loads(line)
                    event_type = event.get("type")
                    
                    # Publish tokens and final messages, skip tool_use
                    if event_type == "token":
                        # Publish token event
                        asyncio.run_coroutine_threadsafe(
                            self.broadcaster.publish(
                                self.run_id,
                                {
                                    "type": "chat_message_token",
                                    "content": event.get("content", ""),
                                    "conversation_id": self.conversation_id,
                                }
                            ),
                            self.event_loop
                        )
                    elif event_type == "assistant":
                        # Publish final message event
                        asyncio.run_coroutine_threadsafe(
                            self.broadcaster.publish(
                                self.run_id,
                                {
                                    "type": "chat_message",
                                    "role": "assistant",
                                    "content": event.get("content", ""),
                                    "conversation_id": self.conversation_id,
                                }
                            ),
                            self.event_loop
                        )
                    # Skip tool_use and other internal events
                    
                except json.JSONDecodeError as e:
                    logger.debug(f"Non-JSON stdout line from orchestrator {self.conversation_id}: {line}")
                except Exception as e:
                    logger.error(f"Error processing stdout line for {self.conversation_id}: {e}")
            
        except Exception as e:
            logger.error(f"stdout_reader thread error for {self.conversation_id}: {e}")
        finally:
            if self.process and self.process.stdout:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
    
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
