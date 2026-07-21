# Text2SQL Test Suite

Database and API tests for the Text2SQL application.

## Test Structure

```
tests/
├── db_tests.py              # Main test runner (runs all tests)
├── test_health.py           # Health endpoint tests
├── test_db_dataloader.py    # Data loader verification tests
├── test_db_permissions.py   # Read-only permission tests
└── test_api_response.py     # API response format tests
```

## Running Tests

### Run All Tests
```bash
uv run python tests/db_tests.py
```

### Run Individual Test Modules
```bash
# Health endpoint tests
uv run python tests/test_health.py

# Data loader tests
uv run python tests/test_db_dataloader.py

# Permission tests
uv run python tests/test_db_permissions.py

# API response tests
uv run python tests/test_api_response.py
```

## Test Categories

### 1. Health Endpoint Tests (`test_health.py`)
- Tests GET /health endpoint
- Verifies database connectivity
- Checks response format

### 2. Data Loader Tests (`test_db_dataloader.py`)
- Verifies all 9 tables were loaded
- Checks row counts match expected values
- Tests sample SELECT queries with:
  - WHERE clauses
  - JOINs
  - Aggregations
  - Calculations

### 3. Database Permission Tests (`test_db_permissions.py`)
- **API Level**: Tests that forbidden keywords are blocked:
  - INSERT, UPDATE, DELETE
  - DROP, CREATE, ALTER, TRUNCATE
  - GRANT, REVOKE
- **Database Level**: Verifies sandbox user permissions:
  - SELECT works
  - INSERT fails (InsufficientPrivilegeError)
  - UPDATE fails (InsufficientPrivilegeError)
  - DELETE fails (InsufficientPrivilegeError)
  - DROP fails (InsufficientPrivilegeError)
  - CREATE fails (permission denied)

### 4. API Response Tests (`test_api_response.py`)
- Response format validation
- Error handling tests
- Row limit enforcement tests

## Prerequisites

Before running tests:
1. PostgreSQL must be running (Docker container or local)
2. Database must be initialized with `uv run python -m database.setup_db`
3. API server must be running at `http://localhost:8000`

Start the API:
```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Test Output

The test suite provides detailed output with:
- ✅ PASS for successful tests
- ❌ FAIL for failed tests
- Summary of all test categories
- Total pass/fail count

Example:
```
======================================================================
  TEST SUMMARY
======================================================================
  ✅ PASS - Health Endpoint
  ✅ PASS - Data Loader
  ✅ PASS - Database Permissions
  ✅ PASS - API Response

----------------------------------------------------------------------
  Total: 4/4 test suites passed

  🎉 All tests passed! The API is working correctly with proper read-only security.
======================================================================
```
