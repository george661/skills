"""Orchestrator manager: pool of relays with LRU eviction and TTL sweeping."""
import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

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
        model: str = "claude-opus-4-7",
        dashboard_port: int = 8080,
    ):
        self.db_path = db_path
        self.broadcaster = broadcaster
        self.max_concurrent = max_concurrent
        self.idle_ttl_seconds = idle_ttl_seconds
        self.model = model
        self.dashboard_port = dashboard_port

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
        """Background task that evicts idle relays."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                async with self.lock:
                    to_evict = []
                    for conv_id, relay in self.relays.items():
                        if relay.get_idle_seconds() > self.idle_ttl_seconds:
                            to_evict.append(conv_id)
                    
                    for conv_id in to_evict:
                        logger.info(f"TTL evicting orchestrator {conv_id}")
                        relay = self.relays.pop(conv_id)
                        self.lru.pop(conv_id, None)
                        relay.stop()
                        # Session UUID retained in DB for resume
            except Exception as e:
                logger.error(f"TTL sweeper error: {e}")
    
    async def route_message(
        self,
        conversation_id: str,
        run_id: str,
        message: str,
    ) -> None:
        """Route a message to the orchestrator for this conversation."""
        async with self.lock:
            # Get or spawn relay
            if conversation_id not in self.relays:
                await self._spawn(conversation_id, run_id)
            
            relay = self.relays[conversation_id]
            # Update LRU order
            self.lru.move_to_end(conversation_id)
        
        # Send message (outside lock)
        relay.send_message(message)
    
    async def _spawn(self, conversation_id: str, run_id: str) -> None:
        """Spawn a new relay, evicting LRU if at capacity."""
        # Check capacity
        if len(self.relays) >= self.max_concurrent:
            # Evict LRU
            lru_conv_id = next(iter(self.lru))
            logger.info(f"Capacity reached, evicting LRU: {lru_conv_id}")
            lru_relay = self.relays.pop(lru_conv_id)
            self.lru.pop(lru_conv_id)
            lru_relay.stop()
            # Session row stays in DB for resume
        
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
            model=self.model,
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
            for relay in self.relays.values():
                relay.stop()
            self.relays.clear()
            self.lru.clear()
        
        logger.info("All orchestrators stopped")
