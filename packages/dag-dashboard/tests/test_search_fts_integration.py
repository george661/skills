"""Integration tests for FTS5 search via API."""
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
import pytest


def test_search_uses_fts_when_flag_enabled_and_index_present(tmp_path: Path) -> None:
    """Search endpoint should use FTS5 when enabled and indexes exist."""
    from dag_dashboard.config import Settings
    from dag_dashboard.server import create_app
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    
    # Create app with FTS5 enabled
    settings = Settings(
        search_token="test-token",
        fts5_enabled=True
    )
    
    app = create_app(
        db_path=db_path,
        settings=settings
    )
    
    # Insert test data
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES ('run-123', 'error', 'rate_limit exceeded', '2024-01-01T00:00:00Z')
    """)
    conn.commit()
    conn.close()
    
    # Test search
    client = TestClient(app)
    response = client.get(
        "/api/search?q=rate_limit&limit=10",
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0
    assert data["results"][0]["kind"] == "event"


def test_search_falls_back_to_like_when_flag_disabled(tmp_path: Path) -> None:
    """Search should use LIKE when FTS5 is disabled."""
    from dag_dashboard.config import Settings
    from dag_dashboard.server import create_app
    
    db_path = tmp_path / "test.db"
    
    # Create app with FTS5 disabled
    settings = Settings(
        search_token="test-token",
        fts5_enabled=False
    )
    
    app = create_app(
        db_path=db_path,
        settings=settings
    )
    
    # Insert test data
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES ('run-456', 'info', 'processing data', '2024-01-01T00:00:00Z')
    """)
    conn.commit()
    conn.close()
    
    # Test search via LIKE path
    client = TestClient(app)
    response = client.get(
        "/api/search?q=processing&limit=10",
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_search_falls_back_when_flag_enabled_but_index_missing(tmp_path: Path) -> None:
    """Search should fall back to LIKE when FTS tables don't exist."""
    from dag_dashboard.config import Settings
    from dag_dashboard.server import create_app
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    
    # Initialize DB without FTS5
    init_db(db_path, fts5_enabled=False)
    
    # Create app with FTS5 enabled (but DB lacks FTS tables)
    settings = Settings(
        search_token="test-token",
        fts5_enabled=True
    )
    
    app = create_app(
        db_path=db_path,
        settings=settings
    )
    
    # Insert test data
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES ('run-789', 'warn', 'cache miss', '2024-01-01T00:00:00Z')
    """)
    conn.commit()
    conn.close()
    
    # Test search - should succeed via LIKE fallback, not 500
    client = TestClient(app)
    response = client.get(
        "/api/search?q=cache&limit=10",
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
