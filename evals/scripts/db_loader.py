#!/usr/bin/env python3
"""PostgreSQL connection helper for the eval runner.

Design constraints (see evals/README.md and the eval_runner spec):
  - One connection per worker thread. Never share a psycopg connection
    across threads.
  - Statement timeout applied per-connection (default 15s for evals,
    distinct from the production agent's 30s default).
  - Read-only: reuses the same `nl2sql_ro` role as the production agent
    (core.config.settings.database_url), so no separate DB credentials
    are needed for the eval suite.
"""
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Tuple

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import settings  # noqa: E402

DEFAULT_STATEMENT_TIMEOUT_MS = 15000  # 15s, per eval_runner spec
DEFAULT_ROW_LIMIT = 10000


class TransientDBError(Exception):
    """Raised for retryable errors: timeout, connection/lock issues."""


def open_connection(statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS) -> psycopg.Connection:
    """Open a new read-only PostgreSQL connection.

    Intended to be called once per worker thread. Caller is responsible
    for closing the connection (use `connection_scope` for that).
    """
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
        cur.execute("SET default_transaction_read_only = on")
    conn.commit()
    return conn


@contextmanager
def connection_scope(statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS):
    """Context manager: open a connection, yield it, always close it.

    Usage (inside a worker thread):
        with connection_scope() as conn:
            rows, cols = execute_query(conn, sql)
    """
    conn = None
    try:
        conn = open_connection(statement_timeout_ms)
        yield conn
    finally:
        if conn is not None:
            conn.close()


def execute_query(
    conn: psycopg.Connection, sql: str, row_limit: int = DEFAULT_ROW_LIMIT
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Execute a SQL query on the given connection and fetch results.

    Raises:
        TransientDBError: on statement timeout or lock-related errors
            (caller should retry).
        Exception: any other error is treated as non-transient (SQL
            errors, permission errors, etc.) and should not be retried.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(row_limit + 1)
            columns = [desc.name for desc in cur.description] if cur.description else []
            if len(rows) > row_limit:
                rows = rows[:row_limit]
            return rows, columns
    except psycopg.errors.QueryCanceled as e:
        raise TransientDBError(f"statement timeout: {e}") from e
    except psycopg.errors.LockNotAvailable as e:
        raise TransientDBError(f"lock not available: {e}") from e
    except psycopg.OperationalError as e:
        # Connection-level issues (e.g. "database is locked"-style errors
        # under load) are treated as transient.
        raise TransientDBError(f"operational error: {e}") from e


def execute_with_retry(
    conn: psycopg.Connection,
    sql: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
    max_retries: int = 2,
    backoff_seconds: Tuple[float, ...] = (0.5, 1.0),
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Execute a query with retry-on-transient-error semantics.

    Retries up to `max_retries` times, sleeping `backoff_seconds[i]`
    between attempts. Non-transient exceptions (SQL parse errors, etc.)
    propagate immediately without retry.
    """
    attempt = 0
    while True:
        try:
            return execute_query(conn, sql, row_limit)
        except TransientDBError:
            if attempt >= max_retries:
                raise
            delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(delay)
            attempt += 1


def test_connection() -> bool:
    """Smoke test: open a connection and run SELECT 1."""
    try:
        with connection_scope() as conn:
            rows, _ = execute_query(conn, "SELECT 1 AS ok")
            return bool(rows) and rows[0].get("ok") == 1
    except Exception:
        return False


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="db_loader.py connection smoke test")
    parser.add_argument("--test", action="store_true", help="Run a connectivity smoke test")
    args = parser.parse_args()

    if args.test:
        try:
            with connection_scope() as conn:
                rows, _ = execute_query(conn, "SELECT COUNT(*) AS n FROM orders")
                print(f"Connection OK: {rows[0]['n']} orders")
                return 0
        except Exception as e:
            print(f"Connection FAILED: {e}")
            return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
