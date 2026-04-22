"""Pytest fixtures for integration tests."""
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import pytest


@pytest.fixture(scope="module")
def dashboard_server(request, tmp_path_factory):
    """Start dag-dashboard server for integration tests.

    Only runs if PLAYWRIGHT_E2E=1 (same condition as test module).

    Supports indirect parametrization for fixture injection:
        @pytest.mark.parametrize("dashboard_server", ["gate_pending_workflow"], indirect=True)

    Fixtures must be .ndjson files (EventCollector filters on extension). They are
    copied AFTER the server starts so the watchdog observer fires a created-event
    and processes the file — files present before the observer starts are ignored.
    """
    if os.getenv("PLAYWRIGHT_E2E") != "1":
        pytest.skip("Server fixture skipped (PLAYWRIGHT_E2E != 1)")

    # Set up events directory
    tmp_path = tmp_path_factory.mktemp("dag_events")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    # Resolve fixture source path BEFORE starting the server, so a missing
    # fixture fails the test rather than silently producing an empty workflow.
    fixture_src: Optional[Path] = None
    fixture_name: Optional[str] = None
    if hasattr(request, "param") and request.param:
        fixture_name = request.param
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        fixture_src = fixtures_dir / f"{fixture_name}.ndjson"
        if not fixture_src.exists():
            pytest.fail(
                f"Fixture {fixture_src} not found. Fixtures must be .ndjson "
                f"(EventCollector ignores other extensions)."
            )

    env = os.environ.copy()
    env["DAG_DASHBOARD_PORT"] = "8100"
    env["DAG_DASHBOARD_DB_DIR"] = str(db_dir)
    env["DAG_DASHBOARD_EVENTS_DIR"] = str(events_dir)

    process = subprocess.Popen(
        ["python", "-m", "dag_dashboard"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready (max 10 seconds)
    ready = False
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://localhost:8100/health", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)

    if not ready:
        process.kill()
        pytest.fail("Dashboard server did not start within 10 seconds")

    # Copy fixture AFTER the observer is running so watchdog sees a
    # file-created event and processes it. Poll the API until the workflow
    # run appears so tests don't race the collector.
    if fixture_src is not None:
        shutil.copy(fixture_src, events_dir / fixture_src.name)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://localhost:8100/api/workflows", timeout=1) as resp:
                    if resp.status == 200:
                        body = resp.read().decode()
                        if fixture_name and fixture_name in body:
                            break
                        # fixture_name may not match the run_id inside the ndjson;
                        # fall through if ANY workflow is present.
                        if '"runs"' in body and '"run_id"' in body:
                            break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.1)

    yield

    process.kill()
    process.wait()


@pytest.fixture(scope="session")
def browser():
    """Provide session-scoped Playwright browser to avoid re-launching per test."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(dashboard_server, browser):
    """Provide Playwright page with running server."""
    page = browser.new_page()
    yield page
    page.close()
