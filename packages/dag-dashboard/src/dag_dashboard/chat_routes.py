"""Chat REST routes for operator-agent communication."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status

from .models import ChatMessageRequest
from .queries import (
    insert_chat_message,
    check_rate_limit,
    get_run,
    get_node,
    get_conversation_row,
    list_conversations,
    list_runs_in_conversation,
    get_conversation_id_from_run,
    get_orchestrator_session,
)
from .session_transcript import read_session_transcript


def _orchestrator_history_for_run(
    db_path: Path, run_id: str, limit: int, offset: int
) -> List[Dict[str, Any]]:
    """Read chat history for the orchestrator conversation bound to a run.

    Claude persists every turn to its session JSONL under
    ``~/.claude/projects/<cwd-slug>/<session_uuid>.jsonl``; we resolve
    ``run_id -> conversation_id -> session_uuid`` and read from there
    instead of duplicating the transcript in the ``chat_messages`` table.
    Returns an empty list when the conversation hasn't produced any turns
    yet (no session file exists).
    """
    conversation_id = get_conversation_id_from_run(db_path, run_id)
    if not conversation_id:
        return []
    session_row = get_orchestrator_session(db_path, conversation_id)
    if not session_row or not session_row.get("session_uuid"):
        return []
    rows = read_session_transcript(session_row["session_uuid"])
    if offset:
        rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    return rows


def _orchestrator_history_for_conversation(
    db_path: Path, conversation_id: str, limit: int, offset: int
) -> List[Dict[str, Any]]:
    """Read full chat history for a conversation across all its runs."""
    session_row = get_orchestrator_session(db_path, conversation_id)
    if not session_row or not session_row.get("session_uuid"):
        return []
    rows = read_session_transcript(session_row["session_uuid"])
    if offset:
        rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    return rows


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

        # Look up conversation_id so orchestrator routing sees a consistent
        # linkage. GW-5497 guarantees this is populated for any run
        # triggered from the dashboard.
        conversation_id = get_conversation_id_from_run(db_path, run_id)

        # Insert an audit/rate-limit record. The chat_messages table is NOT
        # the conversation transcript anymore — that's the claude session
        # JSONL, read by /chat/history. But we still record each operator
        # POST here so check_rate_limit has something to count and so we
        # have an on-dashboard audit trail of who sent what when. Agent
        # replies are intentionally absent; reading them back from JSONL
        # (one source of truth) is what /chat/history does.
        now = datetime.now(timezone.utc).isoformat()
        insert_chat_message(
            db_path,
            execution_id=None,
            role="operator",
            content=message.content,
            created_at=now,
            run_id=run_id,
            operator_username=message.operator_username,
            conversation_id=conversation_id,
        )

        # Broadcast via SSE so live subscribers see the operator message
        # immediately.
        if hasattr(request.app.state, "broadcaster"):
            await request.app.state.broadcaster.publish(
                run_id,
                {
                    "type": "chat_message",
                    "run_id": run_id,
                    "role": "operator",
                    "content": message.content,
                    "operator_username": message.operator_username,
                    "created_at": now
                }
            )

        # Route to orchestrator if available
        if (
            hasattr(request.app.state, "orchestrator_manager")
            and request.app.state.orchestrator_manager
            and conversation_id
        ):
            try:
                await request.app.state.orchestrator_manager.route_message(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    message=message.content,
                )
            except Exception as e:
                # Don't fail the request if orchestrator routing fails
                import logging
                logging.getLogger(__name__).error(f"Failed to route message to orchestrator: {e}")

        return {
            "content": message.content,
            "role": "operator",
            "operator_username": message.operator_username,
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
            await request.app.state.broadcaster.publish(
                run_id,
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
            "operator_username": message.operator_username,
            "created_at": now
        }

    @router.get("/{run_id}/chat/history")
    async def get_chat_history(
        run_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return orchestrator chat history for a workflow run.

        History is the claude session transcript for the conversation this
        run is bound to. When the conversation has spanned multiple runs
        (continuation), all turns across those runs are returned — the
        transcript is conversation-scoped, not run-scoped, because that
        matches how the LLM reasons about the thread.
        """
        return _orchestrator_history_for_run(db_path, run_id, limit, offset)

    return router


def create_conversation_router(db_path: Path) -> APIRouter:
    """Create conversation router with database dependency.

    Args:
        db_path: Path to SQLite database

    Returns:
        Configured API router
    """
    router = APIRouter(prefix="/api/conversations", tags=["conversations"])

    @router.get("")
    async def list_conversations_endpoint(
        limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List conversations ordered by most-recent activity."""
        return list_conversations(db_path, limit=limit, offset=offset)

    @router.get("/{conversation_id}")
    async def get_conversation_detail(conversation_id: str) -> Dict[str, Any]:
        """Return conversation metadata and the runs that belong to it."""
        conversation = get_conversation_row(db_path, conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found",
            )
        conversation["runs"] = list_runs_in_conversation(db_path, conversation_id)
        return conversation

    @router.get("/{conversation_id}/messages")
    async def get_conversation_messages(
        conversation_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get paginated chat history for a conversation across all runs.

        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return (default 50)
            offset: Number of messages to skip (default 0)

        Returns:
            List of chat messages in chronological order

        Raises:
            HTTPException: 404 if conversation not found
        """
        # Check conversation exists
        conversation = get_conversation_row(db_path, conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation {conversation_id} not found"
            )

        return _orchestrator_history_for_conversation(
            db_path, conversation_id, limit, offset
        )

    return router
