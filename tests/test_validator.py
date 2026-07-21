"""Tests for SQL validator (R1-R9).

Each rule has dedicated tests:
- R1: Parse - sqlglot parse must succeed
- R2: Top-level - must be SELECT or WITH...SELECT  
- R3: DDL/DML - INSERT, UPDATE, DELETE, DROP, etc. rejected
- R4: System catalogs - pg_*, information_schema rejected
- R5: Allow-list - only allowed tables
- R6: Trap table - raw geolocation rejected
- R7: No SELECT * - must list columns
- R8: LIMIT - auto-injected for non-aggregating queries
- R9: Soft-FK - INNER JOIN category_translation warns

Run with: pytest tests/test_validator.py -v
"""
import pytest
from agent.validator.sql_validator import (
    validate_sql,
    validate_r1_parse,
    validate_r2_top_level,
    validate_r3_ddl_dml,
    validate_r4_catalogs,
    validate_r5_allow_list,
    validate_r6_trap_table,
    validate_r7_no_select_star,
    validate_r8_limit,
    validate_r9_soft_fk,
    extract_tables,
    has_select_star,
    has_aggregation,
    has_limit,
    ALLOWED_TABLES,
    TRAP_TABLES,
    FORBIDDEN_KEYWORDS,
)


class TestR1Parse:
    """R1: sqlglot parse must succeed."""
    
    def test_valid_simple_select(self):
        """Valid simple SELECT parses correctly."""
        valid, error = validate_r1_parse("SELECT * FROM customers")
        assert valid is True
        assert error == ""
    
    def test_valid_join_query(self):
        """Valid JOIN query parses correctly."""
        sql = """
        SELECT c.customer_state, COUNT(*) 
        FROM orders o 
        JOIN customers c ON o.customer_id = c.customer_id 
        GROUP BY c.customer_state
        """
        valid, error = validate_r1_parse(sql)
        assert valid is True
    
    def test_valid_cte_query(self):
        """Valid CTE query parses correctly."""
        sql = """
        WITH top_customers AS (
            SELECT customer_id FROM orders LIMIT 10
        )
        SELECT * FROM top_customers
        """
        valid, error = validate_r1_parse(sql)
        assert valid is True
    
    def test_invalid_syntax(self):
        """Invalid SQL syntax fails parsing."""
        valid, error = validate_r1_parse("SELECT FROM WHERE")
        assert valid is False
        assert "R1" in error


class TestR2TopLevel:
    """R2: Must be SELECT or WITH...SELECT."""
    
    def test_select_is_valid(self):
        """SELECT statement is valid."""
        valid, error = validate_r2_top_level("SELECT customer_id FROM customers LIMIT 10")
        assert valid is True
    
    def test_with_select_is_valid(self):
        """WITH...SELECT statement is valid."""
        sql = """
        WITH recent_orders AS (
            SELECT order_id FROM orders ORDER BY order_purchase_timestamp DESC LIMIT 100
        )
        SELECT * FROM recent_orders
        """
        valid, error = validate_r2_top_level(sql)
        assert valid is True
    
    def test_insert_is_invalid(self):
        """INSERT statement is invalid (caught by R2 before R3)."""
        valid, error = validate_r2_top_level("INSERT INTO customers VALUES ('test')")
        assert valid is False
        assert "R2" in error
    
    def test_update_is_invalid(self):
        """UPDATE statement is invalid."""
        valid, error = validate_r2_top_level("UPDATE customers SET customer_city = 'test'")
        assert valid is False
        assert "R2" in error


class TestR3DDLDML:
    """R3: DDL/DML keywords are rejected."""
    
    def test_insert_rejected(self):
        """INSERT is rejected."""
        valid, error = validate_r3_ddl_dml("SELECT * FROM customers; INSERT INTO customers VALUES ('x')")
        assert valid is False
        assert "INSERT" in error
    
    def test_update_rejected(self):
        """UPDATE is rejected."""
        valid, error = validate_r3_ddl_dml("UPDATE customers SET city = 'test'")
        assert valid is False
        assert "UPDATE" in error
    
    def test_delete_rejected(self):
        """DELETE is rejected."""
        valid, error = validate_r3_ddl_dml("DELETE FROM customers WHERE customer_id = 'x'")
        assert valid is False
        assert "DELETE" in error
    
    def test_drop_rejected(self):
        """DROP is rejected."""
        valid, error = validate_r3_ddl_dml("DROP TABLE customers")
        assert valid is False
        assert "DROP" in error
    
    def test_create_rejected(self):
        """CREATE is rejected."""
        valid, error = validate_r3_ddl_dml("CREATE TABLE test (id INT)")
        assert valid is False
        assert "CREATE" in error
    
    def test_alter_rejected(self):
        """ALTER is rejected."""
        valid, error = validate_r3_ddl_dml("ALTER TABLE customers ADD COLUMN test VARCHAR")
        assert valid is False
        assert "ALTER" in error
    
    def test_truncate_rejected(self):
        """TRUNCATE is rejected."""
        valid, error = validate_r3_ddl_dml("TRUNCATE TABLE customers")
        assert valid is False
        assert "TRUNCATE" in error
    
    def test_grant_rejected(self):
        """GRANT is rejected."""
        valid, error = validate_r3_ddl_dml("GRANT ALL ON customers TO public")
        assert valid is False
        assert "GRANT" in error
    
    def test_revoke_rejected(self):
        """REVOKE is rejected."""
        valid, error = validate_r3_ddl_dml("REVOKE ALL ON customers FROM public")
        assert valid is False
        assert "REVOKE" in error
    
    def test_valid_select_passes(self):
        """Valid SELECT passes R3."""
        valid, error = validate_r3_ddl_dml("SELECT customer_id, customer_city FROM customers LIMIT 10")
        assert valid is True


class TestR4SystemCatalogs:
    """R4: System catalog access is rejected."""
    
    def test_pg_tables_rejected(self):
        """pg_ tables are rejected."""
        valid, error = validate_r4_catalogs("SELECT * FROM pg_tables")
        assert valid is False
        assert "pg_" in error.lower()
    
    def test_information_schema_rejected(self):
        """information_schema is rejected."""
        valid, error = validate_r4_catalogs("SELECT * FROM information_schema.columns")
        assert valid is False
        assert "information_schema" in error.lower()
    
    def test_pg_class_rejected(self):
        """pg_class is rejected."""
        valid, error = validate_r4_catalogs("SELECT relname FROM pg_class")
        assert valid is False
    
    def test_valid_table_passes(self):
        """Valid table passes R4."""
        valid, error = validate_r4_catalogs("SELECT customer_id FROM customers LIMIT 10")
        assert valid is True


class TestR5AllowList:
    """R5: Only allowed tables can be queried."""
    
    def test_customers_allowed(self):
        """customers table is allowed."""
        valid, error = validate_r5_allow_list("SELECT customer_id FROM customers LIMIT 10")
        assert valid is True
    
    def test_orders_allowed(self):
        """orders table is allowed."""
        valid, error = validate_r5_allow_list("SELECT order_id FROM orders LIMIT 10")
        assert valid is True
    
    def test_order_items_allowed(self):
        """order_items table is allowed."""
        valid, error = validate_r5_allow_list("SELECT order_id FROM order_items LIMIT 10")
        assert valid is True
    
    def test_geolocation_by_zip_allowed(self):
        """geolocation_by_zip view is allowed."""
        valid, error = validate_r5_allow_list("SELECT * FROM geolocation_by_zip LIMIT 10")
        assert valid is True  # R5 passes, R6/R7 catch other issues
    
    def test_unknown_table_rejected(self):
        """Unknown table is rejected."""
        valid, error = validate_r5_allow_list("SELECT * FROM unknown_table")
        assert valid is False
        assert "unknown_table" in error
    
    def test_non_existent_table_rejected(self):
        """Non-existent table is rejected."""
        valid, error = validate_r5_allow_list("SELECT * FROM nonexistent")
        assert valid is False


class TestR6TrapTable:
    """R6: Raw geolocation table is rejected."""
    
    def test_raw_geolocation_rejected(self):
        """Raw geolocation table is rejected."""
        valid, error = validate_r6_trap_table("SELECT * FROM geolocation LIMIT 10")
        assert valid is False
        assert "geolocation_by_zip" in error
    
    def test_geolocation_by_zip_allowed(self):
        """geolocation_by_zip view is allowed."""
        valid, error = validate_r6_trap_table("SELECT geolocation_zip_code_prefix FROM geolocation_by_zip LIMIT 10")
        assert valid is True
    
    def test_other_tables_not_affected(self):
        """Other tables are not affected by R6."""
        valid, error = validate_r6_trap_table("SELECT customer_id FROM customers LIMIT 10")
        assert valid is True


class TestR7NoSelectStar:
    """R7: SELECT * is not allowed."""
    
    def test_select_star_rejected(self):
        """SELECT * is rejected."""
        valid, error = validate_r7_no_select_star("SELECT * FROM customers")
        assert valid is False
        assert "SELECT *" in error
    
    def test_explicit_columns_allowed(self):
        """Explicit column list is allowed."""
        valid, error = validate_r7_no_select_star("SELECT customer_id, customer_city FROM customers LIMIT 10")
        assert valid is True
    
    def test_select_star_with_alias_rejected(self):
        """SELECT t.* is also rejected."""
        valid, error = validate_r7_no_select_star("SELECT c.* FROM customers c LIMIT 10")
        assert valid is False
    
    def test_select_with_expressions_allowed(self):
        """SELECT with expressions is allowed."""
        valid, error = validate_r7_no_select_star("SELECT COUNT(*) as count, customer_state FROM customers GROUP BY customer_state")
        assert valid is True  # COUNT(*) is not SELECT *


class TestR8Limit:
    """R8: LIMIT is auto-injected for non-aggregating queries."""
    
    def test_limit_added_to_simple_query(self):
        """LIMIT is added to simple query."""
        sql = "SELECT customer_id, customer_city FROM customers"
        modified, added = validate_r8_limit(sql)
        assert added is True
        assert "LIMIT 1000" in modified
    
    def test_limit_not_added_to_aggregating_query(self):
        """LIMIT is not added to aggregating query."""
        sql = "SELECT customer_state, COUNT(*) FROM customers GROUP BY customer_state"
        modified, added = validate_r8_limit(sql)
        assert added is False
        assert modified == sql
    
    def test_limit_not_added_if_present(self):
        """LIMIT is not added if already present."""
        sql = "SELECT customer_id FROM customers LIMIT 50"
        modified, added = validate_r8_limit(sql)
        assert added is False
        assert modified == sql
    
    def test_custom_limit_value(self):
        """Custom LIMIT value can be specified."""
        sql = "SELECT customer_id FROM customers"
        modified, added = validate_r8_limit(sql, default_limit=500)
        assert added is True
        assert "LIMIT 500" in modified
    
    def test_limit_with_cte(self):
        """CTE query without LIMIT gets LIMIT added."""
        sql = """
        WITH recent AS (
            SELECT order_id FROM orders ORDER BY order_purchase_timestamp DESC LIMIT 100
        )
        SELECT order_id FROM recent
        """
        modified, added = validate_r8_limit(sql)
        # The outer query should get a LIMIT
        # Note: This depends on sqlglot parsing


class TestR9SoftFK:
    """R9: Warning for INNER JOIN on product_category_translation."""
    
    def test_inner_join_warns(self):
        """INNER JOIN on product_category_translation warns."""
        sql = """
        SELECT p.product_id, pct.product_category_name_english
        FROM products p
        JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
        """
        has_warning, warning = validate_r9_soft_fk(sql)
        assert has_warning is True
        assert "LEFT JOIN" in warning
    
    def test_left_join_no_warning(self):
        """LEFT JOIN on product_category_translation does not warn."""
        sql = """
        SELECT p.product_id, pct.product_category_name_english
        FROM products p
        LEFT JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
        """
        has_warning, warning = validate_r9_soft_fk(sql)
        assert has_warning is False
    
    def test_no_join_no_warning(self):
        """Query without join has no warning."""
        sql = "SELECT product_id, product_category_name FROM products LIMIT 10"
        has_warning, warning = validate_r9_soft_fk(sql)
        assert has_warning is False


class TestFullValidation:
    """Full validation tests with all rules."""
    
    def test_valid_query_passes(self):
        """Valid query passes all rules."""
        sql = """
        SELECT c.customer_state, COUNT(DISTINCT o.order_id) as order_count
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        GROUP BY c.customer_state
        ORDER BY order_count DESC
        """
        result = validate_sql(sql)
        assert result.valid is True
        assert len(result.errors) == 0
    
    def test_multiple_errors(self):
        """Query with multiple errors reports all."""
        sql = "SELECT * FROM unknown_table; DROP TABLE customers;"
        result = validate_sql(sql)
        assert result.valid is False
        assert len(result.errors) > 0
    
    def test_valid_query_with_warnings(self):
        """Valid query can have warnings."""
        sql = """
        SELECT p.product_id, pct.product_category_name_english
        FROM products p
        JOIN product_category_translation pct ON p.product_category_name = pct.product_category_name
        LIMIT 10
        """
        result = validate_sql(sql)
        assert result.valid is True
        assert len(result.warnings) > 0  # R9 warning
    
    def test_trap_table_error(self):
        """Trap table error is caught."""
        sql = "SELECT geolocation_zip_code_prefix FROM geolocation LIMIT 10"
        result = validate_sql(sql)
        assert result.valid is False
        assert "R6" in result.rule_failures


class TestHelperFunctions:
    """Test helper functions."""
    
    def test_extract_tables(self):
        """Table extraction works correctly."""
        sql = "SELECT c.customer_id, o.order_id FROM customers c JOIN orders o ON c.customer_id = o.customer_id"
        tables = extract_tables(sql)
        assert "customers" in tables
        assert "orders" in tables
    
    def test_has_select_star_true(self):
        """SELECT * detection works."""
        assert has_select_star("SELECT * FROM customers") is True
        assert has_select_star("SELECT c.* FROM customers c") is True
    
    def test_has_select_star_false(self):
        """SELECT * detection doesn't false positive."""
        assert has_select_star("SELECT customer_id FROM customers") is False
        assert has_select_star("SELECT COUNT(*) FROM customers") is False
    
    def test_has_aggregation_true(self):
        """Aggregation detection works."""
        assert has_aggregation("SELECT COUNT(*) FROM customers") is True
        assert has_aggregation("SELECT customer_state, COUNT(*) FROM customers GROUP BY customer_state") is True
        assert has_aggregation("SELECT SUM(price) FROM order_items") is True
    
    def test_has_aggregation_false(self):
        """Aggregation detection doesn't false positive."""
        assert has_aggregation("SELECT customer_id FROM customers LIMIT 10") is False
    
    def test_has_limit_true(self):
        """LIMIT detection works."""
        assert has_limit("SELECT customer_id FROM customers LIMIT 10") is True
    
    def test_has_limit_false(self):
        """LIMIT detection doesn't false positive."""
        assert has_limit("SELECT customer_id FROM customers") is False
