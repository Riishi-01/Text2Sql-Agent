"""Unit tests for rubric.py grading functions."""
import rubric


class TestExtractHelpers:
    def test_extract_tables(self):
        sql = "SELECT a FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
        tables = rubric.extract_tables(sql)
        assert "orders" in tables
        assert "customers" in tables

    def test_extract_columns(self):
        sql = "SELECT o.order_id, c.customer_state FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
        cols = rubric.extract_columns(sql)
        assert "order_id" in cols
        assert "o.order_id" in cols
        assert "customer_state" in cols

    def test_extract_aggregates(self):
        sql = "SELECT COUNT(*), SUM(price), AVG(score) FROM t"
        aggs = rubric.extract_aggregates(sql)
        assert aggs == {"COUNT", "SUM", "AVG"}

    def test_has_group_by_true(self):
        assert rubric.has_group_by("SELECT a, COUNT(*) FROM t GROUP BY a") is True

    def test_has_group_by_false(self):
        assert rubric.has_group_by("SELECT a FROM t") is False

    def test_has_distinct_true(self):
        assert rubric.has_distinct("SELECT COUNT(DISTINCT x) FROM t") is True

    def test_has_distinct_false(self):
        assert rubric.has_distinct("SELECT COUNT(x) FROM t") is False

    def test_extract_date_operators(self):
        sql = "SELECT * FROM t WHERE a <= b AND c > d"
        ops = rubric.extract_date_operators(sql)
        assert "<=" in ops
        assert ">" in ops
        assert "<" not in ops


class TestGradeTable:
    def test_na_when_not_required(self):
        result = rubric.grade_table("SELECT 1", {"required": False})
        assert result == rubric.NA

    def test_correct_when_all_columns_present(self):
        sql = "SELECT o.order_id, c.customer_state FROM orders o JOIN customers c ON o.customer_id=c.customer_id"
        block = {"required": True, "items": ["orders.order_id", "customers.customer_state"]}
        assert rubric.grade_table(sql, block) == rubric.CORRECT

    def test_wrong_when_all_missing(self):
        sql = "SELECT x FROM other_table"
        block = {"required": True, "items": ["orders.order_id", "customers.customer_state"]}
        assert rubric.grade_table(sql, block) == rubric.WRONG

    def test_flag_when_partially_missing(self):
        sql = "SELECT o.order_id FROM orders o"
        block = {"required": True, "items": ["orders.order_id", "customers.customer_state"]}
        assert rubric.grade_table(sql, block) == rubric.FLAG


class TestGradeFilters:
    def test_na_when_not_required(self):
        assert rubric.grade_filters("SELECT 1", {"required": False}) == rubric.NA

    def test_correct_when_filter_present(self):
        sql = "SELECT * FROM orders WHERE order_status = 'delivered'"
        block = {"required": True, "items": ["order_status = 'delivered'"]}
        assert rubric.grade_filters(sql, block) == rubric.CORRECT

    def test_wrong_when_filter_absent(self):
        sql = "SELECT * FROM orders"
        block = {"required": True, "items": ["order_status = 'delivered'"]}
        assert rubric.grade_filters(sql, block) == rubric.WRONG


class TestGradeAggregation:
    def test_na_when_not_required(self):
        assert rubric.grade_aggregation("SELECT 1", {"required": False}) == rubric.NA

    def test_correct_when_count_present(self):
        sql = "SELECT COUNT(*) FROM orders"
        block = {"required": True, "items": ["COUNT"]}
        assert rubric.grade_aggregation(sql, block) == rubric.CORRECT

    def test_wrong_when_agg_missing(self):
        sql = "SELECT * FROM orders"
        block = {"required": True, "items": ["COUNT"]}
        assert rubric.grade_aggregation(sql, block) == rubric.WRONG

    def test_distinct_required(self):
        sql = "SELECT COUNT(DISTINCT customer_unique_id) FROM customers"
        block = {"required": True, "items": ["COUNT", "DISTINCT required"]}
        assert rubric.grade_aggregation(sql, block) == rubric.CORRECT

    def test_distinct_missing_flagged_wrong_or_flag(self):
        sql = "SELECT COUNT(customer_unique_id) FROM customers"
        block = {"required": True, "items": ["COUNT", "DISTINCT required"]}
        result = rubric.grade_aggregation(sql, block)
        assert result in (rubric.WRONG, rubric.FLAG)


class TestGradeDateOperator:
    def test_na_when_not_required(self):
        assert rubric.grade_date_operator("SELECT 1", {"required": False}) == rubric.NA

    def test_correct_when_operator_present(self):
        sql = "SELECT * FROM orders WHERE delivered_date <= estimated_date"
        block = {"required": True, "items": ["date comparison operator: <= (on time)"]}
        assert rubric.grade_date_operator(sql, block) == rubric.CORRECT

    def test_wrong_when_operator_absent(self):
        sql = "SELECT * FROM orders WHERE delivered_date = estimated_date"
        block = {"required": True, "items": ["date comparison operator: <= (on time)"]}
        assert rubric.grade_date_operator(sql, block) == rubric.WRONG


class TestGradeRubricAndHasAnyWrong:
    def test_grade_rubric_returns_all_six_dims(self):
        rubric_spec = {
            "table": {"required": False},
            "filters": {"required": False},
            "aggregation": {"required": False},
            "join": {"required": False},
            "date_operator": {"required": False},
            "time_frame": {"required": False},
        }
        result = rubric.grade_rubric("SELECT 1", rubric_spec)
        assert set(result.keys()) == {"table", "filters", "aggregation", "join", "date_operator", "time_frame"}
        assert all(v == rubric.NA for v in result.values())

    def test_has_any_wrong_true(self):
        assert rubric.has_any_wrong({"table": "correct", "filters": "wrong"}) is True

    def test_has_any_wrong_false(self):
        assert rubric.has_any_wrong({"table": "correct", "filters": "NA", "join": "flag"}) is False

    def test_grading_crash_does_not_propagate(self):
        """A malformed rubric block should not raise — grade_rubric catches
        per-dimension exceptions and reports 'flag' instead."""
        bad_spec = {"table": {"required": True, "items": None}}  # items=None could break iteration
        result = rubric.grade_rubric("SELECT 1", bad_spec)
        assert result["table"] in (rubric.NA, rubric.WRONG, rubric.FLAG, rubric.CORRECT)
