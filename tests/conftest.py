"""Shared pytest fixtures for all test categories.

Usage:
    pytest tests/unit/ -v           # unit only (no DB/network)
    pytest tests/integration/ -v    # requires live DB
    pytest tests/e2e/ -v            # requires running API server
    pytest -v                       # all
"""
import os
import pytest

# Default API base URL — override via API_BASE_URL env var
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@pytest.fixture
def base_url() -> str:
    """Base URL for the running API server."""
    return BASE_URL
