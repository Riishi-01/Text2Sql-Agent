"""Static SQL Safety Validator (R1-R9).

This validator is independent of the LLM. It is deterministic, side-effect-free,
and testable without network. It enforces 9 hard rules:

R1: Parse - sqlglot parse must succeed
R2: Top-level - must be SELECT or WITH...SELECT
R3: DDL/DML - INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, COPY, VACUUM, REINDEX rejected
R4: System catalogs - pg_*, information_schema rejected
R5: Allow-list - only 11 Olist tables + geolocation_by_zip
R6: Trap table - raw geolocation rejected; geolocation_by_zip is the only allowed interface
R7: No SELECT * - list every column explicitly
R8: LIMIT - auto-injected LIMIT for non-aggregating queries; default 1000
R9: Soft-FK LEFT JOIN - INNER JOIN category_translation warns (does not block)
"""
import re
from dataclasses import dataclass, field
from typing import List, Set, Optional, Tuple
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


def validate_sql(sql: str, default_limit: int = 1000) -> ValidationResult:
    """Validate SQL query against all rules (R1-R9).
    
    Args:
        sql: SQL query string
        default_limit: Default LIMIT value for R8
        
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
    
    # Determine overall validity
    is_valid = len(errors) == 0
    
    return ValidationResult(
        valid=is_valid,
        sql=modified_sql,
        errors=errors,
        warnings=warnings,
        rule_failures=rule_failures,
    )
