"""Query execution route — POST /query"""
import time

import asyncpg
from fastapi import APIRouter, HTTPException, Request

from api.models import QueryRequest, QueryResponse, ErrorResponse
from core.config import settings

router = APIRouter(tags=["Query"])


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def execute_query(request: QueryRequest, req: Request):
    """Execute a read-only SQL query against the database.

    The query must be a SELECT statement. The sandbox user has SELECT-only
    access with a configurable timeout and row limit.

    - **query**: SQL SELECT statement
    - **timeout**: Optional query timeout in seconds (default from config)
    - **row_limit**: Optional maximum rows to return (default from config)
    """
    from api.app import pool  # imported here to avoid circular import at module load

    # Validate query
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Must start with SELECT
    if not query.upper().startswith("SELECT"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT queries are allowed",
        )

    # Check for forbidden keywords
    forbidden = [
        "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
        "ALTER", "TRUNCATE", "GRANT", "REVOKE",
    ]
    query_upper = query.upper()
    for keyword in forbidden:
        if keyword in query_upper:
            raise HTTPException(
                status_code=400,
                detail=f"Query contains forbidden keyword: {keyword}",
            )

    # Apply timeout and row limit
    timeout = request.timeout or settings.query_timeout_seconds
    row_limit = request.row_limit or settings.query_row_limit

    # Auto-inject LIMIT if not present
    if "LIMIT" not in query_upper and row_limit:
        query = f"{query.rstrip(';')} LIMIT {row_limit}"

    start_time = time.time()

    try:
        async with pool.acquire() as conn:
            await conn.execute(f"SET statement_timeout = '{timeout}s'")
            result = await conn.fetch(query)

            execution_time = (time.time() - start_time) * 1000

            if not result:
                return QueryResponse(
                    success=True,
                    row_count=0,
                    columns=[],
                    rows=[],
                    execution_time_ms=round(execution_time, 2),
                )

            columns = list(result[0].keys())
            rows = [dict(row) for row in result]

            return QueryResponse(
                success=True,
                row_count=len(rows),
                columns=columns,
                rows=rows,
                execution_time_ms=round(execution_time, 2),
            )

    except asyncpg.exceptions.QueryCanceledError:
        raise HTTPException(
            status_code=408,
            detail=f"Query timeout exceeded ({timeout}s)",
        )
    except asyncpg.exceptions.PostgresError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}",
        )
