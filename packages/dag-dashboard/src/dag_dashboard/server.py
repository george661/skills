"""FastAPI server for dag-dashboard."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import ensure_dir, init_db
from .routes import router


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

    # Store db_dir in app state for lifespan and route access
    app.state.db_dir = db_dir

    # Register routes
    app.include_router(router)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/")
    async def root() -> FileResponse:
        """Serve index.html at root path."""
        static_dir = Path(__file__).parent / "static"
        index_path = static_dir / "index.html"
        if not index_path.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(index_path)

    return app
