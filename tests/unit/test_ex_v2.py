"""Tests for the v2 EX comparator in evals/scripts/eval_runner.py.

Covers:
- _rows_equal returns (bool, reason) tuple
- Reason describes row count, col count, value mismatches
- Trailing extra columns are tolerated (generic relaxation)
- Backward-compatible boolean usage via compute_ex (returns 0/1 int)
"""
from decimal import Decimal

from evals.scripts.eval_runner import _rows_equal, compute_ex


class TestRowsEqualReturnType:
    def test_returns_tuple_of_bool_and_str(self):
        rows = [{"a": 1}]
        result = _rows_equal(rows, rows)
        assert isinstance(result, tuple)
        assert len(result) == 2
        equal, reason = result
        assert isinstance(equal, bool)
        assert isinstance(reason, str)

    def test_equal_rows_have_empty_or_passing_reason(self):
        rows = [{"a": 1, "b": "x"}]
        equal, reason = _rows_equal(rows, rows)
        assert equal is True
        assert "rows equal" in reason.lower() or "empty" in reason.lower()


class TestRowsEqualRowCount:
    def test_row_count_mismatch_returns_specific_reason(self):
        gold = [{"a": 1}, {"a": 2}]
        pred = [{"a": 1}]
        equal, reason = _rows_equal(gold, pred, label="test")
        assert equal is False
        assert "row count" in reason.lower()
        assert "test" in reason

    def test_empty_vs_empty_is_equal(self):
        equal, reason = _rows_equal([], [], label="empty")
        assert equal is True


class TestRowsEqualColumnCount:
    def test_extra_trailing_col_in_predicted_is_rejected(self):
        """Gold has 2 cols, pred has 3 cols. Fail (verbose-question
        philosophy: column count must match the question's spec)."""
        gold = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
        pred = [{"x": 1, "y": "a", "z": 100}, {"x": 2, "y": "b", "z": 200}]
        equal, reason = _rows_equal(gold, pred, label="t")
        assert equal is False
        assert "col count" in reason.lower() or "trim" in reason.lower()

    def test_extra_trailing_col_in_gold_is_rejected(self):
        """Gold has 3 cols, pred has 2 cols (truncated). Fail."""
        gold = [{"x": 1, "y": "a", "z": 100}, {"x": 2, "y": "b", "z": 200}]
        pred = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
        equal, reason = _rows_equal(gold, pred, label="t")
        assert equal is False
        assert "col count" in reason.lower() or "trim" in reason.lower()

    def test_matching_col_count_passes(self):
        """Same column count on both sides → pass."""
        gold = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
        pred = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
        equal, reason = _rows_equal(gold, pred, label="t")
        assert equal is True

    def test_value_mismatch_reason_includes_position(self):
        gold = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        pred = [{"a": 1, "b": "x"}, {"a": 99, "b": "y"}]
        equal, reason = _rows_equal(gold, pred, label="t")
        assert equal is False
        assert "row 1" in reason or "row 0" in reason
        assert "col 0" in reason

    def test_explicit_trim_to_gold_cols_true_still_tolerates(self):
        """When caller explicitly opts in to trim, extra cols are tolerated.
        (Used by tests / non-default paths; default callsites pass False.)"""
        gold = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
        pred = [{"x": 1, "y": "a", "z": 100}, {"x": 2, "y": "b", "z": 200}]
        equal, reason = _rows_equal(gold, pred, label="t", trim_to_gold_cols=True)
        assert equal is True


class TestRowsEqualValues:
    def test_decimal_within_tolerance(self):
        gold = [{"x": Decimal("4.0888")}]
        pred = [{"x": Decimal("4.0888019")}]
        equal, _ = _rows_equal(gold, pred)
        assert equal is True

    def test_decimal_outside_tolerance(self):
        gold = [{"x": Decimal("4.00")}]
        pred = [{"x": Decimal("4.50")}]
        equal, _ = _rows_equal(gold, pred)
        assert equal is False

    def test_row_order_independent(self):
        gold = [{"a": 1}, {"a": 2}]
        pred = [{"a": 2}, {"a": 1}]
        equal, _ = _rows_equal(gold, pred)
        assert equal is True

    def test_column_names_dont_affect_comparison(self):
        """Bug-2 regression: alias differences shouldn't break EX."""
        gold = [{"state": "MG", "n": 100}]
        pred = [{"state": "MG", "cnt": 100}]
        equal, _ = _rows_equal(gold, pred)
        assert equal is True


class TestComputeExBackwardCompat:
    """Existing callers of compute_ex(rows, rows) expect int return."""

    def test_compute_ex_returns_int(self):
        rows = [{"a": 1}]
        result = compute_ex(rows, rows)
        assert isinstance(result, int)
        assert result in (0, 1)

    def test_compute_ex_identical_returns_1(self):
        rows = [{"a": 1, "b": "x"}]
        assert compute_ex(rows, rows) == 1

    def test_compute_ex_different_returns_0(self):
        gold = [{"a": 1}]
        pred = [{"a": 2}]
        assert compute_ex(gold, pred) == 0

    def test_compute_ex_with_log_path_creates_file(self, tmp_path):
        rows = [{"a": 1}]
        log = tmp_path / "ex.log"
        compute_ex(rows, rows, label="t", log_path=log)
        assert log.exists()
        content = log.read_text()
        assert "t" in content
        assert "rows equal" in content.lower()
