"""Async broadcast hub connecting event producers to SSE consumers."""
import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Set


class Broadcaster:
    """Manages per-run event subscriptions and broadcasts."""

    def __init__(self) -> None:
        """Initialize broadcaster with empty subscriber map."""
        self._subscribers: Dict[str, Set[asyncio.Queue[Dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[Dict[str, Any]]]:
        """
        Subscribe to events for a specific run_id.
        
        Returns an async context manager that yields a queue.
        The queue receives all events published to this run_id.
        Automatically unsubscribes on context exit.
        """
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        
        # Register subscriber
        async with self._lock:
            if run_id not in self._subscribers:
                self._subscribers[run_id] = set()
            self._subscribers[run_id].add(queue)
        
        try:
            yield queue
        finally:
            # Unregister subscriber
            async with self._lock:
                if run_id in self._subscribers:
                    self._subscribers[run_id].discard(queue)
                    # Clean up empty sets
                    if not self._subscribers[run_id]:
                        del self._subscribers[run_id]

    async def publish(self, run_id: str, event: Dict[str, Any]) -> None:
        """
        Publish an event to all subscribers of a specific run_id.
        
        Events are placed on each subscriber's queue without blocking.
        If a queue is full, the event is skipped for that subscriber.
        """
        async with self._lock:
            subscribers = self._subscribers.get(run_id, set()).copy()
        
        # Put event on all subscriber queues
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Skip slow consumers - they'll miss this event
                pass
