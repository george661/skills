"""Test skills API routes."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


@pytest.fixture
def client_with_skills(tmp_path: Path) -> TestClient:
    """Create test client with sample skills."""
    # Create sample skills
    skill1 = tmp_path / "test1.skill.md"
    skill1.write_text("""---
name: Test Skill 1
description: First test skill
---
Content
""")
    
    skill_dir = tmp_path / "skill2"
    skill_dir.mkdir()
    skill2 = skill_dir / "SKILL.md"
    skill2.write_text("""---
name: Test Skill 2
description: Second test skill
---
Content
""")
    
    # Create app with skills_dirs
    app = create_app(tmp_path)
    app.state.skills_dirs = [tmp_path]
    
    return TestClient(app)


def test_get_skills_returns_200(client_with_skills: TestClient) -> None:
    """Test GET /api/skills returns 200."""
    response = client_with_skills.get("/api/skills")
    assert response.status_code == 200


def test_get_skills_returns_json_array(client_with_skills: TestClient) -> None:
    """Test GET /api/skills returns JSON array."""
    response = client_with_skills.get("/api/skills")
    data = response.json()
    assert isinstance(data, list)


def test_get_skills_returns_correct_shape(client_with_skills: TestClient) -> None:
    """Test GET /api/skills returns objects with name, description, path."""
    response = client_with_skills.get("/api/skills")
    data = response.json()
    
    assert len(data) == 2
    
    for skill in data:
        assert "name" in skill
        assert "description" in skill
        assert "path" in skill
        assert isinstance(skill["name"], str)
        assert isinstance(skill["description"], str)
        assert isinstance(skill["path"], str)


def test_get_skills_returns_expected_skills(client_with_skills: TestClient) -> None:
    """Test GET /api/skills returns the expected skills."""
    response = client_with_skills.get("/api/skills")
    data = response.json()
    
    names = [skill["name"] for skill in data]
    assert "Test Skill 1" in names
    assert "Test Skill 2" in names


def test_get_skills_empty_directory(tmp_path: Path) -> None:
    """Test GET /api/skills with no skills returns empty array."""
    app = create_app(tmp_path)
    app.state.skills_dirs = [tmp_path]
    client = TestClient(app)
    
    response = client.get("/api/skills")
    assert response.status_code == 200
    assert response.json() == []


def test_get_skills_handles_missing_skills_dirs(tmp_path: Path) -> None:
    """Test GET /api/skills when skills_dirs not set."""
    app = create_app(tmp_path)
    # Don't set app.state.skills_dirs
    client = TestClient(app)

    response = client.get("/api/skills")
    # Route uses getattr with default empty list, always returns 200
    assert response.status_code == 200
    assert response.json() == []
