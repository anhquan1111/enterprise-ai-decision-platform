"""Integration test: requires a running PostgreSQL from compose.

Run with:  uv run pytest -m integration
Skipped in the default suite so CI stays green without a database.
"""

import pytest

from src.db import check_connection


@pytest.mark.integration
def test_postgres_is_reachable_and_has_pgvector() -> None:
    """The database answers, and the pgvector extension is available."""
    from src.db import fetch_all

    version = check_connection()
    assert "PostgreSQL" in version

    rows = fetch_all(
        "SELECT extname FROM pg_extension WHERE extname = %(name)s",
        {"name": "vector"},
    )
    assert rows, "pgvector extension is not installed — run sql/00_schema.sql (D1)"
