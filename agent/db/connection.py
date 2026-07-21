"""Read-only PostgreSQL connection with safety settings.

Provides a read-only connection to the Olist database:
- Uses read-only role: nl2sql_ro
- Sets statement_timeout per connection
- Sets default_transaction_read_only = on
- Provides safe execution with row limits
"""
import psycopg
from psycopg.rows import dict_row
from typing import List, Dict, Any, Tuple
from contextlib import contextmanager

from core.config import settings


def get_connection() -> psycopg.Connection:
    """Create a read-only database connection.

    The connection is configured with:
    - statement_timeout from settings
    - default_transaction_read_only = on

    Returns:
        Configured psycopg connection
    """
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)

    # Set statement timeout and enforce read-only mode
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {settings.pg_statement_timeout_ms}")
        cur.execute("SET default_transaction_read_only = on")

    conn.commit()
    return conn


@contextmanager
def get_connection_context():
    """Context manager for database connection.

    Yields:
        psycopg connection with safety settings applied
    """
    conn = None
    try:
        conn = get_connection()
        yield conn
    finally:
        if conn:
            conn.close()


def execute_query(
    sql: str, row_limit: int = 10000
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Execute a SQL query safely.

    Args:
        sql: SQL query to execute
        row_limit: Maximum rows to return (default 10000)

    Returns:
        Tuple of (rows, columns)

    Raises:
        Exception: If query execution fails
    """
    with get_connection_context() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL row_security = on")
            cur.execute(sql)

            rows = cur.fetchmany(row_limit + 1)
            columns = [desc.name for desc in cur.description] if cur.description else []

            # Trim to limit if we over-fetched
            if len(rows) > row_limit:
                rows = rows[:row_limit]

            return rows, columns


def test_connection() -> bool:
    """Test database connectivity.

    Returns:
        True if connection successful
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                return result is not None
    except Exception:
        return False


def get_table_row_counts() -> Dict[str, int]:
    """Get row counts for all allowed tables.

    Returns:
        Dict mapping table name to row count
    """
    counts = {}

    with get_connection_context() as conn:
        with conn.cursor() as cur:
            for table in [
                "customers",
                "sellers",
                "products",
                "product_category_translation",
                "orders",
                "order_items",
                "order_payments",
                "order_reviews",
                "geolocation",
                "geolocation_by_zip",
            ]:
                try:
                    cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                    result = cur.fetchone()
                    counts[table] = result["count"] if result else 0
                except Exception:
                    counts[table] = -1

    return counts


def check_read_only_permission() -> bool:
    """Verify the connection is truly read-only.

    Returns:
        True if connection is read-only
    """
    try:
        with get_connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW default_transaction_read_only")
                result = cur.fetchone()
                return result and result.get("default_transaction_read_only") == "on"
    except Exception:
        return False
