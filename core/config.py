"""Unified application settings — shared by agent and API layers.

Single source of truth for all configuration. Both the LangGraph agent
and the FastAPI service import from here, eliminating the duplicate
Settings classes that previously lived in agent/config.py and config.py.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env before anything else
load_dotenv()

# LangSmith tracing must be wired before any langchain imports
if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING", "true")
    os.environ["LANGSMITH_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "olist-nl2sql")


class Settings:
    """Application settings loaded from environment variables."""

    # ── OpenAI ──────────────────────────────────────────────────────────────
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))

    # ── PostgreSQL — read-only agent role (nl2sql_ro) ────────────────────────
    pg_host: str = os.getenv("PG_HOST", "localhost")
    pg_port: int = int(os.getenv("PG_PORT", "5432"))
    pg_database: str = os.getenv("PG_DATABASE", "text2sql")
    pg_user: str = os.getenv("PG_USER", "nl2sql_ro")
    pg_password: str = os.getenv("PG_PASSWORD", "nl2sql_ro_password")
    pg_statement_timeout_ms: int = int(os.getenv("PG_STATEMENT_TIMEOUT_MS", "30000"))

    # ── PostgreSQL — sandbox / API role ─────────────────────────────────────
    sandbox_user: str = os.getenv("SANDBOX_USER", "sandbox")
    sandbox_password: str = os.getenv("SANDBOX_PASSWORD", "sandbox_password")
    sandbox_db: str = os.getenv("SANDBOX_DB", "text2sql")
    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))
    query_row_limit: int = int(os.getenv("QUERY_ROW_LIMIT", "10000"))

    # ── LangSmith ───────────────────────────────────────────────────────────
    langsmith_api_key: Optional[str] = os.getenv("LANGSMITH_API_KEY")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "olist-nl2sql")
    langsmith_tracing: bool = os.getenv("LANGSMITH_TRACING", "true").lower() == "true"

    # ── Runtime overrides ───────────────────────────────────────────────────
    # NOW_OVERRIDE: ISO date string (YYYY-MM-DD) to pin {{NOW}} in prompts
    now_override: Optional[str] = os.getenv("NOW_OVERRIDE")

    # ── Paths ────────────────────────────────────────────────────────────────
    # Resolved relative to this file so they work regardless of cwd
    _root: Path = Path(__file__).parent.parent
    data_dir: Path = _root / "data" / "Olist Dataset"
    prompts_dir: Path = _root / "agent" / "prompts"

    # Legacy alias used by API (UPPERCASE style from old root config.py)
    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        return f"postgresql+asyncpg://{self.sandbox_user}:{self.sandbox_password}@{self.pg_host}:{self.pg_port}/{self.sandbox_db}"

    @property
    def SANDBOX_USER(self) -> str:  # noqa: N802
        return self.sandbox_user

    @property
    def SANDBOX_PASSWORD(self) -> str:  # noqa: N802
        return self.sandbox_password

    @property
    def SANDBOX_DB(self) -> str:  # noqa: N802
        return self.sandbox_db

    @property
    def QUERY_TIMEOUT_SECONDS(self) -> int:  # noqa: N802
        return self.query_timeout_seconds

    @property
    def QUERY_ROW_LIMIT(self) -> int:  # noqa: N802
        return self.query_row_limit

    @property
    def database_url(self) -> str:
        """psycopg (sync) connection URL — read-only agent role."""
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def api_database_url(self) -> str:
        """asyncpg connection URL — sandbox / API role."""
        return (
            f"postgresql://{self.sandbox_user}:{self.sandbox_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.sandbox_db}"
        )


# Global singleton — import this everywhere
settings = Settings()
