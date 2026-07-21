"""FastAPI application with read-only query endpoint."""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncpg

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


# Global connection pool
pool: Optional[asyncpg.Pool] = None


class QueryRequest(BaseModel):
    """Request model for SQL query."""
    query: str = Field(..., description="SQL SELECT query to execute")
    timeout: Optional[int] = Field(None, description="Query timeout in seconds (overrides default)")
    row_limit: Optional[int] = Field(None, description="Maximum rows to return (overrides default)")


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - manage connection pool."""
    global pool
    
    # Create connection pool on startup
    pool = await asyncpg.create_pool(
        settings.DATABASE_URL.replace('+asyncpg', ''),
        user=settings.SANDBOX_USER,
        password=settings.SANDBOX_PASSWORD,
        database=settings.SANDBOX_DB,
        min_size=5,
        max_size=20,
        command_timeout=60
    )
    
    yield
    
    # Close pool on shutdown
    await pool.close()


app = FastAPI(
    title="Text2SQL API",
    description="Read-only SQL query endpoint for Olist e-commerce dataset",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint with database ping.
    
    Returns database connection status and ping latency.
    """
    import time
    
    start = time.time()
    
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        ping_ms = (time.time() - start) * 1000
        
        return HealthResponse(
            status="healthy",
            database=f"{settings.SANDBOX_DB}@localhost",
            ping_ms=round(ping_ms, 2)
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database connection failed: {str(e)}"
        )


@app.post("/query", 
          response_model=QueryResponse,
          responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
          tags=["Query"])
async def execute_query(request: QueryRequest, req: Request):
    """
    Execute a read-only SQL query against the database.
    
    The query must be a SELECT statement. The sandbox user has SELECT-only access
    with a configurable timeout and row limit.
    
    - **query**: SQL SELECT statement
    - **timeout**: Optional query timeout in seconds (default from config)
    - **row_limit**: Optional maximum rows to return (default from config)
    """
    import time
    
    # Validate query
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    # Basic validation - must start with SELECT
    if not query.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=400, 
            detail="Only SELECT queries are allowed"
        )
    
    # Check for forbidden keywords
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"]
    query_upper = query.upper()
    for keyword in forbidden:
        if keyword in query_upper:
            raise HTTPException(
                status_code=400,
                detail=f"Query contains forbidden keyword: {keyword}"
            )
    
    # Get timeout and row limit
    timeout = request.timeout or settings.QUERY_TIMEOUT_SECONDS
    row_limit = request.row_limit or settings.QUERY_ROW_LIMIT
    
    # Add LIMIT if not present and row_limit is set
    if "LIMIT" not in query_upper and row_limit:
        query = f"{query.rstrip(';')} LIMIT {row_limit}"
    
    start_time = time.time()
    
    try:
        async with pool.acquire() as conn:
            # Set statement timeout for this query
            await conn.execute(f"SET statement_timeout = '{timeout}s'")
            
            # Execute query
            result = await conn.fetch(query)
            
            execution_time = (time.time() - start_time) * 1000
            
            if not result:
                return QueryResponse(
                    success=True,
                    row_count=0,
                    columns=[],
                    rows=[],
                    execution_time_ms=round(execution_time, 2)
                )
            
            # Get column names
            columns = list(result[0].keys())
            
            # Convert to list of dicts
            rows = [dict(row) for row in result]
            
            return QueryResponse(
                success=True,
                row_count=len(rows),
                columns=columns,
                rows=rows,
                execution_time_ms=round(execution_time, 2)
            )
            
    except asyncpg.exceptions.QueryCanceledError:
        raise HTTPException(
            status_code=408,
            detail=f"Query timeout exceeded ({timeout}s)"
        )
    except asyncpg.exceptions.PostgresError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom exception handler for consistent error responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
