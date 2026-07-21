"""
API response format tests for Text2SQL API.

Tests API response structure and error handling.

Run with: uv run python tests/test_api_response.py
"""
import requests

BASE_URL = "http://localhost:8000"


def test_response_format():
    """Test API response format."""
    print("\n" + "=" * 60)
    print("Testing Response Format")
    print("=" * 60)
    
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            json={"query": "SELECT * FROM customers LIMIT 1"},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            
            required_fields = ["success", "row_count", "columns", "rows", "execution_time_ms"]
            missing_fields = [f for f in required_fields if f not in data]
            
            if not missing_fields:
                print(f"✅ PASS - Response contains all required fields")
                print(f"    Fields: {list(data.keys())}")
                
                # Check data types
                type_checks = [
                    ("success is boolean", isinstance(data["success"], bool)),
                    ("row_count is integer", isinstance(data["row_count"], int)),
                    ("columns is list", isinstance(data["columns"], list)),
                    ("rows is list", isinstance(data["rows"], list)),
                    ("execution_time_ms is number", isinstance(data["execution_time_ms"], (int, float)))
                ]
                
                all_type_checks_pass = True
                for check_name, check_result in type_checks:
                    if check_result:
                        print(f"✅ PASS - {check_name}")
                    else:
                        print(f"❌ FAIL - {check_name}")
                        all_type_checks_pass = False
                
                return all_type_checks_pass
            else:
                print(f"❌ FAIL - Response contains all required fields")
                print(f"    Missing: {missing_fields}")
                return False
        else:
            print(f"❌ FAIL - Response format test - Status: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ FAIL - Response format test - {str(e)}")
        return False


def test_error_handling():
    """Test error handling for invalid queries."""
    print("\n" + "=" * 60)
    print("Testing Error Handling")
    print("=" * 60)
    
    test_cases = [
        {"name": "Invalid SQL syntax", "query": "SELECT * FORM customers", "expected_status": 400},
        {"name": "Non-existent table", "query": "SELECT * FROM non_existent_table", "expected_status": 400},
        {"name": "Empty query", "query": "", "expected_status": 400},
        {"name": "Non-SELECT statement (subquery injection)", "query": "SELECT * FROM customers; DROP TABLE customers;--", "expected_status": 400},
        {"name": "Query with timeout parameter", "query": "SELECT * FROM customers LIMIT 1", "expected_status": 200, "timeout": 5},
        {"name": "Query with row_limit parameter", "query": "SELECT * FROM customers", "expected_status": 200, "row_limit": 10},
    ]
    
    all_passed = True
    
    for test in test_cases:
        try:
            payload = {"query": test["query"]}
            if "timeout" in test:
                payload["timeout"] = test["timeout"]
            if "row_limit" in test:
                payload["row_limit"] = test["row_limit"]
            
            response = requests.post(
                f"{BASE_URL}/query",
                json=payload,
                timeout=5
            )
            
            if response.status_code == test["expected_status"]:
                print(f"✅ PASS - {test['name']}")
                print(f"    Got expected status {test['expected_status']}")
            else:
                print(f"❌ FAIL - {test['name']}")
                print(f"    Expected status {test['expected_status']}, got {response.status_code}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ FAIL - {test['name']} - {str(e)}")
            all_passed = False
    
    return all_passed


def test_row_limit():
    """Test row limit enforcement."""
    print("\n" + "=" * 60)
    print("Testing Row Limit Enforcement")
    print("=" * 60)
    
    all_passed = True
    
    # Test 1: Query without explicit limit (should be capped at default 10000)
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            json={"query": "SELECT * FROM geolocation"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            row_count = data.get("row_count", 0)
            
            if row_count <= 10000:
                print(f"✅ PASS - Default row limit (10000) enforced")
                print(f"    Query returned {row_count} rows (capped at 10000)")
            else:
                print(f"❌ FAIL - Default row limit (10000) enforced")
                print(f"    Query returned {row_count} rows, expected <= 10000")
                all_passed = False
        else:
            print(f"❌ FAIL - Default row limit (10000) enforced - {response.text}")
            all_passed = False
            
    except Exception as e:
        print(f"❌ FAIL - Default row limit (10000) enforced - {str(e)}")
        all_passed = False
    
    # Test 2: Custom row limit
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            json={"query": "SELECT * FROM customers", "row_limit": 50},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            row_count = data.get("row_count", 0)
            
            if row_count <= 50:
                print(f"✅ PASS - Custom row limit (50) enforced")
                print(f"    Query returned {row_count} rows")
            else:
                print(f"❌ FAIL - Custom row limit (50) enforced")
                print(f"    Query returned {row_count} rows, expected <= 50")
                all_passed = False
        else:
            print(f"❌ FAIL - Custom row limit (50) enforced - {response.text}")
            all_passed = False
            
    except Exception as e:
        print(f"❌ FAIL - Custom row limit (50) enforced - {str(e)}")
        all_passed = False
    
    return all_passed


def run_tests():
    """Run all API response tests."""
    passed = test_response_format() and test_error_handling() and test_row_limit()
    return passed


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
