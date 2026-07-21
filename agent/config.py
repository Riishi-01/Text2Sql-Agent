"""Environment configuration and LangSmith wiring."""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables BEFORE any langchain imports
load_dotenv()

# Set LangSmith tracing BEFORE importing langchain
# This MUST happen before any langchain_openai imports
if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING", "true")
    os.environ["LANGSMITH_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "olist-nl2sql")


class Settings:
    """Application settings loaded from environment."""
    
    # OpenAI Configuration
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    
    # Database Configuration
    pg_host: str = os.getenv("PG_HOST", "localhost")
    pg_port: int = int(os.getenv("PG_PORT", "5432"))
    pg_database: str = os.getenv("PG_DATABASE", "text2sql")
    pg_user: str = os.getenv("PG_USER", "nl2sql_ro")
    pg_password: str = os.getenv("PG_PASSWORD", "nl2sql_ro_password")
    
    # Read-only connection settings
    pg_statement_timeout_ms: int = int(os.getenv("PG_STATEMENT_TIMEOUT_MS", "30000"))
    
    # LangSmith Configuration
    langsmith_api_key: Optional[str] = os.getenv("LANGSMITH_API_KEY")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "olist-nl2sql")
    langsmith_tracing: bool = os.getenv("LANGSMITH_TRACING", "true").lower() == "true"
    
    # Prompts directory (relative to this file)
    prompts_dir: Path = Path(__file__).parent / "prompts"
    
    # Dataset max date (for {{NOW}} resolution)
    # Can be overridden via env for testing
    now_override: Optional[str] = os.getenv("NOW_OVERRIDE")
    
    @property
    def database_url(self) -> str:
        """Get PostgreSQL connection URL for psycopg."""
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"
    
    @property
    def database_url_async(self) -> str:
        """Get PostgreSQL connection URL for asyncpg."""
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


# Global settings instance
settings = Settings()
