"""Performance tests for FTS5 search."""
import sqlite3
import time
from pathlib import Path
import pytest


@pytest.mark.slow
def test_fts5_search_under_100ms_on_10k_runs(tmp_path: Path) -> None:
    """FTS5 search should be <100ms p95 on 10k-run database."""
    from dag_dashboard.database import init_db
    from dag_executor.search_fts import search_all_fts
    
    # Check if FTS5 is available
    conn_test = sqlite3.connect(":memory:")
    cursor = conn_test.cursor()
    cursor.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')")
    fts5_available = cursor.fetchone()[0]
    conn_test.close()
    
    if not fts5_available:
        pytest.skip("FTS5 not available in this SQLite build")
    
    # Create database with FTS5 enabled
    db_path = tmp_path / "perf.db"
    init_db(db_path, fts5_enabled=True)
    
    conn = sqlite3.connect(db_path)
    
    # Seed 10,000 runs + 30,000 events + 20,000 nodes
    print("\nSeeding database...")
    for i in range(10000):
        # Insert workflow run
        conn.execute("""
            INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs, error)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (f"run-{i}", "test_workflow", "completed", "2024-01-01T00:00:00Z",
              f'{{"param": {i}}}', f"error message {i}" if i % 100 == 0 else None))
        
        # 3 events per run
        for j in range(3):
            conn.execute("""
                INSERT INTO events (run_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?)
            """, (f"run-{i}", "info", f"processing data batch {i}-{j}", "2024-01-01T00:00:00Z"))
        
        # 2 nodes per run
        for k in range(2):
            conn.execute("""
                INSERT INTO node_executions (id, run_id, node_name, status, started_at, inputs, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (f"run-{i}-node-{k}", f"run-{i}", f"node_{k}", "completed",
                  "2024-01-01T00:00:00Z", f'{{"x": {k}}}',
                  f"node error {i}" if i % 200 == 0 else None))
    
    conn.commit()
    print("Seeding complete")
    
    # Warm up cache with one query
    search_all_fts(conn, "processing", limit=50)
    
    # Run 5 representative queries and measure latency
    queries = [
        "processing",
        "error",
        "batch",
        "data",
        "workflow"
    ]
    
    latencies = []
    for query in queries:
        start = time.perf_counter()
        results = search_all_fts(conn, query, limit=50)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        latencies.append(elapsed)
        print(f"Query '{query}': {elapsed:.2f}ms ({len(results)} results)")
    
    # Calculate p95
    latencies.sort()
    p95_index = int(len(latencies) * 0.95)
    p95_latency = latencies[p95_index] if p95_index < len(latencies) else latencies[-1]
    
    print(f"\nP95 latency: {p95_latency:.2f}ms")
    
    conn.close()
    
    # Assert p95 < 100ms
    assert p95_latency < 100, f"P95 latency {p95_latency:.2f}ms exceeds 100ms target"
