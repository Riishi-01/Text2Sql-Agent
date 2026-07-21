"""Read-only PostgreSQL connection layer.

Provides a safe, timeout-guarded connection using the nl2sql_ro role.
All query execution for the agent goes through this sub-package.
"""
from .connection import (
    execute_query,
    get_connection,
    get_connection_context,
    test_connection,
    get_table_row_counts,
    check_read_only_permission,
)

__all__ = [
    "execute_query",
    "get_connection",
    "get_connection_context",
    "test_connection",
    "get_table_row_counts",
    "check_read_only_permission",
]
