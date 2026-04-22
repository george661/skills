"""Search endpoint for dashboard queries."""
import hashlib
import hmac
import sqlite3
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dag_executor.search_local import search_all

from .config import Settings
from .rate_limit import RateLimiter


class SearchResult(BaseModel):
    """Single search result."""
    kind: str = Field(..., description="Result kind: run, node, or event")
    run_id: str = Field(..., description="Workflow run ID")
    snippet: str = Field(..., description="Matched text snippet (≤120 chars)")
    
    # Optional fields depending on kind
    workflow_name: Optional[str] = None
    started_at: Optional[str] = None
    node_name: Optional[str] = None
    event_type: Optional[str] = None


class SearchResponse(BaseModel):
    """Search endpoint response."""
    query: str
    total: int
    results: List[SearchResult]


def build_search_router(
    settings: Settings,
    db_path_provider: Callable[[], Path],
    rate_limiter: Optional[RateLimiter] = None,
    limiter_key: Optional[Callable[[Request], str]] = None
) -> APIRouter:
    """Build search router with auth and rate limiting.
    
    Args:
        settings: Application settings (must have search_token)
        db_path_provider: Callable that returns the database path
        rate_limiter: Optional rate limiter (default: create one with settings.search_rate_limit_per_min)
        limiter_key: Optional custom key function for rate limiting (default: first 8 chars of bearer)
    
    Returns:
        Configured APIRouter
    """
    router = APIRouter()
    
    # Default rate limiter
    if rate_limiter is None:
        rate_limiter = RateLimiter(settings.search_rate_limit_per_min)
    
    # Default limiter key: sha256 hash of bearer token
    if limiter_key is None:
        def limiter_key(request: Request) -> str:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                return hashlib.sha256(token.encode()).hexdigest()[:16]
            return "anonymous"
    
    @router.get("/api/search", response_model=SearchResponse)
    async def search(
        request: Request,
        q: str = Query(..., description="Search query"),
        kinds: str = Query("runs,nodes,events", description="Comma-separated kinds"),
        limit: int = Query(50, ge=1, le=50, description="Max results")
    ) -> SearchResponse:
        """Search across runs, nodes, and events.
        
        Rate limit: 30 requests per minute per bearer token.
        """
        # 503 if search_token not configured
        if settings.search_token is None:
            raise HTTPException(
                status_code=503,
                detail="Search endpoint not configured. Set DAG_DASHBOARD_SEARCH_TOKEN."
            )
        
        # Verify Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header. Expected: Bearer <token>"
            )
        
        token = auth_header[7:]

        # Constant-time token comparison
        if not hmac.compare_digest(token.encode('utf-8'), settings.search_token.encode('utf-8')):
            raise HTTPException(
                status_code=401,
                detail="Invalid bearer token"
            )
        
        # Rate limit check
        source = limiter_key(request)
        if not rate_limiter.is_allowed(source):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Max 30 requests per minute per token."
            )
        
        # Parse kinds
        kinds_list = [k.strip() for k in kinds.split(",")]
        
        # Query database
        db_path = db_path_provider()
        conn = sqlite3.connect(str(db_path))
        
        try:
            raw_results = search_all(conn, q=q, kinds=kinds_list, limit=limit)
            
            # Convert to pydantic models
            results = []
            for r in raw_results:
                result = SearchResult(
                    kind=r["kind"],
                    run_id=r["run_id"],
                    snippet=r["snippet"],
                    workflow_name=r.get("workflow_name"),
                    started_at=r.get("started_at"),
                    node_name=r.get("node_name"),
                    event_type=r.get("event_type")
                )
                results.append(result)
            
            return SearchResponse(
                query=q,
                total=len(results),
                results=results
            )
        finally:
            conn.close()
    
    return router
