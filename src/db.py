"""PostgreSQL access helpers.

Raw SQL with psycopg, no ORM: the SQL tool in this project must run queries the
author can read, explain and check a query plan for. Parameters are always passed
to psycopg rather than formatted into the string, so a question can never inject
SQL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.config import get_settings


@contextmanager
def get_connection(*, read_only: bool = True) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Open a connection as a context manager.

    Args:
        read_only: Open the session read-only. The question-answering path never
            needs to write business data, so it runs read-only and a bug cannot
            modify or delete rows. Ingestion and audit writes pass False.

    Yields:
        An open psycopg connection with dict-style rows.
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        if read_only:
            conn.read_only = True
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a read-only SELECT and return all rows.

    Args:
        sql: Statement with named placeholders, e.g. ``%(department_id)s``.
        params: Values for those placeholders.

    Returns:
        Rows as dictionaries.
    """
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


def check_connection() -> str:
    """Return the server version, or raise if the database is unreachable.

    Used by the readiness probe. Kept separate from the liveness probe so that a
    database outage marks the service not-ready instead of killing the container.
    """
    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT version() AS version")
        row = cur.fetchone()
        return str(row["version"]) if row else "unknown"
