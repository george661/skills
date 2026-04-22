"""Pytest fixtures for integration tests."""
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def dashboard_server(request, tmp_path_factory):
    """Start dag-dashboard server for integration tests.

    Only runs if PLAYWRIGHT_E2E=1 (same condition as test module).

    Supports indirect parametrization for fixture injection:
        @pytest.mark.parametrize("dashboard_server", ["gate_pending_workflow"], indirect=True)
    """
    if os.getenv("PLAYWRIGHT_E2E") != "1":
        pytest.skip("Server fixture skipped (PLAYWRIGHT_E2E != 1)")

    # Set up events directory
    tmp_path = tmp_path_factory.mktemp("dag_events")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    db_dir = tmp_path / "db"
    db_dir.mkdir()

    # Copy fixture if specified via indirect param
    if hasattr(request, "param") and request.param:
        fixture_name = request.param
        fixtures_dir = Path(__file__).parent.parent / "fixtures"
        fixture_path = fixtures_dir / f"{fixture_name}.jsonl"
        if fixture_path.exists():
            shutil.copy(fixture_path, events_dir / f"{fixture_name}.jsonl")

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
