"""Database metadata loader.

Loads table/column metadata from information_schema for the semantic model.
The loaded metadata is injected into the system prompt by the prompt builder.
"""
import psycopg
from typing import Dict, List, Any
from dataclasses import dataclass

from core.config import settings


@dataclass
class ColumnInfo:
    """Column metadata."""

    name: str
    data_type: str
    is_nullable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "is_nullable": self.is_nullable,
        }


@dataclass
class TableInfo:
    """Table metadata."""

    name: str
    columns: List[ColumnInfo]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
        }


def load_table_metadata() -> Dict[str, TableInfo]:
    """Load metadata for all allowed tables from information_schema.

    Returns:
        Dict mapping table name to TableInfo
    """
    tables: Dict[str, TableInfo] = {}

    conn_str = settings.database_url

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            # Query information_schema for column metadata
            cur.execute("""
                SELECT
                    table_name,
                    column_name,
                    data_type,
                    is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'customers', 'sellers', 'products',
                    'product_category_translation', 'orders',
                    'order_items', 'order_payments', 'order_reviews',
                    'geolocation', 'geolocation_by_zip'
                  )
                ORDER BY table_name, ordinal_position
            """)

            rows = cur.fetchall()

            # Group by table
            for row in rows:
                table_name, column_name, data_type, is_nullable = row

                if table_name not in tables:
                    tables[table_name] = TableInfo(name=table_name, columns=[])

                tables[table_name].columns.append(
                    ColumnInfo(
                        name=column_name,
                        data_type=data_type,
                        is_nullable=(is_nullable == "YES"),
                    )
                )

    return tables


def get_dataset_max_date() -> str:
    """Get the maximum date from the orders table for {{NOW}} resolution.

    Returns:
        ISO date string (YYYY-MM-DD)
    """
    if settings.now_override:
        return settings.now_override

    conn_str = settings.database_url

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(order_purchase_timestamp)::date FROM orders")
            result = cur.fetchone()
            if result and result[0]:
                return str(result[0])

    # Fallback to current date
    from datetime import date

    return date.today().isoformat()


def get_table_names() -> List[str]:
    """Get list of allowed table names.

    Returns:
        List of table names in the database
    """
    return list(load_table_metadata().keys())
