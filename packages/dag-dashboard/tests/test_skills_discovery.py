"""Test skills_discovery module."""
from pathlib import Path
from dag_dashboard.skills_discovery import list_skills


def test_list_skills_empty_directory(tmp_path: Path) -> None:
    """Test list_skills returns empty list for empty directory."""
    result = list_skills([tmp_path])
    assert result == []


def test_list_skills_finds_skill_md_files(tmp_path: Path) -> None:
    """Test list_skills finds *.skill.md files."""
    skill_file = tmp_path / "test.skill.md"
    skill_file.write_text("""---
name: Test Skill
description: A test skill
---
# Test Skill Content
""")
    
    result = list_skills([tmp_path])
    assert len(result) == 1
    assert result[0]["name"] == "Test Skill"
    assert result[0]["description"] == "A test skill"
    assert "test.skill.md" in result[0]["path"]


def test_list_skills_finds_skill_md_in_subdirectory(tmp_path: Path) -> None:
    """Test list_skills finds <dir>/SKILL.md files."""
    skill_dir = tmp_path / "myskill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("""---
name: My Skill
description: Another test skill
---
# Skill Content
""")
    
    result = list_skills([tmp_path])
    assert len(result) == 1
    assert result[0]["name"] == "My Skill"
    assert result[0]["description"] == "Another test skill"
    assert "myskill/SKILL.md" in result[0]["path"]


def test_list_skills_finds_both_conventions(tmp_path: Path) -> None:
    """Test list_skills finds both *.skill.md and <dir>/SKILL.md."""
    # Create *.skill.md
    skill_file = tmp_path / "foo.skill.md"
    skill_file.write_text("""---
name: Foo Skill
description: Foo description
---
Content
""")
    
    # Create <dir>/SKILL.md
    skill_dir = tmp_path / "bar"
    skill_dir.mkdir()
    dir_skill = skill_dir / "SKILL.md"
    dir_skill.write_text("""---
name: Bar Skill
description: Bar description
---
Content
""")
    
    result = list_skills([tmp_path])
    assert len(result) == 2
    names = [s["name"] for s in result]
    assert "Foo Skill" in names
    assert "Bar Skill" in names


def test_list_skills_skips_files_without_frontmatter(tmp_path: Path) -> None:
    """Test list_skills skips files without YAML frontmatter."""
    # File with no frontmatter
    no_fm = tmp_path / "no-frontmatter.skill.md"
    no_fm.write_text("# Just content, no frontmatter")
    
    # File with proper frontmatter
    with_fm = tmp_path / "with-frontmatter.skill.md"
    with_fm.write_text("""---
name: Valid Skill
description: Valid description
---
Content
""")
    
    result = list_skills([tmp_path])
    assert len(result) == 1
    assert result[0]["name"] == "Valid Skill"


def test_list_skills_skips_files_missing_name(tmp_path: Path) -> None:
    """Test list_skills skips files with frontmatter but missing name field."""
    skill_file = tmp_path / "no-name.skill.md"
    skill_file.write_text("""---
description: Missing name field
---
Content
""")
    
    result = list_skills([tmp_path])
    assert len(result) == 0


def test_list_skills_handles_multiple_directories(tmp_path: Path) -> None:
    """Test list_skills scans multiple directories."""
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    skill1 = dir1 / "skill1.skill.md"
    skill1.write_text("""---
name: Skill One
description: First skill
---
Content
""")
    
    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    skill2 = dir2 / "skill2.skill.md"
    skill2.write_text("""---
name: Skill Two
description: Second skill
---
Content
""")
    
    result = list_skills([dir1, dir2])
    assert len(result) == 2
    names = [s["name"] for s in result]
    assert "Skill One" in names
    assert "Skill Two" in names
