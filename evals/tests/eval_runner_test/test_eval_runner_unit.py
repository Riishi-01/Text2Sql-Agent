"""Unit tests for eval_runner.py: normalize_sql, EM, EX, cost, summary."""
import json

import pytest

import eval_runner as er


class TestNormalizeSql:
    def test_lowercase(self):
        assert er.normalize_sql("SELECT A FROM T") == er.normalize_sql("select a from t")

    def test_collapses_whitespace(self):
        assert er.normalize_sql("SELECT  a,\n  b   FROM t") == er.normalize_sql("SELECT a, b FROM t")

    def test_strips_quotes(self):
        assert er.normalize_sql('SELECT "a" FROM t') == er.normalize_sql("SELECT a FROM t")

    def test_strips_trailing_semicolon(self):
        assert er.normalize_sql("SELECT a FROM t;") == er.normalize_sql("SELECT a FROM t")

    def test_normalizes_commas_and_parens(self):
        a = er.normalize_sql("SELECT COUNT( a ),b FROM t")
        b = er.normalize_sql("SELECT COUNT(a), b FROM t")
        assert a == b


class TestComputeEM:
    def test_identical_strings_em_and_raw_both_1(self):
        sql = "SELECT a FROM t"
        em, em_raw = er.compute_em(sql, sql)
        assert em == 1
        assert em_raw == 1

    def test_whitespace_only_diff_em_1_raw_0(self):
        gold = "SELECT a, b FROM t WHERE x = 1"
        pred = "  select  a,   b   from t where   x=1  "
        em, em_raw = er.compute_em(gold, pred)
        assert em == 1
        assert em_raw == 0

    def test_different_sql_em_0(self):
        gold = "SELECT a FROM t"
        pred = "SELECT b FROM t"
        em, em_raw = er.compute_em(gold, pred)
        assert em == 0
        assert em_raw == 0


class TestComputeEX:
    def test_identical_rows(self):
        rows = [{"a": 1, "b": "x"}]
        assert er.compute_ex(rows, rows) == 1

    def test_float_within_tolerance(self):
        gold = [{"revenue": 100.0}]
        pred = [{"revenue": 100.5}]  # 0.5% diff, within 1% tolerance
        assert er.compute_ex(gold, pred) == 1

    def test_float_outside_tolerance(self):
        gold = [{"revenue": 100.0}]
        pred = [{"revenue": 105.0}]  # 5% diff, outside 1% tolerance
        assert er.compute_ex(gold, pred) == 0

    def test_row_order_independent(self):
        gold = [{"a": 1}, {"a": 2}]
        pred = [{"a": 2}, {"a": 1}]
        assert er.compute_ex(gold, pred) == 1

    def test_different_row_counts(self):
        gold = [{"a": 1}, {"a": 2}]
        pred = [{"a": 1}]
        assert er.compute_ex(gold, pred) == 0

    def test_different_values(self):
        gold = [{"a": 1}]
        pred = [{"a": 2}]
        assert er.compute_ex(gold, pred) == 0

    def test_empty_vs_empty(self):
        assert er.compute_ex([], []) == 1

    def test_string_values_exact(self):
        gold = [{"city": "sao paulo"}]
        pred = [{"city": "sao paulo"}]
        assert er.compute_ex(gold, pred) == 1
        pred_diff = [{"city": "rio de janeiro"}]
        assert er.compute_ex(gold, pred_diff) == 0


class TestComputeEXRegressions:
    """Regression tests for two EX comparison bugs found during agent eval.

    Bug 1: PostgreSQL numeric columns return Decimal, which the old
           isinstance(a,(int,float)) check skipped — so float tolerance never
           applied and 4.0888 vs 4.0888019 falsely compared unequal.
    Bug 2: rows were sorted by JSON string INCLUDING column names, so gold and
           predicted result sets with different aliases (e.g. `AS n` vs `AS cnt`)
           sorted into different orders and got misaligned → false EX=0.
    """

    def test_decimal_within_tolerance(self):
        """Bug 1: Decimal values within tolerance should be equal."""
        from decimal import Decimal
        gold = [{"round": Decimal("4.0888")}]
        pred = [{"avg_review_score": Decimal("4.0888019510212377")}]
        assert er.compute_ex(gold, pred) == 1

    def test_decimal_outside_tolerance(self):
        """Bug 1: Decimal values outside tolerance should differ."""
        from decimal import Decimal
        gold = [{"avg": Decimal("4.00")}]
        pred = [{"avg": Decimal("4.50")}]  # 12.5% diff, outside 1% tolerance
        assert er.compute_ex(gold, pred) == 0

    def test_decimal_mixed_with_float(self):
        """Bug 1: Decimal vs float comparison should apply tolerance."""
        from decimal import Decimal
        gold = [{"x": Decimal("100.0")}]
        pred = [{"x": 100.5}]  # 0.5% diff, within tolerance
        assert er.compute_ex(gold, pred) == 1

    def test_different_column_names_same_values(self):
        """Bug 2: identical data with different aliases should be equal."""
        gold = [{"state": "MG", "n": 100}]
        pred = [{"state": "MG", "cnt": 100}]
        assert er.compute_ex(gold, pred) == 1

    def test_column_name_sort_divergence(self):
        """Bug 2: the specific misalignment case.

        Gold column 'z_cnt' sorts AFTER 'state'; pred column 'a_cnt' sorts
        BEFORE 'state'. With key-inclusive sorting the rows misalign. With
        value-based sorting they align correctly.
        """
        gold = [
            {"state": "MG", "z_cnt": 500},
            {"state": "SP", "z_cnt": 100},
            {"state": "RJ", "z_cnt": 200},
        ]
        pred = [
            {"state": "MG", "a_cnt": 500},
            {"state": "SP", "a_cnt": 100},
            {"state": "RJ", "a_cnt": 200},
        ]
        assert er.compute_ex(gold, pred) == 1

    def test_genuine_count_vs_count_distinct_still_fails(self):
        """Guard: a genuine semantic difference (COUNT vs COUNT DISTINCT)
        must still be caught as EX=0 even with different aliases."""
        gold = [{"state": "SP", "n": 41746}, {"state": "RJ", "n": 12852}]
        pred = [{"state": "SP", "cnt": 40302}, {"state": "RJ", "cnt": 12384}]
        assert er.compute_ex(gold, pred) == 0

    def test_none_values_handled(self):
        """Rows containing NULL/None should not raise and compare correctly."""
        gold = [{"a": None, "b": 1}]
        pred = [{"a": None, "b": 1}]
        assert er.compute_ex(gold, pred) == 1
        pred_diff = [{"a": None, "b": 2}]
        assert er.compute_ex(gold, pred_diff) == 0

    def test_multi_row_different_aliases_unsorted(self):
        """Multi-row set equality holds regardless of input order and alias."""
        gold = [{"city": "A", "total": 3}, {"city": "B", "total": 1}, {"city": "C", "total": 2}]
        pred = [{"city": "C", "amt": 2}, {"city": "A", "amt": 3}, {"city": "B", "amt": 1}]
        assert er.compute_ex(gold, pred) == 1


class TestComputeCost:
    def test_known_model_pricing(self):
        # gpt-4o-mini: 0.15 input, 0.60 output per 1M tokens
        cost = er.compute_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.15 + 0.60)

    def test_zero_tokens_zero_cost(self):
        assert er.compute_cost("gpt-4o", 0, 0) == 0.0

    def test_unknown_model_zero_cost(self):
        assert er.compute_cost("totally-unknown-model", 1000, 1000) == 0.0


class TestCombineTimeDims:
    def test_both_na(self):
        assert er._combine_time_dims("NA", "NA") == "NA"

    def test_one_na_one_correct(self):
        assert er._combine_time_dims("correct", "NA") == "correct"

    def test_wrong_beats_correct(self):
        assert er._combine_time_dims("correct", "wrong") == "wrong"

    def test_flag_beats_correct(self):
        assert er._combine_time_dims("correct", "flag") == "flag"

    def test_wrong_beats_flag(self):
        assert er._combine_time_dims("flag", "wrong") == "wrong"


class TestDiscoverCases:
    def test_finds_all_39(self):
        cases = er.discover_cases()
        assert len(cases) == 39

    def test_sorted_by_id(self):
        cases = er.discover_cases()
        ids = [c["id"] for c in cases]
        assert ids == sorted(ids)

    def test_difficulty_filter(self):
        hard_cases = er.discover_cases(difficulty_filter="hard")
        assert len(hard_cases) == 10
        assert all(c["difficulty"] == "hard" for c in hard_cases)

    def test_easy_filter(self):
        easy_cases = er.discover_cases(difficulty_filter="easy")
        assert len(easy_cases) == 16

    def test_medium_filter(self):
        medium_cases = er.discover_cases(difficulty_filter="medium")
        assert len(medium_cases) == 13

    def test_case_filter_exact(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        assert len(cases) == 1
        assert cases[0]["id"] == "e04_unique_customers"

    def test_case_filter_prefix(self):
        cases = er.discover_cases(case_filter="e01")
        assert len(cases) >= 1
        assert all(c["id"].startswith("e01") for c in cases)

    def test_no_match_returns_empty(self):
        cases = er.discover_cases(case_filter="zzz_does_not_exist")
        assert cases == []


class TestGetGoldSql:
    def test_gold_mode_returns_gold_sql(self):
        cases = er.discover_cases(case_filter="e04_unique_customers")
        case = cases[0]
        sql = er.get_gold_sql(case)
        assert sql.strip() == case["gold_sql"].strip()

    def test_empty_case_returns_empty_string(self):
        sql = er.get_gold_sql({})
        assert sql == ""

    def test_none_gold_sql_returns_empty_string(self):
        sql = er.get_gold_sql({"gold_sql": None})
        assert sql == ""


class TestRunIdNaming:
    def test_slugify_basic(self):
        assert er.slugify_run_name("baseline 4o-mini!") == "baseline_4o_mini"

    def test_slugify_collapses_and_strips(self):
        assert er.slugify_run_name("  Hello   World  ") == "hello_world"

    def test_slugify_empty(self):
        assert er.slugify_run_name("") == ""
        assert er.slugify_run_name("!!!") == ""

    def test_build_run_id_timestamp_only_when_no_name(self):
        rid = er.build_run_id(None, timestamp="20260101_000000")
        assert rid == "20260101_000000"

    def test_build_run_id_prefixes_slug(self):
        rid = er.build_run_id("baseline 4o-mini", timestamp="20260101_000000")
        assert rid == "baseline_4o_mini_20260101_000000"

    def test_build_run_id_blank_name_falls_back_to_ts(self):
        rid = er.build_run_id("!!!", timestamp="20260101_000000")
        assert rid == "20260101_000000"


class TestReviewOutcome:
    def _make_result(self, query_id, status, outcome, difficulty="easy", **overrides):
        base = {
            "query_id": query_id, "question": "q", "em": 0, "ex": 1,
            "latency_sec": 0.0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "status": status, "outcome": outcome,
            "table": "NA", "time_frame": "NA",
            "filters": "NA", "aggregation": "NA", "join": "NA",
            "difficulty": difficulty, "gold_sql": "SELECT 1", "predicted_sql": "SELECT 1",
            "error": "", "ground_truth_rows": "[]",
        }
        base.update(overrides)
        return base

    def test_review_counted_in_summary(self):
        results = [
            self._make_result("e01", "pass", "pass"),
            self._make_result("e02", "pass", "review"),
            self._make_result("e03", "fail", "fail", ex=0),
        ]
        summary = er.build_summary(results, "test_run", "agent(gpt-4o-mini)")
        assert summary["review"] == 1
        assert summary["passed"] == 2   # review is still a pass status
        assert summary["failed"] == 1
        assert summary["model"] == "agent(gpt-4o-mini)"   # mode label, not "gold"


class TestBuildSummary:
    def _make_result(self, query_id, status, em=1, ex=1, difficulty="easy", **overrides):
        base = {
            "query_id": query_id, "question": "q", "em": em, "ex": ex,
            "latency_sec": 0.0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "status": status, "table": "NA", "time_frame": "NA",
            "filters": "NA", "aggregation": "NA", "join": "NA",
            "difficulty": difficulty, "gold_sql": "SELECT 1", "predicted_sql": "SELECT 1",
            "error": "", "ground_truth_rows": "[]",
        }
        base.update(overrides)
        return base

    def test_all_pass_summary(self):
        results = [self._make_result(f"e{i:02d}", "pass") for i in range(5)]
        summary = er.build_summary(results, "test_run", None)
        assert summary["total"] == 5
        assert summary["passed"] == 5
        assert summary["pass_rate"] == 1.0
        assert summary["failures"] == []

    def test_mixed_results_failures_list(self):
        results = [
            self._make_result("e01", "pass"),
            self._make_result("e02", "fail", em=0, ex=1, table="wrong"),
            self._make_result("e03", "error", error="boom"),
        ]
        summary = er.build_summary(results, "test_run", None)
        assert summary["total"] == 3
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["errors"] == 1
        assert len(summary["failures"]) == 2
        fail_ids = {f["query_id"] for f in summary["failures"]}
        assert fail_ids == {"e02", "e03"}

    def test_false_positive_rate(self):
        # ex=1 but a rubric dim is wrong -> false positive
        results = [self._make_result("e01", "fail", em=0, ex=1, table="wrong")]
        summary = er.build_summary(results, "test_run", None)
        assert summary["metrics"]["false_positive_rate"] == 1.0

    def test_by_difficulty_breakdown(self):
        results = [
            self._make_result("e01", "pass", difficulty="easy"),
            self._make_result("h01", "fail", em=0, difficulty="hard"),
        ]
        summary = er.build_summary(results, "test_run", None)
        assert summary["by_difficulty"]["easy"]["n"] == 1
        assert summary["by_difficulty"]["hard"]["n"] == 1
        assert summary["by_difficulty"]["medium"]["n"] == 0

    def test_summary_is_json_serializable(self):
        results = [self._make_result("e01", "pass")]
        summary = er.build_summary(results, "test_run", "gpt-4o-mini")
        json.dumps(summary)  # should not raise


class TestPercentile:
    def test_p50_median(self):
        assert er._percentile([1, 2, 3, 4, 5], 50) == 3

    def test_p95_of_single_value(self):
        assert er._percentile([42.0], 95) == 42.0

    def test_empty_list(self):
        assert er._percentile([], 95) == 0.0
