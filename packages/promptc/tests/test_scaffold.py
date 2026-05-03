"""Scaffold smoke test for promptc package.

Placeholder test to avoid pytest exit code 5 (no tests collected).
This ensures CI passes during the scaffolding phase before parser/schema
tests are added in GW-5472/3/4.
"""


def test_imports_clean() -> None:
    """Verify promptc package imports without errors."""
    import promptc  # noqa: F401
