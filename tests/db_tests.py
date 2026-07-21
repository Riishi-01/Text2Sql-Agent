"""
Main test runner for Text2SQL database tests.

This script runs all database-related test modules:
- test_health.py - Health endpoint tests
- test_db_dataloader.py - Data loader verification
- test_db_permissions.py - Read-only permission tests
- test_api_response.py - API response format and error handling

Run with: uv run python tests/db_tests.py
"""
import sys
import time
from pathlib import Path

# Add tests directory to path
sys.path.insert(0, str(Path(__file__).parent))

from test_health import run_tests as run_health_tests
from test_db_dataloader import run_tests as run_dataloader_tests
from test_db_permissions import run_tests as run_permission_tests
from test_api_response import run_tests as run_response_tests


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_summary(results: dict):
    """Print test summary."""
    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {name}")
    
    print("\n" + "-" * 70)
    print(f"  Total: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n  🎉 All tests passed! The API is working correctly with proper read-only security.")
    else:
        print(f"\n  ⚠️  {total - passed} test suite(s) failed. Please review the results above.")
    
    print("=" * 70)


def run_all_tests():
    """Run all database test suites."""
    print_header("Text2SQL Database Test Suite")
    print(f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  API URL: http://localhost:8000")
    
    results = {}
    
    # Run each test suite
    print_header("1. Health Endpoint Tests")
    results["Health Endpoint"] = run_health_tests()
    
    print_header("2. Data Loader Tests")
    results["Data Loader"] = run_dataloader_tests()
    
    print_header("3. Database Permission Tests")
    results["Database Permissions"] = run_permission_tests()
    
    print_header("4. API Response Tests")
    results["API Response"] = run_response_tests()
    
    # Print summary
    print_summary(results)
    
    return all(results.values())


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
