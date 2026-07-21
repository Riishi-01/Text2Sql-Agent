"""Application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Settings:
    """Application settings."""
    
    # Database URLs
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://sandbox:sandbox_password@localhost:5432/text2sql")
    DATABASE_URL_SYNC: str = os.getenv("DATABASE_URL_SYNC", "postgresql://sandbox:sandbox_password@localhost:5432/text2sql")
    
    # Admin database for setup
    ADMIN_DB_URL: str = os.getenv("ADMIN_DB_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    
    # Sandbox credentials
    SANDBOX_USER: str = os.getenv("SANDBOX_USER", "sandbox")
    SANDBOX_PASSWORD: str = os.getenv("SANDBOX_PASSWORD", "sandbox_password")
    SANDBOX_DB: str = os.getenv("SANDBOX_DB", "text2sql")
    
    # Query constraints
    QUERY_TIMEOUT_SECONDS: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))
    QUERY_ROW_LIMIT: int = int(os.getenv("QUERY_ROW_LIMIT", "10000"))
    
    # Data path
    DATA_DIR: Path = Path(__file__).parent / "data" / "Olist Dataset"


settings = Settings()
