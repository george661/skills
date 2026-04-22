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
