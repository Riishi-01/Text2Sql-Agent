"""Pydantic request/response models for the Text2SQL API."""
from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request model for SQL query."""

    query: str = Field(..., description="SQL SELECT query to execute")
    timeout: Optional[int] = Field(
        None, description="Query timeout in seconds (overrides default)"
    )
    row_limit: Optional[int] = Field(
        None, description="Maximum rows to return (overrides default)"
    )


class QueryResponse(BaseModel):
    """Response model for query results."""

    success: bool
    row_count: int
    columns: list[str]
    rows: list[dict]
    execution_time_ms: float


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    database: str
    ping_ms: float


class ErrorResponse(BaseModel):
    """Response model for errors."""

    success: bool = False
    error: str
    detail: Optional[str] = None
