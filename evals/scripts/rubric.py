#!/usr/bin/env python3
"""Pure sqlglot-based rubric grading for the eval suite.

Grades a predicted SQL string against a case's rubric spec across 6
dimensions: table, filters, aggregation, join, date_operator, time_frame.

Each dimension grader returns one of: "correct", "wrong", "flag", "NA".
  - "NA"      — rubric.<dim>.required is False (golden set had no value)
  - "correct" — every expected item for the dimension was found
  - "wrong"   — at least one expected item is missing/mismatched
  - "flag"    — partially matched / ambiguous, needs human verification
               (e.g. join keys match but join type differs)

This module intentionally does NOT import agent/validator/sql_validator.py
directly (to keep the eval suite decoupled from the agent package), but
mirrors its sqlglot walk patterns for table/column/join extraction.
"""
import re
from typing import Any, Dict, List, Set

import sqlglot
from sqlglot import exp

DIALECT = "postgres"

NA = "NA"
CORRECT = "correct"
WRONG = "wrong"
FLAG = "flag"


def _safe_parse(sql: str):
    try:
        parsed = sqlglot.parse_one(sql, dialect=DIALECT)
        return parsed
    except Exception:
        return None


def _normalize_ident(s: str) -> str:
    return s.strip().strip('"').strip("`").lower()


def extract_columns(sql: str) -> Set[str]:
    """Return a set of 'table.column' and bare 'column' strings referenced."""
    refs: Set[str] = set()
    tree = _safe_parse(sql)
    if tree is None:
        return refs
    for col in tree.find_all(exp.Column):
        name = _normalize_ident(col.name) if col.name else ""
        table = _normalize_ident(col.table) if col.table else ""
        if name:
            refs.add(name)
            if table:
                refs.add(f"{table}.{name}")
    return refs


def extract_tables(sql: str) -> Set[str]:
    tables: Set[str] = set()
    tree = _safe_parse(sql)
    if tree is None:
        return tables
    for t in tree.find_all(exp.Table):
        tables.add(_normalize_ident(t.name))
    return tables


def extract_aggregates(sql: str) -> Set[str]:
    """Return uppercase aggregate function names present (SUM, COUNT, ...)."""
    agg_types = (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max, exp.Stddev, exp.Variance)
    found: Set[str] = set()
    tree = _safe_parse(sql)
    if tree is None:
        return found
    for node in tree.walk():
        if isinstance(node, agg_types):
            found.add(type(node).__name__.upper())
    return found


def has_group_by(sql: str) -> bool:
    tree = _safe_parse(sql)
    return bool(tree and tree.find(exp.Group))


def has_order_by(sql: str) -> bool:
    tree = _safe_parse(sql)
    return bool(tree and tree.find(exp.Order))


def has_distinct(sql: str) -> bool:
    tree = _safe_parse(sql)
    if tree is None:
        return False
    for node in tree.walk():
        if isinstance(node, exp.Distinct):
            return True
    # sqlglot also represents COUNT(DISTINCT x) via exp.Count with a 'this'
    # that's wrapped differently depending on version; fall back to regex.
    return bool(re.search(r"\bDISTINCT\b", sql, re.IGNORECASE))


def extract_joins(sql: str) -> List[Dict[str, str]]:
    """Return a list of {type, right_table, on} dicts for each join."""
    joins: List[Dict[str, str]] = []
    tree = _safe_parse(sql)
    if tree is None:
        return joins
    for node in tree.find_all(exp.Join):
        side = (node.side or "").upper()
        kind = (node.kind or "").upper()
        join_type = side if side else (kind if kind else "INNER")
        right_table = ""
        table_node = node.this
        if isinstance(table_node, exp.Table):
            right_table = _normalize_ident(table_node.name)
        on_clause = ""
        if node.args.get("on") is not None:
            on_clause = node.args["on"].sql(dialect=DIALECT)
        joins.append({"type": join_type, "right": right_table, "on": on_clause})
    return joins


def extract_date_operators(sql: str) -> Set[str]:
    """Return the set of comparison operators used in date-like predicates."""
    ops: Set[str] = set()
    tree = _safe_parse(sql)
    if tree is None:
        return ops
    op_map = {
        exp.LT: "<",
        exp.LTE: "<=",
        exp.GT: ">",
        exp.GTE: ">=",
    }
    for node_type, symbol in op_map.items():
        if tree.find(node_type):
            ops.add(symbol)
    return ops


# ── Dimension graders ────────────────────────────────────────────────────


def grade_table(sql: str, rubric_block: Dict[str, Any]) -> str:
    if not rubric_block.get("required"):
        return NA
    expected_items = rubric_block.get("items") or []
    if not expected_items:
        return NA

    cols = extract_columns(sql)
    tables = extract_tables(sql)
    haystack = cols | tables

    missing = []
    for item in expected_items:
        item_norm = _normalize_ident(item)
        # Accept match on full "table.column", bare column, or bare table.
        bare_col = item_norm.split(".")[-1]
        if item_norm in haystack or bare_col in haystack:
            continue
        missing.append(item)

    if not missing:
        return CORRECT
    if len(missing) < len(expected_items):
        return FLAG
    return WRONG


def grade_filters(sql: str, rubric_block: Dict[str, Any]) -> str:
    if not rubric_block.get("required"):
        return NA
    expected_items = rubric_block.get("items") or []
    if not expected_items:
        return NA

    tree = _safe_parse(sql)
    where_sql = ""
    if tree is not None:
        where_node = tree.find(exp.Where)
        if where_node is not None:
            where_sql = where_node.sql(dialect=DIALECT)
    sql_norm = re.sub(r"\s+", " ", (where_sql or sql)).lower()

    missing = []
    for item in expected_items:
        # Extract the column/value tokens loosely and check substring
        # presence (best-effort — the golden set stores filters as
        # free-text like "order_status = 'delivered'").
        item_norm = re.sub(r"\s+", " ", item).lower()
        # Strip table prefixes for a looser match too.
        item_norm_no_prefix = re.sub(r"\b[a-z_]+\.", "", item_norm)
        if item_norm in sql_norm or item_norm_no_prefix in sql_norm:
            continue
        missing.append(item)

    if not missing:
        return CORRECT
    if len(missing) < len(expected_items):
        return FLAG
    return WRONG


def grade_aggregation(sql: str, rubric_block: Dict[str, Any]) -> str:
    if not rubric_block.get("required"):
        return NA
    expected_items = rubric_block.get("items") or []
    if not expected_items:
        return NA

    found_aggs = extract_aggregates(sql)
    group_by_present = has_group_by(sql)
    order_by_present = has_order_by(sql)
    distinct_present = has_distinct(sql)

    missing = []
    for item in expected_items:
        item_low = item.strip().lower()
        if item_low in ("count", "sum", "avg", "min", "max", "stddev", "variance"):
            if item_low.upper() not in found_aggs:
                missing.append(item)
        elif "distinct" in item_low:
            if not distinct_present:
                missing.append(item)
        elif item_low.startswith("group by"):
            if not group_by_present:
                missing.append(item)
        elif item_low.startswith("order by"):
            if not order_by_present:
                missing.append(item)
        elif item_low.startswith("limit"):
            m = re.search(r"limit\s+(\d+)", item_low)
            tree = _safe_parse(sql)
            limit_node = tree.find(exp.Limit) if tree is not None else None
            if limit_node is None:
                missing.append(item)
            elif m:
                expected_n = m.group(1)
                if expected_n not in limit_node.sql(dialect=DIALECT):
                    missing.append(item)
        else:
            # Free-text aggregate expression like "SUM(CASE...)" or
            # "ROUND(100.0 * ...)" — do a loose substring/function check.
            fn_match = re.match(r"([a-z_]+)\(", item_low)
            if fn_match:
                fn_name = fn_match.group(1).upper()
                if fn_name in ("SUM", "COUNT", "AVG", "MIN", "MAX") and fn_name not in found_aggs:
                    missing.append(item)
                # Otherwise treat as best-effort pass (can't fully verify
                # arbitrary expressions structurally).
            # else: unrecognized free text, skip (don't penalize)

    if not missing:
        return CORRECT
    if len(missing) < len(expected_items):
        return FLAG
    return WRONG


def grade_join(sql: str, rubric_block: Dict[str, Any]) -> str:
    if not rubric_block.get("required"):
        return NA
    expected_items = rubric_block.get("items") or []
    if not expected_items:
        return NA

    actual_joins = extract_joins(sql)
    actual_tables_joined = {j["right"] for j in actual_joins}
    # Also count the FROM-clause table names available for loose matching.
    all_tables = extract_tables(sql)

    missing = []
    flagged = False
    for item in expected_items:
        item_low = item.lower()
        # Find any table name mentioned in the item spec that we can look up.
        mentioned_tables = [t for t in all_tables if t in item_low]
        if not mentioned_tables:
            # Can't identify a table to check against; skip rather than
            # penalize on unparseable free text.
            continue

        target_table = mentioned_tables[-1]  # usually the "right" side
        if target_table not in actual_tables_joined and target_table not in all_tables:
            missing.append(item)
            continue

        # Check join type when the spec explicitly mentions LEFT/INNER/RIGHT.
        expected_type = None
        if "left join" in item_low:
            expected_type = "LEFT"
        elif "right join" in item_low:
            expected_type = "RIGHT"
        elif "inner join" in item_low or " join " in item_low:
            expected_type = "INNER"

        matching_actual = [j for j in actual_joins if j["right"] == target_table]
        if expected_type and matching_actual:
            actual_type = matching_actual[0]["type"] or "INNER"
            if actual_type != expected_type:
                flagged = True

    if missing:
        if len(missing) < len(expected_items):
            return FLAG
        return WRONG
    if flagged:
        return FLAG
    return CORRECT


def grade_date_operator(sql: str, rubric_block: Dict[str, Any]) -> str:
    if not rubric_block.get("required"):
        return NA
    expected_items = rubric_block.get("items") or []
    if not expected_items:
        return NA

    actual_ops = extract_date_operators(sql)
    expected_ops = set()
    for item in expected_items:
        m = re.search(r"(<=|>=|<|>)", item)
        if m:
            expected_ops.add(m.group(1))

    if not expected_ops:
        return NA

    missing = expected_ops - actual_ops
    if not missing:
        return CORRECT
    if len(missing) < len(expected_ops):
        return FLAG
    return WRONG


def grade_time_frame(sql: str, rubric_block: Dict[str, Any]) -> str:
    """Time dimension is reserved / currently unused — pass-through NA
    unless the golden set supplied a spec (free-text hints about date
    bucketing functions like STRFTIME/JULIANDAY), in which case we do a
    loose substring check as a best-effort signal.
    """
    if not rubric_block.get("required"):
        return NA
    spec = (rubric_block.get("spec") or "").lower()
    if not spec:
        return NA

    sql_low = sql.lower()
    hints = re.findall(r"[a-z_]+\(", spec)
    if not hints:
        return NA

    missing = [h for h in hints if h not in sql_low]
    if not missing:
        return CORRECT
    if len(missing) < len(hints):
        return FLAG
    return WRONG


DIMENSION_GRADERS = {
    "table": grade_table,
    "filters": grade_filters,
    "aggregation": grade_aggregation,
    "join": grade_join,
    "date_operator": grade_date_operator,
    "time_frame": grade_time_frame,
}


def grade_rubric(predicted_sql: str, rubric: Dict[str, Any]) -> Dict[str, str]:
    """Grade all 6 dimensions for a predicted SQL against a case's rubric.

    Returns a dict: {dimension_name: "correct"|"wrong"|"flag"|"NA"}
    """
    results: Dict[str, str] = {}
    for dim, grader in DIMENSION_GRADERS.items():
        block = rubric.get(dim, {"required": False})
        try:
            results[dim] = grader(predicted_sql, block)
        except Exception:
            # A grading crash should not take down the whole eval run;
            # surface it as "flag" so a human can inspect.
            results[dim] = FLAG
    return results


def has_any_wrong(rubric_results: Dict[str, str]) -> bool:
    return any(v == WRONG for v in rubric_results.values())


def has_any_flag(rubric_results: Dict[str, str]) -> bool:
    return any(v == FLAG for v in rubric_results.values())


def _self_test() -> None:
    """Quick manual smoke test — run with `python3 rubric.py --test`."""
    sample_rubric = {
        "table": {"required": True, "items": ["order_items.product_id", "products.product_id"]},
        "filters": {"required": True, "items": ["order_status = 'delivered'"]},
        "aggregation": {"required": True, "items": ["COUNT", "GROUP BY product_id"]},
        "join": {"required": True, "items": ["order_items JOIN products (order_items.product_id = products.product_id)"]},
        "date_operator": {"required": False},
        "time_frame": {"required": False},
    }
    good_sql = """
        SELECT i.product_id, COUNT(*) AS n
        FROM order_items i
        JOIN products p ON i.product_id = p.product_id
        JOIN orders o ON i.order_id = o.order_id
        WHERE o.order_status = 'delivered'
        GROUP BY i.product_id
    """
    bad_sql = """
        SELECT i.product_id
        FROM order_items i
    """
    print("good_sql grading:", grade_rubric(good_sql, sample_rubric))
    print("bad_sql grading:", grade_rubric(bad_sql, sample_rubric))


if __name__ == "__main__":
    import sys as _sys
    if "--test" in _sys.argv:
        _self_test()
    else:
        print("Usage: python3 rubric.py --test")
