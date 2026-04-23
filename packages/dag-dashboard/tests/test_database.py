"""Tests for database initialization and schema."""
import sqlite3
from pathlib import Path
from dag_dashboard.database import ensure_dir, init_db


def test_ensure_dir_creates_with_0700(tmp_path: Path) -> None:
    """ensure_dir should create directory with 0700 permissions."""
    db_dir = tmp_path / "test-dashboard"
    ensure_dir(db_dir)
    
    assert db_dir.exists()
    assert db_dir.is_dir()
    
    # Check permissions (0700 = user rwx only)
    mode = db_dir.stat().st_mode & 0o777
    assert mode == 0o700


def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    """init_db should create all required tables."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check all tables exist (exclude sqlite_sequence which is auto-created)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    expected_tables = [
        'artifacts',
        'channel_states',
        'chat_messages',
        'conversations',
        'dashboard_settings',
        'events',
        'gate_decisions',
        'node_executions',
        'node_logs',
        'sessions',
        'slack_threads',
        'workflow_runs'
    ]

    assert tables == expected_tables
    conn.close()


def test_init_db_sets_wal_mode(tmp_path: Path) -> None:
    """init_db should enable WAL mode for concurrent reads."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    
    assert mode.lower() == "wal"
    conn.close()


def test_init_db_sets_file_permissions(tmp_path: Path) -> None:
    """init_db should set database file permissions to 0600."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Check permissions (0600 = user rw only)
    mode = db_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    """Running init_db twice should not raise errors."""
    db_path = tmp_path / "test.db"

    # First run
    init_db(db_path)

    # Second run should not error
    init_db(db_path)

    # Verify tables still exist (exclude sqlite_sequence)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
    count = cursor.fetchone()[0]
    assert count == 12  # Updated to 12 to include conversations and sessions tables
    conn.close()


def test_migration_adds_token_breakdown_columns(tmp_path: Path) -> None:
    """Migration should add tokens_input, tokens_output, tokens_cache columns to node_executions."""
    db_path = tmp_path / "old-schema.db"

    # Create a minimal old-schema DB without the new columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            tokens INTEGER,
            cost REAL
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new columns exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'tokens_input' in columns
    assert 'tokens_output' in columns
    assert 'tokens_cache' in columns
    # Old tokens column should still exist for back-compat
    assert 'tokens' in columns
    conn.close()


def test_migration_adds_artifact_url_column(tmp_path: Path) -> None:
    """Migration should add url column to artifacts table."""
    db_path = tmp_path / "old-artifacts.db"

    # Create a minimal old-schema DB without the url column
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT,
            content TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify url column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(artifacts)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'url' in columns
    conn.close()


def test_migration_adds_checkpoint_columns(tmp_path: Path) -> None:
    """Migration should add content_hash and input_versions columns to node_executions."""
    db_path = tmp_path / "old-checkpoint.db"

    # Create a minimal old-schema DB without checkpoint columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new columns exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'content_hash' in columns
    assert 'input_versions' in columns
    conn.close()


def test_init_db_is_idempotent_and_adds_cache_hit_column_to_legacy_db(tmp_path: Path) -> None:
    """init_db should add cache_hit column to legacy DBs and be idempotent."""
    db_path = tmp_path / "legacy.db"

    # Create a legacy DB without cache_hit column
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

    # Run init_db (should add cache_hit column)
    init_db(db_path)

    # Verify cache_hit column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'cache_hit' in columns
    conn.close()

    # Run init_db again (should not error — idempotent)
    init_db(db_path)

    # Verify cache_hit column still exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'cache_hit' in columns
    conn.close()


def test_migration_adds_conversation_id_to_chat_messages(tmp_path: Path) -> None:
    """Migration should add conversation_id column to chat_messages."""
    db_path = tmp_path / "old-chat.db"

    # Create minimal old-schema DB without conversation_id
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata TEXT,
            run_id TEXT,
            operator_username TEXT
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(chat_messages)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'conversation_id' in columns
    conn.close()


def test_migration_adds_session_id_to_chat_messages(tmp_path: Path) -> None:
    """Migration should add session_id column to chat_messages."""
    db_path = tmp_path / "old-chat2.db"

    # Create minimal old-schema DB without session_id
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata TEXT,
            run_id TEXT,
            operator_username TEXT
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(chat_messages)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'session_id' in columns
    conn.close()


def test_migration_adds_conversation_id_to_workflow_runs(tmp_path: Path) -> None:
    """Migration should add conversation_id column to workflow_runs."""
    db_path = tmp_path / "old-runs.db"

    # Create minimal old-schema DB without conversation_id
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(workflow_runs)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'conversation_id' in columns
    conn.close()


def test_migration_creates_conversations_table(tmp_path: Path) -> None:
    """Migration should create conversations table with proper schema."""
    db_path = tmp_path / "new-conversations.db"

    # Start with empty database
    conn = sqlite3.connect(db_path)
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify conversations table exists with correct columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(conversations)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type

    assert 'id' in columns
    assert 'created_at' in columns
    assert 'closed_at' in columns
    assert 'origin' in columns
    conn.close()


def test_migration_creates_sessions_table(tmp_path: Path) -> None:
    """Migration should create sessions table with proper schema and index."""
    db_path = tmp_path / "new-sessions.db"

    # Start with empty database
    conn = sqlite3.connect(db_path)
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify sessions table exists with correct columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type

    assert 'id' in columns
    assert 'conversation_id' in columns
    assert 'parent_session_id' in columns
    assert 'transition_reason' in columns
    assert 'created_at' in columns
    assert 'active' in columns

    # Verify index exists
    cursor.execute("PRAGMA index_list(sessions)")
    indexes = [row[1] for row in cursor.fetchall()]
    assert 'idx_sessions_conv' in indexes

    conn.close()


def test_init_db_is_idempotent_with_new_schema(tmp_path: Path) -> None:
    """Running init_db twice with new schema should not error."""
    db_path = tmp_path / "idempotent-new.db"

    # First run
    init_db(db_path)

    # Second run should not fail
    init_db(db_path)

    # Verify tables still exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    assert 'conversations' in tables
    assert 'sessions' in tables
    assert 'chat_messages' in tables
    assert 'workflow_runs' in tables
    conn.close()


def test_future_prp009_migration_is_additive_only(tmp_path: Path) -> None:
    """Simulates PRP-009 migration landing after PRP-010 (GW-5303).

    GW-5323: Ensures that future PRP-009 (GW-5269) migration that adds
    source/source_ref columns is purely additive and does NOT modify
    existing conversation_id/session_id values.

    This test encodes the coordination contract: PRP-009's migration MUST
    use ALTER TABLE ADD COLUMN and MUST NOT backfill or overwrite
    conversation_id or session_id columns.
    """
    db_path = tmp_path / "prp009-additive.db"

    # Step 1: Initialize DB with PRP-010 schema (conversation_id, session_id)
    init_db(db_path)

    # Step 2: Insert a test row with non-null conversation_id and session_id
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    test_conversation_id = "test-conv-123"
    test_session_id = "test-session-456"
    cursor.execute(
        "INSERT INTO chat_messages (role, content, created_at, conversation_id, session_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("user", "test message", "2026-04-23T00:00:00Z", test_conversation_id, test_session_id)
    )
    conn.commit()

    # Get the auto-generated ID
    msg_id = cursor.lastrowid

    # Step 3: Simulate future PRP-009 migration (ALTER TABLE ADD COLUMN)
    try:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN source_ref TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.commit()

    # Step 4: Assert that conversation_id and session_id are PRESERVED
    cursor.execute(
        "SELECT conversation_id, session_id FROM chat_messages WHERE id = ?",
        (msg_id,)
    )
    row = cursor.fetchone()

    assert row is not None, "Test row disappeared after PRP-009 migration"
    assert row[0] == test_conversation_id, (
        f"conversation_id was modified: expected {test_conversation_id}, got {row[0]}"
    )
    assert row[1] == test_session_id, (
        f"session_id was modified: expected {test_session_id}, got {row[1]}"
    )

    # Step 5: Verify new columns exist
    cursor.execute("PRAGMA table_info(chat_messages)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'source' in columns
    assert 'source_ref' in columns
    assert 'conversation_id' in columns
    assert 'session_id' in columns

    conn.close()


def test_web_origin_source_ref_rule_documented(tmp_path: Path) -> None:
    """Verifies coordination docstring exists in database.py.

    GW-5323: Ensures the coordination rule for web-origin rows is documented
    so the future GW-5269 implementer understands:
    - For web-origin: source='web', source_ref=hostname, conversation_id is dedicated
    - For slack-origin: source='slack', source_ref=thread_ts
    - For cli-origin: source='cli', source_ref=hostname

    This is a documentation contract test.
    """
    from dag_dashboard import database

    # Check module-level docstring exists and contains coordination rule
    module_doc = database.__doc__
    assert module_doc is not None, "database.py module docstring is missing"

    # Required keywords that must appear in the coordination documentation
    required_keywords = [
        "GW-5269",  # Reference to the sibling PRP issue
        "source",   # Column name
        "source_ref",  # Column name
        "conversation_id",  # Column name
        "web",  # Origin type
    ]

    module_doc_lower = module_doc.lower()
    missing_keywords = [kw for kw in required_keywords if kw.lower() not in module_doc_lower]

    assert not missing_keywords, (
        f"Coordination rule not documented in database.py. "
        f"Missing keywords: {missing_keywords}. "
        f"See GW-5323 implementation plan for required documentation."
    )


def test_merge_order_convergence(tmp_path: Path) -> None:
    """Verifies schema converges regardless of PRP merge order.

    GW-5323: Tests both merge orders produce identical final schema:
    - Order A: PRP-010 first (init_db with conversation_id/session_id),
               then PRP-009 (ALTER ADD source/source_ref)
    - Order B: Simulated empty DB with PRP-009 columns → then PRP-010 (init_db)

    Both orders should result in the same column set on chat_messages.
    """
    # Order A: PRP-010 first, then simulated PRP-009
    db_a = tmp_path / "order-a.db"
    init_db(db_a)
    conn_a = sqlite3.connect(db_a)
    cursor_a = conn_a.cursor()

    try:
        cursor_a.execute("ALTER TABLE chat_messages ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor_a.execute("ALTER TABLE chat_messages ADD COLUMN source_ref TEXT")
    except sqlite3.OperationalError:
        pass

    conn_a.commit()

    cursor_a.execute("PRAGMA table_info(chat_messages)")
    schema_a = {row[1] for row in cursor_a.fetchall()}
    conn_a.close()

    # Order B: Simulated PRP-009 first (same base schema as init_db creates),
    # then PRP-010 (init_db which is idempotent)
    db_b = tmp_path / "order-b.db"
    conn_b = sqlite3.connect(db_b)
    cursor_b = conn_b.cursor()

    # Create chat_messages table matching the base schema from database.py
    cursor_b.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT REFERENCES node_executions(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata TEXT,
            run_id TEXT REFERENCES workflow_runs(id),
            operator_username TEXT
        )
    """)

    # Simulate PRP-009 columns added first
    cursor_b.execute("ALTER TABLE chat_messages ADD COLUMN source TEXT")
    cursor_b.execute("ALTER TABLE chat_messages ADD COLUMN source_ref TEXT")
    conn_b.commit()
    conn_b.close()

    # Now run init_db which will add PRP-010 columns (conversation_id, session_id)
    init_db(db_b)
    conn_b = sqlite3.connect(db_b)
    cursor_b = conn_b.cursor()

    cursor_b.execute("PRAGMA table_info(chat_messages)")
    schema_b = {row[1] for row in cursor_b.fetchall()}
    conn_b.close()

    # Assert both orders produce the same column set
    assert schema_a == schema_b, (
        f"Schema divergence detected. "
        f"Order A (PRP-010 first) columns: {sorted(schema_a)}. "
        f"Order B (PRP-009 first) columns: {sorted(schema_b)}. "
        f"Difference: {schema_a.symmetric_difference(schema_b)}"
    )
