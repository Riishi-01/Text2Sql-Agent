"""SQL Validator module with R1-R9 static safety checks."""

from .sql_validator import (
    validate_sql,
    ValidationResult,
    extract_tables,
    has_select_star,
    has_aggregation,
    has_limit,
    ALLOWED_TABLES,
    TRAP_TABLES,
    FORBIDDEN_KEYWORDS,
)

__all__ = [
    "validate_sql",
    "ValidationResult",
    "extract_tables",
    "has_select_star",
    "has_aggregation",
    "has_limit",
    "ALLOWED_TABLES",
    "TRAP_TABLES",
    "FORBIDDEN_KEYWORDS",
]
