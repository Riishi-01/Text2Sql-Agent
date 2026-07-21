"""
Health endpoint tests for Text2SQL API.

Tests the GET /health endpoint for database connectivity.

Run with: uv run python tests/test_health.py
"""
import requests

BASE_URL = "http://localhost:8000"


def test_health_endpoint():
    """Test GET /health endpoint."""
    print("\n" + "=" * 60)
    print("Testing Health Endpoint")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ PASS - Health check returns 200")
            print(f"    Status: {data.get('status')}, DB: {data.get('database')}, Ping: {data.get('ping_ms')}ms")
            return True
        else:
            print(f"❌ FAIL - Health check returns 200 - Got status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ FAIL - Health check returns 200 - {str(e)}")
        return False


def run_tests():
    """Run all health tests."""
    return test_health_endpoint()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
