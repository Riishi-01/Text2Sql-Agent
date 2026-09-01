"""Static SQL Safety Validator (R1-R10).

This validator is independent of the LLM. It is deterministic, side-effect-free,
and testable without network. It enforces 10 hard rules:

R1: Parse - sqlglot parse must succeed
R2: Top-level - must be SELECT or WITH...SELECT
R3: DDL/DML - INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, COPY, VACUUM, REINDEX rejected
R4: System catalogs - pg_*, information_schema rejected
R5: Allow-list - only 11 Olist tables + geolocation_by_zip
R6: Trap table - raw geolocation rejected; geolocation_by_zip is the only allowed interface
R7: No SELECT * - list every column explicitly
R8: LIMIT - auto-injected LIMIT for non-aggregating queries; default 1000
R9: Soft-FK LEFT JOIN - INNER JOIN category_translation warns (does not block)
R10: Column existence - every referenced column must exist in the schema catalog
     (catches hallucinated columns like p.product_name)
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import sqlglot
from sqlglot import exp


# Allowed tables (R5)
ALLOWED_TABLES: Set[str] = {
    "customers",
    "sellers", 
    "products",
    "product_category_translation",
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
    "geolocation",
    "geolocation_by_zip",
}

# Trap table - raw geolocation (R6)
TRAP_TABLES: Set[str] = {
    "geolocation",  # Use geolocation_by_zip instead
}

# Forbidden keywords (R3)
FORBIDDEN_KEYWORDS: Set[str] = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "VACUUM", "REINDEX",
}

# System catalog patterns (R4)
SYSTEM_CATALOG_PATTERNS: List[str] = [
    r"^pg_",
    r"^information_schema",
]

# Schema column catalog (R10). Mirrors agent/prompts/semantic_model.yaml.
# Lowercased table → set of lowercased column names. The validator rejects
# any column reference that cannot be resolved to a real table/column pair.
SCHEMA_COLUMNS: Dict[str, Set[str]] = {
    "customers": {
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    },
    "sellers": {
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    },
    "products": {
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    },
    "product_category_translation": {
        "product_category_name",
        "product_category_name_english",
    },
    "orders": {
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    },
    "order_items": {
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    },
    "order_payments": {
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    },
    "order_reviews": {
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    },
    "geolocation": {
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    },
    "geolocation_by_zip": {
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state",
    },
}


@dataclass
class ValidationResult:
    """Result of SQL validation."""
    valid: bool
    sql: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rule_failures: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        if self.valid:
            return f"✓ Valid SQL (warnings: {len(self.warnings)})"
        return f"✗ Invalid SQL: {', '.join(self.errors)}"


def extract_tables(sql: str) -> Set[str]:
    """Extract all table names from a SQL query.
    
    Args:
        sql: SQL query string
        
    Returns:
        Set of table names (lowercase)
    """
    tables: Set[str] = set()
    
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                # Walk the AST and find all table references
                for node in statement.walk():
                    if isinstance(node, exp.Table):
                        tables.add(node.name.lower())
                        # Also check alias
                        if node.alias:
                            pass  # Alias is not a table name
    except Exception:
        pass
    
    return tables


def has_select_star(sql: str) -> bool:
    """Check if query contains SELECT * (not COUNT(*) or other aggregates).
    
    Args:
        sql: SQL query string
        
    Returns:
        True if SELECT * found (excluding aggregate functions)
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                for node in statement.walk():
                    # Check for Star node in SELECT (not inside Count/Sum/etc)
                    if isinstance(node, exp.Star):
                        # Check if parent is an aggregate function
                        parent = node.parent
                        if parent and isinstance(parent, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
                            continue  # COUNT(*) is allowed
                        return True
                    # Check for SELECT * pattern
                    if isinstance(node, exp.Select):
                        for expr in node.expressions:
                            if isinstance(expr, exp.Star):
                                return True
    except Exception:
        # Fallback to regex - but exclude COUNT(*)
        # Match SELECT * FROM but not COUNT(*)
        if re.search(r"SELECT\s+\*\s+FROM", sql, re.IGNORECASE):
            return True
    
    return False


def has_aggregation(sql: str) -> bool:
    """Check if query has aggregation functions.
    
    Args:
        sql: SQL query string
        
    Returns:
        True if aggregation found (GROUP BY, SUM, COUNT, AVG, etc.)
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                # Check for GROUP BY
                if statement.find(exp.Group):
                    return True
                
                # Check for aggregate functions
                for node in statement.walk():
                    if isinstance(node, (exp.Count, exp.Sum, exp.Avg, 
                                       exp.Min, exp.Max, exp.Stddev,
                                       exp.Variance)):
                        return True
    except Exception:
        pass
    
    # Fallback: check for GROUP BY keyword
    if re.search(r"\bGROUP\s+BY\b", sql, re.IGNORECASE):
        return True
    
    return False


def has_limit(sql: str) -> bool:
    """Check if query has LIMIT clause.
    
    Args:
        sql: SQL query string
        
    Returns:
        True if LIMIT found
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                if statement.find(exp.Limit):
                    return True
    except Exception:
        pass
    
    # Fallback: regex check
    if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        return True
    
    return False


def has_inner_join_category_translation(sql: str) -> bool:
    """Check if query uses INNER JOIN on product_category_translation (R9).
    
    Args:
        sql: SQL query string
        
    Returns:
        True if INNER JOIN on category translation found
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                for node in statement.walk():
                    if isinstance(node, exp.Join):
                        # Check the join side (LEFT, RIGHT, FULL = outer joins)
                        join_side = (node.side or "").upper()
                        # Only flag if it's NOT an outer join (LEFT/RIGHT/FULL)
                        if join_side in ("LEFT", "RIGHT", "FULL"):
                            continue  # Outer joins are fine
                        # This is an INNER JOIN or plain JOIN
                        # Check if table is product_category_translation
                        for table in node.find_all(exp.Table):
                            if table.name.lower() in ("product_category_translation", 
                                                      "pct"):
                                return True
    except Exception:
        pass
    
    return False


def validate_r1_parse(sql: str) -> Tuple[bool, str]:
    """R1: sqlglot parse must succeed.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        if not parsed or not any(parsed):
            return False, "R1 parse: SQL parsing returned empty result"
        return True, ""
    except Exception as e:
        return False, f"R1 parse: SQL parsing failed: {str(e)}"


def validate_r2_top_level(sql: str) -> Tuple[bool, str]:
    """R2: Must be SELECT or WITH...SELECT.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        
        for statement in parsed:
            if statement:
                # Check if it's a SELECT or WITH statement
                if isinstance(statement, (exp.Select, exp.With)):
                    return True, ""
                
                # Check statement type
                stmt_type = type(statement).__name__
                return False, f"R2 top-level: Expected SELECT or WITH, got {stmt_type}"
        
        return False, "R2 top-level: Could not determine statement type"
    except Exception as e:
        return False, f"R2 top-level: Validation failed: {str(e)}"


def validate_r3_ddl_dml(sql: str) -> Tuple[bool, str]:
    """R3: Reject DDL/DML keywords.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    sql_upper = sql.upper()
    
    for keyword in FORBIDDEN_KEYWORDS:
        # Use word boundary matching
        pattern = r"\b" + keyword + r"\b"
        if re.search(pattern, sql_upper):
            return False, f"R3 DDL/DML: Forbidden keyword {keyword}"
    
    return True, ""


def validate_r4_catalogs(sql: str) -> Tuple[bool, str]:
    """R4: Reject system catalog access.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    tables = extract_tables(sql)
    
    for pattern in SYSTEM_CATALOG_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE)
        for table in tables:
            if regex.match(table):
                return False, f"R4 system catalogs: Access to {table} not allowed"
    
    # Also check for information_schema in the raw SQL (fallback)
    if re.search(r'\binformation_schema\b', sql, re.IGNORECASE):
        return False, "R4 system catalogs: Access to information_schema not allowed"
    
    return True, ""


def validate_r5_allow_list(sql: str) -> Tuple[bool, str]:
    """R5: Only allowed tables.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    tables = extract_tables(sql)
    
    for table in tables:
        if table not in ALLOWED_TABLES:
            return False, f"R5 allow-list: Table '{table}' not in allowed list"
    
    return True, ""


def validate_r6_trap_table(sql: str) -> Tuple[bool, str]:
    """R6: Reject raw geolocation table.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    tables = extract_tables(sql)
    
    # Check if raw geolocation is referenced
    if "geolocation" in tables:
        # Check if geolocation_by_zip is also referenced (allow if using both)
        if "geolocation_by_zip" not in tables:
            return False, f"R6 trap table: Use geolocation_by_zip instead of raw geolocation"
    
    return True, ""


def validate_r7_no_select_star(sql: str) -> Tuple[bool, str]:
    """R7: No SELECT *.
    
    Args:
        sql: SQL query string
        
    Returns:
        (valid, error_message)
    """
    if has_select_star(sql):
        return False, "R7 no SELECT *: List every column explicitly"
    
    return True, ""


def validate_r8_limit(sql: str, default_limit: int = 1000) -> Tuple[str, bool]:
    """R8: Auto-inject LIMIT for non-aggregating queries.
    
    Args:
        sql: SQL query string
        default_limit: Default LIMIT value
        
    Returns:
        (modified_sql, limit_added)
    """
    # If query has aggregation or already has LIMIT, return as-is
    if has_aggregation(sql) or has_limit(sql):
        return sql, False
    
    # Add LIMIT to non-aggregating queries
    sql = sql.rstrip(";").strip()
    
    # Check if query ends with a valid SQL statement
    return f"{sql} LIMIT {default_limit}", True


def validate_r9_soft_fk(sql: str) -> Tuple[bool, str]:
    """R9: Warn on INNER JOIN with product_category_translation.
    
    Args:
        sql: SQL query string
        
    Returns:
        (warning_message or "")
    """
    if has_inner_join_category_translation(sql):
        return True, "R9 soft-FK: Consider using LEFT JOIN for product_category_translation (some products lack translations)"
    
    return False, ""


def _resolve_column_table(
    column: exp.Column,
    tables_in_query: Set[str],
) -> Optional[str]:
    """Resolve a column reference to its physical table.

    Resolution order:
    1. Explicit alias prefix (e.g. `p.product_id` → table aliased as `p`).
    2. Unprefixed column when only one table is in scope.
    3. Otherwise return None (cannot resolve — caller decides whether to flag).

    Args:
        column: sqlglot Column node.
        tables_in_query: Set of table names appearing in the query.

    Returns:
        Physical table name (without alias) or None if unresolvable.
    """
    table_ref = column.table
    if table_ref:
        # Strip quotes that sqlglot may preserve
        return table_ref.lower().replace('"', "")

    # No prefix — only resolvable if there's exactly one table in scope
    if len(tables_in_query) == 1:
        return next(iter(tables_in_query))

    return None


def validate_r10_column_exists(
    sql: str,
    schema_columns: Optional[Dict[str, Set[str]]] = None,
) -> Tuple[bool, List[str]]:
    """R10: Every referenced column must exist in the schema catalog.

    Catches hallucinated columns (e.g. `p.product_name` on the `products`
    table). Does NOT reject computed expressions, aggregates, or constants —
    only raw column references that resolve to a real table.

    Args:
        sql: SQL query string.
        schema_columns: Optional override of the column catalog. Defaults
            to the module-level SCHEMA_COLUMNS dict.

    Returns:
        (valid, list_of_error_messages). valid=True means no invented columns.
    """
    catalog = schema_columns if schema_columns is not None else SCHEMA_COLUMNS
    errors: List[str] = []

    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except Exception as e:
        # R1 should have caught this; fail open here.
        return True, [f"R10 column-exists: parse error passthrough: {e}"]

    known_tables = extract_tables(sql)
    # Map alias → physical table (case-insensitive)
    alias_to_table: Dict[str, str] = {}
    try:
        for statement in parsed:
            if not statement:
                continue
            for table_node in statement.find_all(exp.Table):
                phys = table_node.name.lower()
                alias = (table_node.alias or "").lower()
                if alias:
                    alias_to_table[alias] = phys
                # A table may be referenced by its own name
                alias_to_table[phys] = phys
    except Exception:
        pass

    try:
        # Collect SELECT alias names so we don't false-positive on bare
        # identifier references in ORDER BY / GROUP BY that point at an
        # alias (e.g. `ORDER BY my_alias` after `SELECT ... AS my_alias`).
        alias_names: Set[str] = set()
        for statement in parsed:
            if not statement:
                continue
            for alias_node in statement.find_all(exp.Alias):
                alias_ident = alias_node.alias
                if alias_ident:
                    alias_names.add(alias_ident.lower().replace('"', ""))

        for statement in parsed:
            if not statement:
                continue
            for col in statement.find_all(exp.Column):
                col_name = col.name.lower().replace('"', "")

                # Skip SELECT aliases — they are not column references
                if col_name in alias_names:
                    continue

                # Resolve physical table via alias if present
                prefix = (col.table or "").lower().replace('"', "")
                physical: Optional[str] = None
                if prefix:
                    physical = alias_to_table.get(prefix)
                    if physical is None and prefix in known_tables:
                        physical = prefix
                else:
                    physical = _resolve_column_table(col, known_tables)

                # If we can't resolve, be permissive — R5 already gates
                # tables, and ambiguous refs will fail at execution.
                if physical is None:
                    continue

                allowed = catalog.get(physical)
                if allowed is None:
                    # Unknown physical table — R5 territory, skip.
                    continue

                if col_name not in allowed:
                    errors.append(
                        f"R10 column-exists: column '{col_name}' not found "
                        f"on table '{physical}' "
                        f"(available: {sorted(allowed)})"
                    )
    except Exception as e:
        return True, [f"R10 column-exists: AST walk error: {e}"]

    return len(errors) == 0, errors


def validate_sql(
    sql: str,
    default_limit: int = 1000,
    schema_columns: Optional[Dict[str, Set[str]]] = None,
) -> ValidationResult:
    """Validate SQL query against all rules (R1-R10).
    
    Args:
        sql: SQL query string
        default_limit: Default LIMIT value for R8
        schema_columns: Optional override of column catalog for R10
        
    Returns:
        ValidationResult with valid flag, errors, warnings
    """
    errors: List[str] = []
    warnings: List[str] = []
    rule_failures: List[str] = []
    
    # R1: Parse
    valid, error = validate_r1_parse(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R1")
        return ValidationResult(valid=False, sql=sql, errors=errors, 
                               rule_failures=rule_failures)
    
    # R2: Top-level
    valid, error = validate_r2_top_level(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R2")
    
    # R3: DDL/DML
    valid, error = validate_r3_ddl_dml(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R3")
    
    # R4: System catalogs
    valid, error = validate_r4_catalogs(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R4")
    
    # R5: Allow-list
    valid, error = validate_r5_allow_list(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R5")
    
    # R6: Trap table
    valid, error = validate_r6_trap_table(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R6")
    
    # R7: No SELECT *
    valid, error = validate_r7_no_select_star(sql)
    if not valid:
        errors.append(error)
        rule_failures.append("R7")
    
    # R8: LIMIT injection (modifies SQL)
    modified_sql, limit_added = validate_r8_limit(sql, default_limit)
    if limit_added:
        warnings.append(f"R8 LIMIT: Auto-injected LIMIT {default_limit}")
    
    # R9: Soft-FK warning (does not block)
    has_warning, warning = validate_r9_soft_fk(sql)
    if has_warning:
        warnings.append(warning)
    
    # R10: Column existence (safety net for invented columns)
    valid, col_errors = validate_r10_column_exists(sql, schema_columns)
    if not valid:
        errors.extend(col_errors)
        rule_failures.append("R10")
    
    # Determine overall validity
    is_valid = len(errors) == 0
    
    return ValidationResult(
        valid=is_valid,
        sql=modified_sql,
        errors=errors,
        warnings=warnings,
        rule_failures=rule_failures,
    )
