"""FastAPI server for dag-dashboard."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import FastAPI

from .database import ensure_dir, init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize database on startup."""
    db_dir: Path = app.state.db_dir
    ensure_dir(db_dir)
    db_path = db_dir / "dashboard.db"
    init_db(db_path)
    yield


def create_app(db_dir: Path) -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="DAG Dashboard",
        description="Workflow execution monitoring dashboard",
        version="0.1.0",
        lifespan=lifespan
    )
    
    # Store db_dir in app state for lifespan access
    app.state.db_dir = db_dir
    
    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}
    
    return app
