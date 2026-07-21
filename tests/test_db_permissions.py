"""
Database permissions tests for Text2SQL API.

Tests that the sandbox user has proper read-only permissions.

Run with: uv run python tests/test_db_permissions.py
"""
import requests
import asyncio
import asyncpg

BASE_URL = "http://localhost:8000"


def test_api_level_permissions():
    """Test that write operations are blocked at API level."""
    print("\n" + "=" * 60)
    print("Testing API-Level Permissions")
    print("=" * 60)
    
    forbidden_tests = [
        {"name": "INSERT blocked", "query": "INSERT INTO customers (customer_id) VALUES ('test123')"},
        {"name": "UPDATE blocked", "query": "UPDATE customers SET customer_city = 'test' WHERE customer_id = '06b8999e2fba1a1fbc88172c00ba8bc7'"},
        {"name": "DELETE blocked", "query": "DELETE FROM customers WHERE customer_id = 'test'"},
        {"name": "DROP TABLE blocked", "query": "DROP TABLE customers"},
        {"name": "CREATE TABLE blocked", "query": "CREATE TABLE test_table (id INT)"},
        {"name": "ALTER TABLE blocked", "query": "ALTER TABLE customers ADD COLUMN test_column VARCHAR(50)"},
        {"name": "TRUNCATE blocked", "query": "TRUNCATE TABLE customers"},
        {"name": "GRANT blocked", "query": "GRANT ALL ON customers TO public"},
        {"name": "REVOKE blocked", "query": "REVOKE ALL ON customers FROM public"},
    ]
    
    all_passed = True
    
    for test in forbidden_tests:
        try:
            response = requests.post(
                f"{BASE_URL}/query",
                json={"query": test["query"]},
                timeout=5
            )
            
            if response.status_code == 400:
                error_detail = response.json().get("error", "")
                if "forbidden" in error_detail.lower() or "only select" in error_detail.lower():
                    print(f"✅ PASS - {test['name']}")
                    print(f"    Correctly blocked at API level")
                else:
                    print(f"✅ PASS - {test['name']}")
                    print(f"    Blocked with: {error_detail}")
            elif response.status_code == 403:
                print(f"✅ PASS - {test['name']}")
                print(f"    Blocked by database permissions")
            else:
                print(f"❌ FAIL - {test['name']}")
                print(f"    Expected 400/403, got {response.status_code}: {response.text}")
                all_passed = False
                
        except Exception as e:
            print(f"❌ FAIL - {test['name']} - {str(e)}")
            all_passed = False
    
    return all_passed


def test_database_level_permissions():
    """Test database permissions directly via asyncpg."""
    print("\n" + "=" * 60)
    print("Testing Database-Level Permissions")
    print("=" * 60)
    
    async def test_db():
        results = []
        
        try:
            conn = await asyncpg.connect(
                host='localhost',
                port=5432,
                user='sandbox',
                password='sandbox_password',
                database='text2sql'
            )
            
            # Test 1: SELECT should work
            try:
                result = await conn.fetchval("SELECT COUNT(*) FROM customers")
                results.append(("Sandbox user can SELECT", True, f"Count: {result}"))
            except Exception as e:
                results.append(("Sandbox user can SELECT", False, str(e)))
            
            # Test 2: INSERT should fail
            try:
                await conn.execute("INSERT INTO customers (customer_id) VALUES ('test_permission_check')")
                results.append(("Sandbox user cannot INSERT", False, "INSERT succeeded but should have failed"))
            except asyncpg.exceptions.InsufficientPrivilegeError:
                results.append(("Sandbox user cannot INSERT", True, "Correctly denied by database"))
            except Exception as e:
                results.append(("Sandbox user cannot INSERT", True, f"Blocked: {type(e).__name__}"))
            
            # Test 3: UPDATE should fail
            try:
                await conn.execute("UPDATE customers SET customer_city = 'test' WHERE customer_id = 'test'")
                results.append(("Sandbox user cannot UPDATE", False, "UPDATE succeeded but should have failed"))
            except asyncpg.exceptions.InsufficientPrivilegeError:
                results.append(("Sandbox user cannot UPDATE", True, "Correctly denied by database"))
            except Exception as e:
                results.append(("Sandbox user cannot UPDATE", True, f"Blocked: {type(e).__name__}"))
            
            # Test 4: DELETE should fail
            try:
                await conn.execute("DELETE FROM customers WHERE customer_id = 'test'")
                results.append(("Sandbox user cannot DELETE", False, "DELETE succeeded but should have failed"))
            except asyncpg.exceptions.InsufficientPrivilegeError:
                results.append(("Sandbox user cannot DELETE", True, "Correctly denied by database"))
            except Exception as e:
                results.append(("Sandbox user cannot DELETE", True, f"Blocked: {type(e).__name__}"))
            
            # Test 5: DROP should fail
            try:
                await conn.execute("DROP TABLE customers")
                results.append(("Sandbox user cannot DROP", False, "DROP succeeded but should have failed"))
            except asyncpg.exceptions.InsufficientPrivilegeError:
                results.append(("Sandbox user cannot DROP", True, "Correctly denied by database"))
            except Exception as e:
                results.append(("Sandbox user cannot DROP", True, f"Blocked: {type(e).__name__}"))
            
            # Test 6: CREATE should fail
            try:
                await conn.execute("CREATE TABLE test_table (id INT)")
                results.append(("Sandbox user cannot CREATE", False, "CREATE succeeded but should have failed"))
            except asyncpg.exceptions.InsufficientPrivilegeError:
                results.append(("Sandbox user cannot CREATE", True, "Correctly denied by database"))
            except Exception as e:
                results.append(("Sandbox user cannot CREATE", True, f"Blocked: {type(e).__name__}"))
            
            await conn.close()
            
        except Exception as e:
            results.append(("Database connection", False, str(e)))
        
        return results
    
    results = asyncio.run(test_db())
    
    all_passed = True
    for name, success, detail in results:
        if success:
            print(f"✅ PASS - {name}")
            print(f"    {detail}")
        else:
            print(f"❌ FAIL - {name}")
            print(f"    {detail}")
            all_passed = False
    
    return all_passed


def run_tests():
    """Run all permission tests."""
    passed = test_api_level_permissions() and test_database_level_permissions()
    return passed


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
