"""Database schema metadata loader.

This sub-package introspects information_schema and loads table/column
metadata for injection into the system prompt via the prompt builder.

Data flow:
    DB ──► schema/loader.py ──► agent/prompts/builder.py ──► LLM
"""
from .loader import load_table_metadata, get_dataset_max_date, get_table_names

__all__ = ["load_table_metadata", "get_dataset_max_date", "get_table_names"]
