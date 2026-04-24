"""Tests for drafts_routes.py - REST endpoints for draft management."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app
from dag_dashboard.database import init_db


@pytest.fixture
def workflows_dir(tmp_path):
    """Create a temporary workflows directory."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    return workflows_dir


@pytest.fixture
def app(workflows_dir, tmp_path):
    """Create test app with temporary workflows directory."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    app = create_app(
        db_path=db_path,
        events_dir=events_dir,
        workflows_dirs=[workflows_dir],
        checkpoint_prefix=None,
    )
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


def create_draft(workflows_dir: Path, name: str, timestamp: str, content: str) -> Path:
    """Helper to create a draft file."""
    drafts_dir = workflows_dir / ".drafts" / name
    drafts_dir.mkdir(parents=True, exist_ok=True)
    draft_path = drafts_dir / f"{timestamp}.yaml"
    draft_path.write_text(content)
    return draft_path


# Test 1: List drafts - empty
def test_list_drafts_empty(client):
    """GET /api/workflows/{name}/drafts returns empty list when no drafts exist."""
    response = client.get("/api/workflows/test-workflow/drafts")
    assert response.status_code == 200
    assert response.json() == []


# Test 2: List drafts sorted newest first
def test_list_drafts_sorted_newest_first(client, workflows_dir):
    """Drafts are returned newest-first."""
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "content: old")
    create_draft(workflows_dir, "test-workflow", "20260102T120000_000000Z", "content: middle")
    create_draft(workflows_dir, "test-workflow", "20260103T120000_000000Z", "content: new")
    
    response = client.get("/api/workflows/test-workflow/drafts")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    assert items[0]["timestamp"] == "20260103T120000_000000Z"
    assert items[1]["timestamp"] == "20260102T120000_000000Z"
    assert items[2]["timestamp"] == "20260101T120000_000000Z"


# Test 3: Get draft returns content
def test_get_draft_returns_content(client, workflows_dir):
    """GET /api/workflows/{name}/drafts/{timestamp} returns content and parsed data."""
    content = "name: test\ndescription: A test workflow\n"
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", content)
    
    response = client.get("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 200
    data = response.json()
    assert data["timestamp"] == "20260101T120000_000000Z"
    assert data["content"] == content
    assert data["parsed"]["name"] == "test"
    assert data["parsed"]["description"] == "A test workflow"


# Test 4: Get draft 404 missing
def test_get_draft_404_missing(client):
    """GET returns 404 for non-existent draft."""
    response = client.get("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 404


# Test 5: Get draft 400 invalid timestamp
def test_get_draft_400_invalid_timestamp(client):
    """GET returns 400 for malformed timestamp."""
    response = client.get("/api/workflows/test-workflow/drafts/invalid-timestamp")
    assert response.status_code == 400


def test_get_draft_returns_null_parsed_on_malformed_yaml(client, workflows_dir):
    """GET returns 200 with parsed=null for drafts with invalid YAML."""
    # Create a draft with invalid YAML
    invalid_yaml = "{\ninvalid yaml: [\n"
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", invalid_yaml)

    # GET should return 200 (not 400), with content intact and parsed=null
    response = client.get("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 200

    data = response.json()
    assert data["content"] == invalid_yaml
    assert data["parsed"] is None


# Test 6: Create draft returns timestamp
def test_create_draft_returns_timestamp(client, workflows_dir):
    """POST creates draft and returns valid timestamp."""
    content = "name: test\n"
    response = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": content}
    )
    assert response.status_code == 201
    data = response.json()
    assert "timestamp" in data
    
    # Verify timestamp format: YYYYMMDDTHHMMSS_uuuuuuZ (23 chars)
    ts = data["timestamp"]
    assert len(ts) == 23
    assert ts[8] == "T"
    assert ts[15] == "_"
    assert ts.endswith("Z")
    
    # Verify file exists
    draft_path = workflows_dir / ".drafts" / "test-workflow" / f"{ts}.yaml"
    assert draft_path.exists()
    assert draft_path.read_text() == content


def test_create_draft_no_collision_within_second(client, workflows_dir):
    """Two rapid POSTs get different timestamps and both files exist with correct content."""
    content1 = "name: test1\n"
    content2 = "name: test2\n"

    # Issue two rapid sequential POSTs
    response1 = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": content1}
    )
    response2 = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": content2}
    )

    assert response1.status_code == 201
    assert response2.status_code == 201

    ts1 = response1.json()["timestamp"]
    ts2 = response2.json()["timestamp"]

    # Timestamps must be different (microsecond precision prevents collision)
    assert ts1 != ts2

    # Both files must exist with their original content
    draft_path1 = workflows_dir / ".drafts" / "test-workflow" / f"{ts1}.yaml"
    draft_path2 = workflows_dir / ".drafts" / "test-workflow" / f"{ts2}.yaml"
    assert draft_path1.exists()
    assert draft_path2.exists()
    assert draft_path1.read_text() == content1
    assert draft_path2.read_text() == content2


# Test 7: Create draft prunes to 50
def test_create_draft_prunes_to_50(client, workflows_dir):
    """Creating draft when 50 exist deletes oldest, keeps 50 total."""
    # Create 50 drafts (use new timestamp format with microseconds)
    for i in range(50):
        ts = f"202601{i:02d}T120000_000000Z"
        create_draft(workflows_dir, "test-workflow", ts, f"content: {i}")

    # Create 51st draft
    response = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": "content: new"}
    )
    assert response.status_code == 201
    new_ts = response.json()["timestamp"]

    # Count remaining drafts
    drafts_dir = workflows_dir / ".drafts" / "test-workflow"
    draft_files = list(drafts_dir.glob("*.yaml"))
    assert len(draft_files) == 50

    # Verify oldest deleted (20260100T120000_000000Z)
    oldest_path = drafts_dir / "20260100T120000_000000Z.yaml"
    assert not oldest_path.exists()

    # Verify newest still exists
    newest_path = drafts_dir / f"{new_ts}.yaml"
    assert newest_path.exists()


def test_create_draft_rejects_oversized_content(client):
    """POST with content > 2 MiB returns 422."""
    # Create content that is exactly 2 MiB + 1 byte
    oversized_content = "x" * (2_097_152 + 1)

    response = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": oversized_content}
    )

    assert response.status_code == 422
    assert "content" in response.text.lower() or "too long" in response.text.lower()


# Test 8: Update draft in place
def test_update_draft_inplace(client, workflows_dir):
    """PUT overwrites existing draft."""
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "old content")
    
    new_content = "new content"
    response = client.put(
        "/api/workflows/test-workflow/drafts/20260101T120000_000000Z",
        json={"content": new_content}
    )
    assert response.status_code == 204
    
    # Verify content changed
    draft_path = workflows_dir / ".drafts" / "test-workflow" / "20260101T120000_000000Z.yaml"
    assert draft_path.read_text() == new_content


# Test 9: Update draft 404 missing
def test_update_draft_404_missing(client):
    """PUT returns 404 for non-existent draft."""
    response = client.put(
        "/api/workflows/test-workflow/drafts/20260101T120000_000000Z",
        json={"content": "new content"}
    )
    assert response.status_code == 404


# Test 10: Delete draft 204
def test_delete_draft_204(client, workflows_dir):
    """DELETE removes draft file."""
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "content")
    
    response = client.delete("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 204
    
    # Verify file removed
    draft_path = workflows_dir / ".drafts" / "test-workflow" / "20260101T120000_000000Z.yaml"
    assert not draft_path.exists()


# Test 11: Delete draft 404 missing
def test_delete_draft_404_missing(client):
    """DELETE returns 404 for non-existent draft."""
    response = client.delete("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 404


# Test 12: Publish atomic rename
def test_publish_atomic_rename(client, workflows_dir):
    """POST publish renames draft to canonical workflow file."""
    content = """
name: test-workflow
config:
  checkpoint_prefix: /tmp/test
nodes:
  - id: start
    name: start
    type: prompt
    prompt: "Hello"
"""
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", content)
    
    response = client.post("/api/workflows/test-workflow/drafts/20260101T120000_000000Z/publish")
    assert response.status_code == 200
    data = response.json()
    
    # Verify published path
    canonical_path = workflows_dir / "test-workflow.yaml"
    assert canonical_path.exists()
    assert canonical_path.read_text().strip() == content.strip()
    
    # Verify response
    assert data["published_path"] == str(canonical_path)
    assert data["source_timestamp"] == "20260101T120000_000000Z"


# Test 13: Publish validates schema before rename
def test_publish_validates_schema_before_rename(client, workflows_dir):
    """Publish rejects invalid schema without creating canonical file."""
    # Create canonical file with valid content first
    canonical_path = workflows_dir / "test-workflow.yaml"
    canonical_path.write_text("name: original\nnodes: []\n")
    
    # Create draft with invalid schema (missing required fields)
    invalid_content = "invalid: yaml content without required fields"
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", invalid_content)
    
    response = client.post("/api/workflows/test-workflow/drafts/20260101T120000_000000Z/publish")
    assert response.status_code == 400
    
    # Verify canonical file unchanged
    assert canonical_path.read_text() == "name: original\nnodes: []\n"


# Test 14: Publish invalid YAML
def test_publish_invalid_yaml(client, workflows_dir):
    """Publish rejects malformed YAML."""
    invalid_yaml = "{\ninvalid yaml: [\n"
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", invalid_yaml)
    
    response = client.post("/api/workflows/test-workflow/drafts/20260101T120000_000000Z/publish")
    assert response.status_code == 400
    assert "Invalid YAML syntax" in response.json()["detail"]


# Test 15: Multi-dir collision first wins
def test_multi_dir_collision_first_wins(tmp_path):
    """Draft in first dir shadows same-timestamp draft in second dir."""
    dir_a = tmp_path / "workflows_a"
    dir_b = tmp_path / "workflows_b"
    dir_a.mkdir()
    dir_b.mkdir()
    
    # Create drafts with same timestamp in both dirs
    create_draft(dir_a, "test-workflow", "20260101T120000_000000Z", "content from A")
    create_draft(dir_b, "test-workflow", "20260101T120000_000000Z", "content from B")
    
    # Create app with both dirs
    db_path = tmp_path / "test.db"
    init_db(db_path)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    app = create_app(
        db_path=db_path,
        events_dir=events_dir,
        workflows_dirs=[dir_a, dir_b],
        checkpoint_prefix=None,
    )
    client = TestClient(app)
    
    # GET should return content from A (first dir)
    response = client.get("/api/workflows/test-workflow/drafts/20260101T120000_000000Z")
    assert response.status_code == 200
    assert response.json()["content"] == "content from A"


# Test 16: Path traversal - dotdot
def test_rejects_name_with_dotdot(client):
    """Reject workflow names with .. (path traversal)."""
    # Use a name containing .. that routes to handler (not a pure path segment)
    response = client.get("/api/workflows/test..etc/drafts")
    assert response.status_code == 400


# Test 17: Path traversal - absolute
def test_rejects_absolute_name(client):
    """Reject absolute paths."""
    # Slash in workflow name will be caught by validator (if it routes through)
    # Note: Pure path segments don't route, but this tests the validator logic
    response = client.get("/api/workflows//etc/passwd/drafts")
    assert response.status_code in [400, 404]


# Test 18: Path traversal - slash in name
def test_rejects_name_with_slash(client):
    """Reject names with slash."""
    # FastAPI routing won't match this, but that's acceptable defense
    response = client.post(
        "/api/workflows/foo/bar/drafts",
        json={"content": "test"}
    )
    assert response.status_code in [400, 404]


# Test 19: Path traversal - non-alphanumeric
def test_rejects_non_alphanumeric_name(client):
    """Reject names with special characters."""
    response = client.get("/api/workflows/foo$bar/drafts")
    assert response.status_code == 400
    
    response = client.get("/api/workflows/foo bar/drafts")
    assert response.status_code == 400


# Test 20: Path traversal - dot in name
def test_rejects_name_with_dot(client):
    """Reject names with dots."""
    response = client.get("/api/workflows/foo.yaml/drafts")
    assert response.status_code == 400


# Test 21: Path traversal - invalid timestamp
def test_rejects_invalid_timestamp_traversal(client):
    """Reject timestamp with traversal characters."""
    # Use a malformed timestamp that will fail our pattern validation
    response = client.get("/api/workflows/test-workflow/drafts/20260101..120000")
    assert response.status_code == 400


# Test 22: Create in new dir creates drafts subdir
def test_create_in_new_dir_creates_drafts_subdir(client, workflows_dir):
    """POST creates .drafts/{name}/ when missing."""
    drafts_dir = workflows_dir / ".drafts" / "new-workflow"
    assert not drafts_dir.exists()
    
    response = client.post(
        "/api/workflows/new-workflow/drafts",
        json={"content": "name: new\n"}
    )
    assert response.status_code == 201
    assert drafts_dir.exists()


# Test 23: Drafts dir not listed as definition
def test_drafts_dir_not_listed_as_definition(client, workflows_dir):
    """Ensure .drafts directory is not exposed in definitions list."""
    # Create a draft
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "content")
    
    # List definitions (main route)
    response = client.get("/api/definitions")
    assert response.status_code == 200
    definitions = response.json()
    
    # Verify no .drafts entries
    for definition in definitions:
        assert not definition["name"].startswith(".")
        assert ".drafts" not in definition["path"]

# Test 24: Get current pointer returns 404 when unset
def test_get_current_404_when_unset(client):
    """GET /api/workflows/{name}/drafts/current returns 404 when no .current file exists."""
    response = client.get("/api/workflows/test-workflow/drafts/current")
    assert response.status_code == 404


# Test 25: Put current sets pointer
def test_put_current_sets_pointer(client, workflows_dir):
    """PUT /api/workflows/{name}/drafts/current sets pointer, GET returns same timestamp."""
    # Create a draft first
    timestamp = "20260101T120000_000000Z"
    create_draft(workflows_dir, "test-workflow", timestamp, "content: test")
    
    # Set current pointer
    response = client.put(
        "/api/workflows/test-workflow/drafts/current",
        json={"timestamp": timestamp}
    )
    assert response.status_code == 204
    
    # Verify GET returns the same timestamp
    response = client.get("/api/workflows/test-workflow/drafts/current")
    assert response.status_code == 200
    assert response.json()["timestamp"] == timestamp


# Test 26: Put current rejects malformed timestamp
def test_put_current_rejects_malformed_timestamp(client):
    """PUT /api/workflows/{name}/drafts/current returns 422 for malformed timestamp (Pydantic validation)."""
    response = client.put(
        "/api/workflows/test-workflow/drafts/current",
        json={"timestamp": "not-a-timestamp"}
    )
    assert response.status_code == 422


# Test 27: Put current returns 404 when draft missing
def test_put_current_404_when_draft_missing(client):
    """PUT /api/workflows/{name}/drafts/current returns 404 when draft doesn't exist."""
    response = client.put(
        "/api/workflows/test-workflow/drafts/current",
        json={"timestamp": "20260101T120000_000000Z"}
    )
    assert response.status_code == 404


# Test 28: Put current overwrites previous pointer
def test_put_current_overwrites_previous_pointer(client, workflows_dir):
    """Second PUT replaces first pointer cleanly."""
    ts1 = "20260101T120000_000000Z"
    ts2 = "20260102T120000_000000Z"
    create_draft(workflows_dir, "test-workflow", ts1, "content: v1")
    create_draft(workflows_dir, "test-workflow", ts2, "content: v2")
    
    # Set first pointer
    client.put("/api/workflows/test-workflow/drafts/current", json={"timestamp": ts1})
    response = client.get("/api/workflows/test-workflow/drafts/current")
    assert response.json()["timestamp"] == ts1
    
    # Overwrite with second pointer
    client.put("/api/workflows/test-workflow/drafts/current", json={"timestamp": ts2})
    response = client.get("/api/workflows/test-workflow/drafts/current")
    assert response.status_code == 200
    assert response.json()["timestamp"] == ts2


# Test 29: Get current survives across directories
def test_get_current_survives_across_directories(tmp_path):
    """GET /api/workflows/{name}/drafts/current finds .current in any configured workflows_dirs."""
    # Create two separate workflows directories
    dir_a = tmp_path / "workflows_a"
    dir_b = tmp_path / "workflows_b"
    dir_a.mkdir()
    dir_b.mkdir()
    
    # Create draft in dir_b
    timestamp = "20260101T120000_000000Z"
    drafts_dir = dir_b / ".drafts" / "test-workflow"
    drafts_dir.mkdir(parents=True)
    draft_path = drafts_dir / f"{timestamp}.yaml"
    draft_path.write_text("content: test")
    
    # Create .current pointer in dir_b
    current_path = drafts_dir / ".current"
    current_path.write_text(timestamp)
    
    # Create app with both directories (dir_a is primary, dir_b is secondary)
    db_path = tmp_path / "test.db"
    init_db(db_path)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    app = create_app(
        db_path=db_path,
        events_dir=events_dir,
        workflows_dirs=[dir_a, dir_b],
        checkpoint_prefix=None,
    )
    client = TestClient(app)
    
    # Verify .current is found in dir_b even though dir_a is primary
    response = client.get("/api/workflows/test-workflow/drafts/current")
    assert response.status_code == 200
    assert response.json()["timestamp"] == timestamp


# New tests for GW-5251: Version browser drawer

def create_published_log(workflows_dir: Path, name: str, entries: list[tuple[str, str, str]]) -> Path:
    """Helper to create a PUBLISHED.log file.
    
    Args:
        workflows_dir: Workflows directory
        name: Workflow name
        entries: List of (timestamp, publisher, draft_timestamp) tuples
        
    Returns:
        Path to created PUBLISHED.log
    """
    log_path = workflows_dir / ".drafts" / name / "PUBLISHED.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{ts}  {pub}  published {draft_ts}" for ts, pub, draft_ts in entries]
    log_path.write_text("\n".join(lines) + "\n")
    return log_path


def test_list_drafts_includes_publisher_from_published_log(client, workflows_dir):
    """List endpoint populates publisher field from PUBLISHED.log."""
    # Create two drafts
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "content: draft1")
    create_draft(workflows_dir, "test-workflow", "20260102T120000_000000Z", "content: draft2")
    
    # Create PUBLISHED.log with one published entry
    create_published_log(
        workflows_dir,
        "test-workflow",
        [
            ("20260101T120500_000000Z", "alice@example.com", "20260101T120000_000000Z"),
        ]
    )
    
    response = client.get("/api/workflows/test-workflow/drafts")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    
    # Published draft should have publisher
    published_item = next((item for item in items if item["timestamp"] == "20260101T120000_000000Z"), None)
    assert published_item is not None
    assert published_item["publisher"] == "alice@example.com"
    
    # Unpublished draft should have null publisher
    unpublished_item = next((item for item in items if item["timestamp"] == "20260102T120000_000000Z"), None)
    assert unpublished_item is not None
    assert unpublished_item["publisher"] is None


def test_drafts_diff_endpoint_returns_unified_diff(client, workflows_dir):
    """POST /api/workflows/{name}/drafts/diff returns unified diff."""
    # Create a draft
    draft_content = "name: test\ndescription: old description\n"
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", draft_content)
    
    # Current canvas content (modified)
    current_content = "name: test\ndescription: new description\n"
    
    response = client.post(
        "/api/workflows/test-workflow/drafts/diff",
        json={
            "from_ts": "20260101T120000_000000Z",
            "to_content": current_content
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "unified_diff" in data
    assert "first_change_line" in data
    
    # Verify unified diff contains expected changes
    unified_diff = data["unified_diff"]
    assert "-description: old description" in unified_diff
    assert "+description: new description" in unified_diff
    
    # Verify first_change_line
    assert "description" in data["first_change_line"].lower()


def test_drafts_diff_invalid_timestamp_returns_400(client):
    """POST /diff with invalid timestamp returns 422 (Pydantic validation)."""
    response = client.post(
        "/api/workflows/test-workflow/drafts/diff",
        json={
            "from_ts": "invalid-timestamp",
            "to_content": "name: test\n"
        }
    )
    assert response.status_code == 422


def test_drafts_diff_missing_draft_returns_404(client):
    """POST /diff with non-existent draft returns 404."""
    response = client.post(
        "/api/workflows/test-workflow/drafts/diff",
        json={
            "from_ts": "20260101T120000_000000Z",
            "to_content": "name: test\n"
        }
    )
    assert response.status_code == 404


def test_published_log_parser_handles_two_space_format(client, workflows_dir):
    """Publisher extraction correctly parses two-space separator format."""
    # Create drafts
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", "content: draft1")
    create_draft(workflows_dir, "test-workflow", "20260102T120000_000000Z", "content: draft2")
    create_draft(workflows_dir, "test-workflow", "20260103T120000_000000Z", "content: draft3")

    # Create PUBLISHED.log with specific two-space format
    # Format: YYYY-MM-DDTHH:MM:SSZ  {publisher}  published {ts}
    create_published_log(
        workflows_dir,
        "test-workflow",
        [
            ("20260101T120500_000000Z", "alice@example.com", "20260101T120000_000000Z"),
            ("20260102T120500_000000Z", "bob@example.com", "20260102T120000_000000Z"),
        ]
    )

    response = client.get("/api/workflows/test-workflow/drafts")
    assert response.status_code == 200
    items = response.json()

    # Build dict for easier lookup
    items_by_ts = {item["timestamp"]: item for item in items}

    # Verify correct publishers extracted
    assert items_by_ts["20260101T120000_000000Z"]["publisher"] == "alice@example.com"
    assert items_by_ts["20260102T120000_000000Z"]["publisher"] == "bob@example.com"
    assert items_by_ts["20260103T120000_000000Z"]["publisher"] is None


def test_drafts_diff_with_json_content_format(client, workflows_dir):
    """POST /diff with JSON-formatted draft content (matching autosave format) compares correctly.

    GW-5251: Drafts are stored as JSON.stringify({nodes: [...]}), not YAML.
    The diff endpoint must handle apples-to-apples comparison when both from and to are JSON.
    """
    # Create a draft with JSON content (matching autosave format)
    draft_json = json.dumps({"nodes": [{"id": "node1", "type": "bash", "script": "echo hello"}]})
    create_draft(workflows_dir, "test-workflow", "20260101T120000_000000Z", draft_json)

    # Current canvas content (JSON with modified node)
    current_json = json.dumps({"nodes": [{"id": "node1", "type": "bash", "script": "echo world"}]})

    response = client.post(
        "/api/workflows/test-workflow/drafts/diff",
        json={
            "from_ts": "20260101T120000_000000Z",
            "to_content": current_json
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert "unified_diff" in data

    # Verify diff shows only the changed field, not 100% replacement
    unified_diff = data["unified_diff"]
    assert "hello" in unified_diff or "world" in unified_diff, "Diff should show changed script content"
    # Verify it's not treating the entire content as replaced
    lines = unified_diff.split("\n")
    # Count changed lines - should be minimal for a single field change
    changed_lines = [l for l in lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    assert len(changed_lines) < 10, f"Expected minimal diff, got {len(changed_lines)} changed lines"


def test_publish_appends_to_published_log(workflows_dir, client):
    """
    GW-5330: Dashboard publish must write PUBLISHED.log audit trail.

    AC: POST /api/workflows/{name}/drafts/{ts}/publish causes PUBLISHED.log to be appended
    with publisher identity in format: YYYY-MM-DDTHH:MM:SSZ  publisher  published {ts}
    (two-space separator between fields).
    """
    import os
    import socket
    from dag_dashboard.drafts_routes import _read_publishers_from_log

    # Create a valid workflow draft
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: /tmp/test
nodes:
  - id: node1
    name: node1
    type: bash
    script: echo test
"""
    response = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": yaml_content}
    )
    assert response.status_code == 201
    timestamp = response.json()["timestamp"]

    # Publish the draft
    response = client.post(f"/api/workflows/test-workflow/drafts/{timestamp}/publish")
    if response.status_code != 200:
        print(f"Response: {response.status_code} - {response.text}")
    assert response.status_code == 200

    # Verify PUBLISHED.log exists and contains correct entry
    published_log = workflows_dir / ".drafts" / "test-workflow" / "PUBLISHED.log"
    assert published_log.exists(), "PUBLISHED.log should exist after publish"

    log_content = published_log.read_text()
    assert log_content, "PUBLISHED.log should not be empty"

    # Verify format: log_timestamp  publisher  published draft_timestamp
    lines = log_content.strip().split("\n")
    assert len(lines) >= 1, "PUBLISHED.log should have at least one entry"

    last_line = lines[-1]
    parts = last_line.split("  ")  # Two-space separator
    assert len(parts) == 3, f"Expected 3 parts (log_ts, publisher, action), got {len(parts)}: {last_line}"

    log_ts, publisher, action = parts

    # Verify log timestamp format (ISO 8601 with seconds: YYYY-MM-DDTHH:MM:SSZ)
    assert len(log_ts) == 20, f"Log timestamp should be 20 chars (YYYY-MM-DDTHH:MM:SSZ), got {len(log_ts)}: {log_ts}"
    assert log_ts[10] == "T" and log_ts[-1] == "Z", f"Log timestamp should be ISO 8601 format: {log_ts}"

    # Verify publisher format: dashboard-ui:user@host (single-token, colon-delimited)
    assert publisher.startswith("dashboard-ui:"), f"Publisher should start with 'dashboard-ui:', got: {publisher}"
    assert "@" in publisher, f"Publisher should contain '@' for user@host format: {publisher}"
    # Verify no embedded double-space (this was the Critical Fix #1 from plan review)
    assert "  " not in publisher, f"Publisher should not contain embedded double-space: {publisher}"

    # Verify action format
    assert action == f"published {timestamp}", f"Action should be 'published {timestamp}', got: {action}"


def test_list_drafts_shows_publisher_after_dashboard_publish(workflows_dir, client):
    """
    GW-5330: After dashboard publish, list endpoint must show publisher identity.

    End-to-end test: POST draft → POST publish → GET list shows publisher field.
    """
    # Create and publish a draft
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: /tmp/test
nodes:
  - id: node1
    name: node1
    type: bash
    script: echo test
"""
    response = client.post(
        "/api/workflows/test-workflow/drafts",
        json={"content": yaml_content}
    )
    assert response.status_code == 201
    timestamp = response.json()["timestamp"]

    response = client.post(f"/api/workflows/test-workflow/drafts/{timestamp}/publish")
    assert response.status_code == 200

    # List drafts - should show publisher
    response = client.get("/api/workflows/test-workflow/drafts")
    assert response.status_code == 200
    drafts = response.json()

    # Find the draft we just published
    published_draft = next((d for d in drafts if d["timestamp"] == timestamp), None)
    assert published_draft is not None, f"Published draft {timestamp} should appear in list"

    # Verify publisher field is populated
    assert published_draft["publisher"] is not None, "Publisher field should be populated after publish"
    assert published_draft["publisher"].startswith("dashboard-ui:"), \
        f"Publisher should start with 'dashboard-ui:', got: {published_draft['publisher']}"


def test_read_publishers_from_log_parses_dashboard_format(workflows_dir):
    """
    GW-5330: Parser-roundtrip assertion for new publisher format.

    Critical Fix #1: Publisher format changed from 'dashboard-ui  user@host' (embedded double-space)
    to 'dashboard-ui:user@host' (colon-delimited) so that _read_publishers_from_log can correctly
    parse entries split on two-space separator.
    """
    import os
    from dag_dashboard.drafts_routes import _read_publishers_from_log

    # Create mock PUBLISHED.log with new format
    drafts_dir = workflows_dir / ".drafts" / "test-workflow"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    published_log = drafts_dir / "PUBLISHED.log"

    # Write entries with both old CLI format and new dashboard format
    published_log.write_text(
        "2026-01-15T10:30:00Z  cli:alice@host1  published 20260101T120000_000000Z\n"
        "2026-01-15T10:31:00Z  dashboard-ui:bob@host2  published 20260101T130000_000000Z\n"
    )

    # Parse the log
    publishers = _read_publishers_from_log(drafts_dir)

    # Verify both entries parsed correctly
    assert "20260101T120000_000000Z" in publishers, "First entry should be parsed"
    assert publishers["20260101T120000_000000Z"] == "cli:alice@host1", \
        f"First publisher should be 'cli:alice@host1', got: {publishers.get('20260101T120000_000000Z')}"

    assert "20260101T130000_000000Z" in publishers, "Second entry should be parsed"
    assert publishers["20260101T130000_000000Z"] == "dashboard-ui:bob@host2", \
        f"Second publisher should be 'dashboard-ui:bob@host2', got: {publishers.get('20260101T130000_000000Z')}"


def test_cli_written_draft_visible_to_rest(client, workflows_dir):
    """CLI-written drafts (via drafts_fs.write_draft) are readable via REST GET /drafts."""
    from dag_executor import drafts_fs

    # Write draft using CLI function (drafts_fs.write_draft)
    workflow_name = "test-workflow"
    content = """name: test
config:
  checkpoint_prefix: /tmp/test
nodes:
  - id: start
    name: start
    type: prompt
    prompt: "Hello"
"""
    ts = drafts_fs.write_draft(workflows_dir, workflow_name, content)

    # List drafts via REST — should not return 500
    response = client.get(f"/api/workflows/{workflow_name}/drafts")
    assert response.status_code == 200, f"GET /drafts failed with {response.status_code}: {response.text}"

    data = response.json()
    assert isinstance(data, list), "Response should be a list of drafts"
    assert len(data) > 0, "Should list at least one draft"

    # Verify the CLI-written timestamp appears in the list
    timestamps = [d["timestamp"] for d in data]
    assert ts in timestamps, f"CLI-written timestamp {ts} not found in REST list: {timestamps}"

    # Read draft via REST
    response = client.get(f"/api/workflows/{workflow_name}/drafts/{ts}")
    assert response.status_code == 200, f"GET /drafts/{ts} failed with {response.status_code}: {response.text}"
    draft_data = response.json()
    assert draft_data["content"] == content, "Draft content should match what was written"

    # Publish draft via REST (simulates publish operation)
    response = client.post(f"/api/workflows/{workflow_name}/drafts/{ts}/publish")
    assert response.status_code == 200, f"POST /drafts/{ts}/publish failed with {response.status_code}: {response.text}"


def test_rest_written_draft_readable_by_cli(client, workflows_dir):
    """REST-written drafts are readable via CLI functions (drafts_fs.read_draft, list_drafts)."""
    from dag_executor import drafts_fs

    workflow_name = "test-workflow"
    content = """name: rest-test
config:
  checkpoint_prefix: /tmp/test
nodes:
  - id: start
    name: start
    type: prompt
    prompt: "Hello"
"""

    # Write draft via REST
    response = client.post(
        f"/api/workflows/{workflow_name}/drafts",
        json={"content": content}
    )
    assert response.status_code == 201, f"POST /drafts failed with {response.status_code}: {response.text}"
    
    data = response.json()
    assert "timestamp" in data
    ts = data["timestamp"]

    # Read draft via CLI function
    read_content = drafts_fs.read_draft(workflows_dir, workflow_name, ts)
    assert read_content == content, "CLI read_draft should return same content as REST wrote"

    # List drafts via CLI function — should include REST-written timestamp
    drafts = drafts_fs.list_drafts(workflows_dir, workflow_name)
    assert ts in drafts, f"REST-written timestamp {ts} not found in CLI list: {drafts}"
