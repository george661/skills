"""FastAPI server for dag-dashboard."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import RequestResponseEndpoint

from .broadcast import Broadcaster
from .cancel import create_cancel_router
from .retry import create_retry_router
from .chat_relay import ChatRelay
from .chat_routes import create_chat_router, create_conversation_router
from .checkpoint_routes import router as checkpoint_router
from .config import Settings
from .drafts_routes import router as drafts_router
from .validation_routes import router as validation_router
from .database import ensure_dir, init_db
from .event_collector import EventCollector
from .notifier import SlackNotifier
from .search import build_search_router
from .settings_routes import create_settings_router
from .sse import create_sse_router
from .routes import router
from .trigger import create_trigger_router

logger = logging.getLogger(__name__)


def create_app(
    db_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    events_dir: Path = Path("dag-events"),
    pipe_root: Optional[Path] = None,
    max_sse_connections: int = 50,
    slack_notifier: Optional[SlackNotifier] = None,
    dashboard_url: str = "http://127.0.0.1:8100",
    checkpoint_prefix: Optional[Path] = None,
    settings: Optional[Settings] = None,
    checkpoint_dir_fallback: Optional[str] = None,
    workflows_dirs: Optional[List[Path]] = None,
    skills_dirs: Optional[List[Path]] = None,
    cancel_reconcile_timeout_s: float = 3.0,
    cancel_reconcile_poll_interval_s: float = 0.5,
) -> FastAPI:
    """Create and configure FastAPI application."""

    # Initialize database first (before creating app)
    if db_path is None:
        if db_dir is None:
            raise ValueError("Either db_dir or db_path must be provided")
        ensure_dir(db_dir)
        db_path = db_dir / "dashboard.db"
    init_db(db_path, fts5_enabled=settings.fts5_enabled if settings else False)

    # Ensure events directory exists
    ensure_dir(events_dir)

    # Set default pipe_root
    if pipe_root is None:
        pipe_root = Path.home() / ".dag-dashboard" / "chat"

    # Create broadcaster
    broadcaster = Broadcaster()

    # Create chat relay
    chat_relay = ChatRelay(db_path=db_path, pipe_root=pipe_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize event collector on startup."""
        # Store broadcaster, db_path, chat_relay, and checkpoint_dir_fallback in app.state for access by endpoints/tests
        app.state.broadcaster = broadcaster
        app.state.db_path = db_path
        app.state.db_dir = db_dir if db_dir else db_path.parent
        app.state.events_dir = events_dir
        app.state.chat_relay = chat_relay
        app.state.checkpoint_dir_fallback = checkpoint_dir_fallback
        app.state.settings = settings
        # Store workflows_dirs for definitions endpoints.
        # Explicit workflows_dirs kwarg takes precedence (used by tests).
        if workflows_dirs is not None:
            app.state.workflows_dirs = workflows_dirs
        elif settings:
            app.state.workflows_dirs = settings.workflows_dirs
        else:
            app.state.workflows_dirs = [Path("workflows")]

        # Store skills_dirs for skills endpoints.
        # Explicit skills_dirs kwarg takes precedence (used by tests).
        if skills_dirs is not None:
            app.state.skills_dirs = skills_dirs
        elif settings:
            app.state.skills_dirs = settings.skills_dirs
        else:
            app.state.skills_dirs = [Path("skills")]

        # Reload settings from db to pick up dashboard_settings overrides
        if settings:
            settings.reload_from_db(db_path)

        # Create and start event collector
        loop = asyncio.get_running_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop,
            slack_notifier=slack_notifier,
            dashboard_url=dashboard_url,
            node_log_line_cap=settings.node_log_line_cap if settings else 50000,
        )
        collector.start()
        app.state.collector = collector

        logger.info(f"Event collector started, watching {events_dir}")
        logger.info(f"Chat relay initialized, pipe_root: {pipe_root}")

        yield

        # Shutdown: stop collector and chat relay
        collector.stop()
        chat_relay.stop()
        logger.info("Event collector and chat relay stopped")

    app = FastAPI(
        title="DAG Dashboard",
        description="Workflow execution monitoring dashboard",
        version="0.1.0",
        lifespan=lifespan
    )

    # Store db_dir, events_dir, and checkpoint state in app state for lifespan and route access
    app.state.db_path = db_path
    app.state.db_dir = db_dir if db_dir else db_path.parent
    app.state.events_dir = events_dir
    app.state.checkpoint_prefix = checkpoint_prefix
    app.state.checkpoint_dir_fallback = checkpoint_dir_fallback
    app.state.settings = settings

    # Store workflows_dirs up front so routes can access it without waiting for lifespan
    # (TestClient does not always trigger lifespan startup).
    if workflows_dirs is not None:
        app.state.workflows_dirs = workflows_dirs
    elif settings:
        app.state.workflows_dirs = settings.workflows_dirs
    else:
        app.state.workflows_dirs = [Path("workflows")]

    # Store skills_dirs up front so routes can access it without waiting for lifespan
    # (TestClient does not always trigger lifespan startup).
    if skills_dirs is not None:
        app.state.skills_dirs = skills_dirs
    elif settings:
        app.state.skills_dirs = settings.skills_dirs
    else:
        app.state.skills_dirs = [Path("skills")]

    # Register routes
    app.include_router(router)

    # Register checkpoint routes if checkpoint_prefix is set
    if checkpoint_prefix is not None:
        app.include_router(checkpoint_router)

    # Register drafts routes (always mounted - workflow editing)
    app.include_router(drafts_router)

    # Register validation routes (builder feature)
    if settings and settings.builder_enabled:
        app.include_router(validation_router)

    # Register chat routes
    chat_router = create_chat_router(db_path)
    app.include_router(chat_router)

    # Register conversation routes
    conversation_router = create_conversation_router(db_path)
    app.include_router(conversation_router)

    # Register cancel routes (always mounted, core functionality)
    cancel_settings = type('Settings', (), {'events_dir': events_dir})()
    cancel_router = create_cancel_router(
        cancel_settings,
        db_path,
        reconcile_timeout_s=cancel_reconcile_timeout_s,
        reconcile_poll_interval_s=cancel_reconcile_poll_interval_s,
    )
    app.include_router(cancel_router)

    # Register settings routes (always mounted, core functionality)
    if settings:
        settings_router = create_settings_router(settings, db_path)
        app.include_router(settings_router)

    # Register retry routes (requires settings with workflows_dir)
    if settings:
        retry_router = create_retry_router(settings, db_path)
        app.include_router(retry_router)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

    # During active iteration the dashboard ships JS without fingerprinted
    # filenames, which means browsers happily serve a stale cached copy for
    # hours after we restart the server. Send a short-lived Cache-Control on
    # /js and /css so reloads pick up the freshly-deployed bundle without
    # requiring the user to hard-refresh (Cmd+Shift+R).
    @app.middleware("http")
    async def _no_cache_static_assets(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/js/") or path.startswith("/css/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/builder-config.js")
    async def builder_config_js() -> Response:
        """Return inline JavaScript that sets window.DAG_DASHBOARD_BUILDER_ENABLED."""
        enabled = settings.builder_enabled if settings else False
        js_content = f"window.DAG_DASHBOARD_BUILDER_ENABLED = {'true' if enabled else 'false'};"
        return Response(content=js_content, media_type="application/javascript")

    # Stable per-process cache-buster stamp appended to every /js and /css
    # URL in index.html. Changes every server restart so deployed JS updates
    # take effect on a normal page reload — no more "clear cache or the user
    # sees a two-hour-stale ChatPanel" footguns.
    import time as _time_mod
    _asset_version = str(int(_time_mod.time()))

    _static_dir_cache = Path(__file__).parent / "static"
    _index_path_cache = _static_dir_cache / "index.html"

    import re as _re_mod
    _asset_rewrite_re = _re_mod.compile(
        r'((?:src|href)\s*=\s*["\'])(/(?:js|css)/[^"\'?#]+)(["\'])'
    )

    def _rewrite_asset_urls(html: str, version: str) -> str:
        return _asset_rewrite_re.sub(
            lambda m: f'{m.group(1)}{m.group(2)}?v={version}{m.group(3)}',
            html,
        )

    @app.get("/")
    async def root() -> Response:
        """Serve index.html at root path, rewriting /js and /css URLs with a
        per-process version stamp so browsers never serve stale dashboard
        JS after a restart."""
        if not _index_path_cache.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="index.html not found")
        html = _index_path_cache.read_text(encoding="utf-8")
        html = _rewrite_asset_urls(html, _asset_version)
        return Response(
            content=html,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    # Mount SSE router - router has its own state, doesn't need app.state
    sse_router = create_sse_router(
        db_path=db_path,
        broadcaster=broadcaster,
        max_connections=max_sse_connections
    )
    app.include_router(sse_router)

    # Mount trigger router if enabled
    if settings and settings.trigger_enabled:
        trigger_router = create_trigger_router(settings, db_path)
        app.include_router(trigger_router)
        logger.info("Trigger endpoint enabled")

    # Mount search router (always mounted; auth handled by endpoint)
    if settings:
        search_router = build_search_router(
            settings=settings,
            db_path_provider=lambda: db_path
        )
        app.include_router(search_router)
        if settings.search_token:
            logger.info("Search endpoint enabled")
        else:
            logger.info("Search endpoint available but not configured (503)")

    return app
