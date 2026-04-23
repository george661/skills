"""Tests for builder bundle packaging in pyproject.toml."""
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib


def test_package_data_includes_builder() -> None:
    """pyproject.toml should include static/js/builder in package-data."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)
    
    # Get package data for dag_dashboard
    package_data = config.get("tool", {}).get("setuptools", {}).get("package-data", {})
    dag_dashboard_data = package_data.get("dag_dashboard", [])
    
    # Check that static/js/builder is covered (either explicitly or via static/**/*)
    # The existing "static/**/*" should cover it, but we verify it would be included
    has_builder_pattern = any(
        "static/js/builder" in pattern or 
        pattern in ["static/**/*", "static/**/**/*"]
        for pattern in dag_dashboard_data
    )
    
    assert has_builder_pattern, \
        f"package-data should include pattern covering static/js/builder/, found: {dag_dashboard_data}"
