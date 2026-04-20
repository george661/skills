"""Pytest fixtures for integration tests."""
import os
import subprocess
import time
import pytest
import requests


@pytest.fixture(scope="module")
def dashboard_server():
    """Start dag-dashboard server for integration tests.
    
    Only runs if PLAYWRIGHT_E2E=1 (same condition as test module).
    """
    if os.getenv("PLAYWRIGHT_E2E") != "1":
        pytest.skip("Server fixture skipped (PLAYWRIGHT_E2E != 1)")
    
    # Start server in subprocess
    env = os.environ.copy()
    env["DAG_DASHBOARD_PORT"] = "8100"
    env["DAG_DASHBOARD_DB_DIR"] = "/tmp/dag-dashboard-test"
    
    process = subprocess.Popen(
        ["python", "-m", "dag_dashboard"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Wait for server to be ready (max 10 seconds)
    for _ in range(20):
        try:
            response = requests.get("http://localhost:8100/health", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            time.sleep(0.5)
    else:
        process.kill()
        pytest.fail("Dashboard server did not start within 10 seconds")
    
    yield
    
    # Cleanup
    process.kill()
    process.wait()


@pytest.fixture
def page(dashboard_server):
    """Provide Playwright page with running server."""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        yield page
        page.close()
        browser.close()
