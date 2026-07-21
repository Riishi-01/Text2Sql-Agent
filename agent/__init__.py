"""Olist NL2SQL Agent - Natural Language to SQL for Olist e-commerce dataset."""

__version__ = "0.1.0"

from .agent import run_agent
from .validator.sql_validator import validate_sql, ValidationResult

__all__ = ["run_agent", "validate_sql", "ValidationResult"]
