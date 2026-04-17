"""Test SSE endpoint.

Note: Full SSE streaming tests are difficult with TestClient due to infinite
streaming. Manual browser testing is required per validation criteria.
"""
from pathlib import Path
from dag_dashboard.server import create_app
from dag_dashboard.routes import router


def test_sse_route_registered(tmp_path: Path) -> None:
    """Test that SSE route is registered in the API router."""
    app = create_app(tmp_path)

    # Verify the /api/events route exists
    routes = [route.path for route in app.routes]
    assert "/api/events" in routes, "SSE endpoint /api/events not registered"


def test_event_generator_yields_data() -> None:
    """Test that event generator produces SSE-formatted data."""
    from dag_dashboard.routes import event_generator
    import asyncio

    async def test_first_event() -> None:
        gen = event_generator()
        first_chunk = await gen.__anext__()
        assert first_chunk.startswith("data: ")
        assert "\n\n" in first_chunk  # SSE format requires double newline
        assert "connected" in first_chunk or "type" in first_chunk

    asyncio.run(test_first_event())
