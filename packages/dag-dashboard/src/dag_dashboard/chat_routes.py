"""Chat REST routes for operator-agent communication."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from .models import ChatMessageRequest
from .queries import (
    insert_chat_message,
    get_workflow_chat_history,
    check_rate_limit,
    get_run,
    get_node,
)


def create_chat_router(db_path: Path) -> APIRouter:
    """Create chat router with database dependency.

    Args:
        db_path: Path to SQLite database

    Returns:
        Configured API router
    """
    router = APIRouter(prefix="/api/workflows", tags=["chat"])

    @router.post("/{run_id}/chat", status_code=status.HTTP_201_CREATED)
    async def post_workflow_chat(
        run_id: str,
        message: ChatMessageRequest,
        request: Request
    ) -> Dict[str, Any]:
        """Post a workflow-level chat message.

        Args:
            run_id: Workflow run ID
            message: Chat message request

        Returns:
            Created message metadata

        Raises:
            HTTPException: 404 if run not found, 429 if rate limited
        """
        # Check run exists
        run = get_run(db_path, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Check rate limit
        if check_rate_limit(db_path, run_id, window_seconds=60, max_messages=10):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded: max 10 messages per minute"
            )

        # Insert message
        now = datetime.now(timezone.utc).isoformat()
        msg_id = insert_chat_message(
            db_path,
            execution_id=None,
            role="operator",
            content=message.content,
            created_at=now,
            run_id=run_id,
            operator_username=message.operator_username
        )

        # Broadcast via SSE if broadcaster available
        if hasattr(request.app.state, "broadcaster"):
            await request.app.state.broadcaster.broadcast(
                f"chat_message_{run_id}",
                {
                    "type": "chat_message",
                    "run_id": run_id,
                    "role": "operator",
                    "content": message.content,
                    "operator_username": message.operator_username,
                    "created_at": now
                }
            )

        return {
            "id": msg_id,
            "content": message.content,
            "role": "operator",
            "created_at": now
        }

    @router.post("/{run_id}/nodes/{node_id}/chat", status_code=status.HTTP_201_CREATED)
    async def post_node_chat(
        run_id: str,
        node_id: str,
        message: ChatMessageRequest,
        request: Request
    ) -> Dict[str, Any]:
        """Post a node-level chat message.

        Args:
            run_id: Workflow run ID
            node_id: Node execution ID
            message: Chat message request

        Returns:
            Created message metadata

        Raises:
            HTTPException: 404 if node not found, 409 if node not executing, 429 if rate limited
        """
        # Check node exists
        node = get_node(db_path, node_id)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

        # Check node is executing
        if node["status"] != "running":
            raise HTTPException(
                status_code=409,
                detail="Cannot send message to non-executing node"
            )

        # Check rate limit
        if check_rate_limit(db_path, run_id, window_seconds=60, max_messages=10):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded: max 10 messages per minute"
            )

        # Insert message
        now = datetime.now(timezone.utc).isoformat()
        msg_id = insert_chat_message(
            db_path,
            execution_id=node_id,
            role="operator",
            content=message.content,
            created_at=now,
            run_id=run_id,
            operator_username=message.operator_username
        )

        # Write to agent via ChatRelay if available
        if hasattr(request.app.state, "chat_relay"):
            relay = request.app.state.chat_relay
            relay.write_to_agent(run_id, node_id, message.content)

        # Broadcast via SSE
        if hasattr(request.app.state, "broadcaster"):
            await request.app.state.broadcaster.broadcast(
                f"chat_message_{run_id}_{node_id}",
                {
                    "type": "chat_message",
                    "run_id": run_id,
                    "node_id": node_id,
                    "role": "operator",
                    "content": message.content,
                    "operator_username": message.operator_username,
                    "created_at": now
                }
            )

        return {
            "id": msg_id,
            "content": message.content,
            "role": "operator",
            "created_at": now
        }

    @router.get("/{run_id}/chat/history")
    async def get_chat_history(
        run_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get paginated chat history for a workflow run.

        Args:
            run_id: Workflow run ID
            limit: Maximum messages to return (default 50)
            offset: Number of messages to skip (default 0)

        Returns:
            List of chat messages
        """
        return get_workflow_chat_history(db_path, run_id, limit, offset)

    return router
