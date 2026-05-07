"""Orchestrator manager: pool of relays with LRU eviction and TTL sweeping."""
import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .orchestrator_relay import OrchestratorRelay
from .queries import (
    get_orchestrator_session,
    upsert_orchestrator_session,
)


logger = logging.getLogger(__name__)


class OrchestratorManager:
    """Manages a pool of orchestrator relays with concurrency cap and TTL."""
    
    def __init__(
        self,
        db_path: Path,
        broadcaster: Any,
        max_concurrent: int = 8,
        idle_ttl_seconds: int = 1800,
        model: Optional[str] = None,
        dashboard_port: int = 8080,
        allow_edits: bool = False,
    ):
        self.db_path = db_path
        self.broadcaster = broadcaster
        self.max_concurrent = max_concurrent
        self.idle_ttl_seconds = idle_ttl_seconds
        self.model = model
        self.dashboard_port = dashboard_port
        self.allow_edits = allow_edits

        self.relays: Dict[str, OrchestratorRelay] = {}
        self.lru: "OrderedDict[str, bool]" = OrderedDict()
        self.lock = asyncio.Lock()
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.sweeper_task: "Optional[asyncio.Task[None]]" = None
    
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture event loop for run_coroutine_threadsafe in relays."""
        self.event_loop = loop
        # Start TTL sweeper
        self.sweeper_task = asyncio.create_task(self._ttl_sweeper())
        logger.info("OrchestratorManager event loop captured, sweeper started")
    
    async def _ttl_sweeper(self) -> None:
        """Background task that evicts idle AND dead relays.

        Idle relays are evicted on the TTL policy. Dead relays (subprocess
        exited for any reason — crash, OOM, operator kill) must also be
        evicted so the next route_message respawns from the persisted
        session instead of queuing into a zombie.
        """
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                async with self.lock:
                    to_evict_idle: List[str] = []
                    to_evict_dead: List[str] = []
                    for conv_id, relay in self.relays.items():
                        if not relay.is_alive():
                            to_evict_dead.append(conv_id)
                        elif relay.get_idle_seconds() > self.idle_ttl_seconds:
                            to_evict_idle.append(conv_id)

                    for conv_id in to_evict_dead:
                        logger.warning(
                            f"Sweeper found dead orchestrator {conv_id}, evicting"
                        )
                        self._evict_locked(conv_id, new_status="exited")
                    for conv_id in to_evict_idle:
                        logger.info(f"TTL evicting orchestrator {conv_id}")
                        self._evict_locked(conv_id, new_status="idle_evicted")
            except Exception as e:
                logger.error(f"TTL sweeper error: {e}")

    async def route_message(
        self,
        conversation_id: str,
        run_id: str,
        message: str,
    ) -> None:
        """Route a message to the orchestrator for this conversation.

        If the cached relay is dead (subprocess exited), evict it and
        respawn from the persisted session (via --resume) before queueing.
        Without this check, a zombie relay swallows messages silently.
        """
        async with self.lock:
            # Liveness check: drop dead relays before anyone writes to them.
            existing = self.relays.get(conversation_id)
            if existing is not None and not existing.is_alive():
                logger.warning(
                    f"Detected dead orchestrator for {conversation_id}, "
                    f"evicting and respawning"
                )
                self._evict_locked(conversation_id, new_status="exited")

            if conversation_id not in self.relays:
                await self._spawn(conversation_id, run_id)

            relay = self.relays[conversation_id]
            # Update LRU order
            self.lru.move_to_end(conversation_id)

        # Send message (outside lock). Pass run_id through so the reply
        # SSE-broadcasts back to the run the user is currently viewing,
        # even when the conversation spans multiple runs (continuation).
        relay.send_message(message, run_id)

    def _evict_locked(self, conversation_id: str, *, new_status: str) -> None:
        """Remove a relay from the pool and update its persisted status.

        Must be called while holding ``self.lock``. ``new_status`` is the
        value written to ``orchestrator_sessions.status`` so the DB row
        reflects why the relay left the pool ("exited", "idle_evicted",
        "lru_evicted", "stopped"). Session UUID is retained for --resume.
        """
        relay = self.relays.pop(conversation_id, None)
        if relay is None:
            return
        self.lru.pop(conversation_id, None)
        try:
            relay.stop()
        except Exception as e:
            logger.error(f"Error stopping relay {conversation_id}: {e}")
        try:
            self._mark_session_status(conversation_id, new_status)
        except Exception as e:
            logger.error(
                f"Failed to update session status for {conversation_id}: {e}"
            )

    def _mark_session_status(self, conversation_id: str, status: str) -> None:
        """Patch orchestrator_sessions.status in-place.

        Preserves all other columns (session_uuid, model, created_at) by
        reading the current row first — the ``upsert_orchestrator_session``
        helper requires every field, so this read-modify-write is the
        straightforward path without introducing a second helper.
        """
        row = get_orchestrator_session(self.db_path, conversation_id)
        if row is None:
            # Pool-only relay without a persisted session row; nothing to do.
            return
        now = datetime.now(timezone.utc).isoformat()
        upsert_orchestrator_session(
            db_path=self.db_path,
            conversation_id=conversation_id,
            session_uuid=row["session_uuid"],
            last_active=now,
            status=status,
            model=row["model"],
            created_at=row["created_at"],
        )
    
    async def _spawn(self, conversation_id: str, run_id: str) -> None:
        """Spawn a new relay, evicting LRU if at capacity."""
        # Check capacity
        if len(self.relays) >= self.max_concurrent:
            # Evict LRU
            lru_conv_id = next(iter(self.lru))
            logger.info(f"Capacity reached, evicting LRU: {lru_conv_id}")
            self._evict_locked(lru_conv_id, new_status="lru_evicted")
        
        # Check for existing session in DB
        session_row = get_orchestrator_session(self.db_path, conversation_id)
        session_uuid = session_row["session_uuid"] if session_row else None
        
        # Create relay
        if not self.event_loop:
            raise RuntimeError("Event loop not set - call set_loop() first")

        relay = OrchestratorRelay(
            conversation_id=conversation_id,
            run_id=run_id,
            db_path=self.db_path,
            broadcaster=self.broadcaster,
            model=self.model,
            event_loop=self.event_loop,
            dashboard_port=self.dashboard_port,
            session_uuid=session_uuid,
            allow_edits=self.allow_edits,
        )
        relay.start()
        
        # Store in pool
        self.relays[conversation_id] = relay
        self.lru[conversation_id] = True
        
        # Persist session UUID
        now = datetime.now(timezone.utc).isoformat()
        upsert_orchestrator_session(
            db_path=self.db_path,
            conversation_id=conversation_id,
            session_uuid=relay.session_uuid or "",  # Should always be set after start()
            last_active=now,
            status="alive",
            # model=None means "inherit ANTHROPIC_MODEL"; record that literal
            # marker so the orchestrator_sessions row is self-describing.
            model=self.model or "env:ANTHROPIC_MODEL",
            created_at=session_row["created_at"] if session_row else now,
        )
        
        logger.info(f"Spawned orchestrator for {conversation_id}, pool size: {len(self.relays)}")
    
    async def get_status(self, run_id: str, conversation_id: str) -> Dict[str, Any]:
        """Get orchestrator status for a run."""
        async with self.lock:
            relay = self.relays.get(conversation_id)
            if relay and relay.is_alive():
                return {
                    "alive": True,
                    "model": relay.model,
                    "idle_seconds": int(relay.get_idle_seconds()),
                    "session_uuid": relay.session_uuid,
                }
            
            # Check DB for evicted session
            session_row = get_orchestrator_session(self.db_path, conversation_id)
            if session_row:
                return {
                    "alive": False,
                    "model": session_row["model"],
                    "idle_seconds": 0,
                    "session_uuid": session_row["session_uuid"],
                }
            
            return {"alive": False, "model": None, "idle_seconds": 0, "session_uuid": None}
    
    async def stop_all(self) -> None:
        """Stop all relays (called during shutdown)."""
        if self.sweeper_task:
            self.sweeper_task.cancel()

        async with self.lock:
            # Snapshot ids first — _evict_locked mutates self.relays.
            conv_ids = list(self.relays.keys())
            for conv_id in conv_ids:
                self._evict_locked(conv_id, new_status="stopped")

        logger.info("All orchestrators stopped")
