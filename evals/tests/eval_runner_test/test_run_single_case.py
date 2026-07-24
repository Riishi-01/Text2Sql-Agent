"""Tests for run_single_case() using a mocked PostgreSQL connection.

These tests patch eval_runner.connection_scope and eval_runner.execute_query
so no live database is required. They exercise the full per-case flow:
predicted SQL retrieval, gold+predicted execution, EM/EX scoring, rubric
grading, and status derivation — including the retry-on-transient-error
and error/timeout paths.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import eval_runner as er
from db_loader import TransientDBError


def _fake_connection_scope_factory(query_results, raise_on_calls=None):
    """Build a fake connection_scope + execute_query pair.

    query_results: dict mapping sql string (exact match) -> rows list.
        Falls back to [] for unmatched SQL.
    raise_on_calls: optional list of exceptions to raise on successive
        execute_query calls (for retry testing); once exhausted, falls
        back to normal behavior.
    """
    call_counter = {"n": 0}

    @contextmanager
    def fake_connection_scope(timeout_ms=15000):
        yield object()  # dummy "connection"

    def fake_execute_query(conn, sql, row_limit=10000):
        call_counter["n"] += 1
        if raise_on_calls and call_counter["n"] <= len(raise_on_calls):
            exc = raise_on_calls[call_counter["n"] - 1]
            if exc is not None:
                raise exc
        rows = query_results.get(sql.strip(), [])
        return rows, []

    return fake_connection_scope, fake_execute_query, call_counter


class TestRunSingleCaseGoldMode:
    def test_pass_when_gold_equals_predicted(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()
        gold_rows = [{"count": 96096}]

        fake_scope, fake_exec, _ = _fake_connection_scope_factory({gold_sql: gold_rows})

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec):
            result = er.run_single_case(case, model=None, inject_failure=None)

        assert result["status"] == "pass"
        assert result["em"] == 1
        assert result["ex"] == 1
        assert result["query_id"] == "e04_unique_customers"
        assert result["error"] == ""

    def test_rubric_dims_present_in_result(self):
        cases = er.discover_cases(case_filter="e01_5_selling_products_health_beauty")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()
        gold_rows = [{"product_id": "abc", "n_sold": 281}]

        fake_scope, fake_exec, _ = _fake_connection_scope_factory({gold_sql: gold_rows})

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec):
            result = er.run_single_case(case, model=None, inject_failure=None)

        for dim in ("table", "time_frame", "filters", "aggregation", "join"):
            assert dim in result
            assert result[dim] in ("correct", "wrong", "flag", "NA")

    def test_ground_truth_rows_recorded_as_json(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()
        gold_rows = [{"count": 96096}]

        fake_scope, fake_exec, _ = _fake_connection_scope_factory({gold_sql: gold_rows})

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec):
            result = er.run_single_case(case, model=None, inject_failure=None)

        import json
        parsed = json.loads(result["ground_truth_rows"])
        assert parsed == gold_rows


class TestRunSingleCaseFailureModes:
    def test_unknown_inject_failure_mode_yields_error_status(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()
        fake_scope, fake_exec, _ = _fake_connection_scope_factory({gold_sql: [{"count": 1}]})

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec):
            result = er.run_single_case(case, model=None, inject_failure="not_a_real_mode")

        assert result["status"] == "error"
        assert "ValueError" in result["error"] or "TypeError" in result["error"]

    def test_mismatched_predicted_sql_yields_fail(self):
        """Simulate a predicted SQL that returns different rows than gold."""
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()

        # Use a different SQL that returns different rows
        different_sql = "SELECT COUNT(*) FROM customers"  # deliberately different
        query_results = {
            gold_sql: [{"count": 96096}],
            different_sql: [{"count": 1}],
        }
        fake_scope, fake_exec, _ = _fake_connection_scope_factory(query_results)

        # Patch get_gold_sql to return the different SQL
        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec), \
             patch.object(er, "get_gold_sql", lambda c: different_sql):
            result = er.run_single_case(case, model=None, inject_failure=None)

        assert result["status"] == "fail"
        assert result["ex"] == 0


class TestRunSingleCaseRetry:
    def test_transient_error_retries_then_succeeds(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()

        # First call (gold execute) raises transient error once, then succeeds.
        raise_on_calls = [TransientDBError("timeout"), None, None]
        fake_scope, fake_exec, counter = _fake_connection_scope_factory(
            {gold_sql: [{"count": 96096}]}, raise_on_calls=raise_on_calls,
        )

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec), \
             patch.object(er.time, "sleep", lambda s: None):  # skip real backoff delay
            result = er.run_single_case(case, model=None, inject_failure=None)

        assert result["status"] == "pass"
        assert counter["n"] >= 2  # at least one retry happened

    def test_transient_error_exhausts_retries_yields_timeout(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        gold_sql = case["gold_sql"].strip()

        # Always raise transient error -> exhausts MAX_RETRIES -> status=timeout
        raise_on_calls = [TransientDBError("timeout")] * 10
        fake_scope, fake_exec, _ = _fake_connection_scope_factory(
            {gold_sql: [{"count": 96096}]}, raise_on_calls=raise_on_calls,
        )

        with patch.object(er, "connection_scope", fake_scope), \
             patch.object(er, "execute_query", fake_exec), \
             patch.object(er.time, "sleep", lambda s: None):
            result = er.run_single_case(case, model=None, inject_failure=None)

        assert result["status"] == "timeout"
        assert result["error"]

    def test_non_transient_error_no_retry_yields_error(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]

        @contextmanager
        def raising_scope(timeout_ms=15000):
            yield object()

        def raising_exec(conn, sql, row_limit=10000):
            raise ValueError("SQL syntax error near FROM")

        with patch.object(er, "connection_scope", raising_scope), \
             patch.object(er, "execute_query", raising_exec):
            result = er.run_single_case(case, model=None, inject_failure=None)

        assert result["status"] == "error"
        assert "ValueError" in result["error"]
