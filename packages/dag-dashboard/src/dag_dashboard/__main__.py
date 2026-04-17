"""Entry point for running dag-dashboard server."""
import logging
import uvicorn

from .config import Settings
from .server import create_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the dag-dashboard server."""
    settings = Settings()
    settings.validate_host()

    app = create_app(
        db_dir=settings.db_dir,
        events_dir=settings.events_dir,
        max_sse_connections=settings.max_sse_connections
    )

    logger.info(f"Starting DAG Dashboard on {settings.host}:{settings.port}")
    logger.info(f"Database directory: {settings.db_dir}")
    logger.info(f"Events directory: {settings.events_dir}")
    logger.info(f"Max SSE connections per run: {settings.max_sse_connections}")

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
