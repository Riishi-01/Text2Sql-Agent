"""
Database dataloader tests for Text2SQL API.

Tests that all Olist dataset tables were loaded correctly.

Run with: uv run python tests/test_db_dataloader.py
"""
import requests

BASE_URL = "http://localhost:8000"


def test_select_queries():
    """Test various SELECT queries to verify data was loaded correctly."""
    print("\n" + "=" * 60)
    print("Testing Database Data Loader")
    print("=" * 60)
    
    # Expected row counts based on loaded data
    table_info = [
        {"name": "customers", "table": "customers", "expected_min": 99000},
        {"name": "sellers", "table": "sellers", "expected_min": 3000},
        {"name": "products", "table": "products", "expected_min": 32000},
        {"name": "product_category_translation", "table": "product_category_translation", "expected_min": 70},
        {"name": "orders", "table": "orders", "expected_min": 99000},
        {"name": "order_items", "table": "order_items", "expected_min": 110000},
        {"name": "order_payments", "table": "order_payments", "expected_min": 100000},
        {"name": "order_reviews", "table": "order_reviews", "expected_min": 98000},
        {"name": "geolocation", "table": "geolocation", "expected_min": 900000},
    ]
    
    all_passed = True
    
    for info in table_info:
        try:
            response = requests.post(
                f"{BASE_URL}/query",
                json={"query": f"SELECT COUNT(*) as count FROM {info['table']}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                count = data["rows"][0]["count"]
                
                if count >= info["expected_min"]:
                    print(f"✅ PASS - {info['name']} table loaded")
                    print(f"    {count} rows (expected >= {info['expected_min']})")
                else:
                    print(f"❌ FAIL - {info['name']} table loaded")
                    print(f"    {count} rows (expected >= {info['expected_min']})")
                    all_passed = False
            else:
                print(f"❌ FAIL - {info['name']} table loaded - Status {response.status_code}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ FAIL - {info['name']} table loaded - {str(e)}")
            all_passed = False
    
    return all_passed


def test_sample_queries():
    """Test sample queries to verify data integrity."""
    print("\n" + "-" * 60)
    print("Testing Sample Queries")
    print("-" * 60)
    
    test_cases = [
        {
            "name": "SELECT with WHERE clause",
            "query": "SELECT * FROM orders WHERE order_status = 'delivered' LIMIT 10",
            "expected_min_rows": 1,
            "expected_max_rows": 10
        },
        {
            "name": "SELECT with JOIN",
            "query": """
                SELECT o.order_id, c.customer_city, o.order_status
                FROM orders o
                JOIN customers c ON o.customer_id = c.customer_id
                LIMIT 5
            """,
            "expected_min_rows": 1,
            "expected_max_rows": 5
        },
        {
            "name": "SELECT with aggregation",
            "query": "SELECT customer_state, COUNT(*) as count FROM customers GROUP BY customer_state ORDER BY count DESC LIMIT 5",
            "expected_min_rows": 1,
            "expected_max_rows": 5
        },
        {
            "name": "SELECT from order_items with calculation",
            "query": "SELECT order_id, price, freight_value, (price + freight_value) as total FROM order_items LIMIT 5",
            "expected_min_rows": 1,
            "expected_max_rows": 5
        },
        {
            "name": "SELECT from order_payments grouped by type",
            "query": "SELECT payment_type, COUNT(*) as count, SUM(payment_value) as total FROM order_payments GROUP BY payment_type",
            "expected_min_rows": 1,
            "expected_max_rows": 10
        },
    ]
    
    all_passed = True
    
    for test in test_cases:
        try:
            response = requests.post(
                f"{BASE_URL}/query",
                json={"query": test["query"]},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                row_count = data.get("row_count", 0)
                
                if test["expected_min_rows"] <= row_count <= test["expected_max_rows"]:
                    print(f"✅ PASS - {test['name']}")
                    print(f"    Returned {row_count} rows in {data.get('execution_time_ms')}ms")
                else:
                    print(f"❌ FAIL - {test['name']}")
                    print(f"    Expected {test['expected_min_rows']}-{test['expected_max_rows']} rows, got {row_count}")
                    all_passed = False
            else:
                print(f"❌ FAIL - {test['name']} - Status {response.status_code}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ FAIL - {test['name']} - {str(e)}")
            all_passed = False
    
    return all_passed


def run_tests():
    """Run all dataloader tests."""
    passed = test_select_queries() and test_sample_queries()
    return passed


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
