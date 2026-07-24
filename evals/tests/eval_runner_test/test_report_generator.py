"""Unit tests for report_generator.py.

Tests use in-memory fixture data — no DB, no filesystem beyond tmp_path.
All assertions are structural (section headers, key content, formatting
invariants) rather than pixel-perfect string matching.
"""
import json
from pathlib import Path

import pytest
import report_generator as rg

# ── Fixtures ─────────────────────────────────────────────────────────────


def _summary(
    *,
    run_id: str = "20260101_120000",
    model: str = "gold",
    total: int = 4,
    passed: int = 2,
    failed: int = 1,
    errors: int = 1,
    timeouts: int = 0,
    pass_rate: float = 0.5,
    em_rate: float = 0.5,
    ex_rate: float = 0.5,
    rubric_clean_rate: float = 0.75,
    false_positive_rate: float = 0.25,
    cost: float = 0.0,
    by_difficulty=None,
    by_dim_fail_rate=None,
    failures=None,
) -> dict:
    return {
        "run_id": run_id,
        "model": model,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "timeouts": timeouts,
        "pass_rate": pass_rate,
        "metrics": {
            "em_rate": em_rate,
            "ex_rate": ex_rate,
            "rubric_clean_rate": rubric_clean_rate,
            "false_positive_rate": false_positive_rate,
            "avg_latency_sec": 0.0,
            "p50_latency_sec": 0.0,
            "p95_latency_sec": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": cost,
        },
        "by_difficulty": by_difficulty or {
            "easy": {"n": 2, "em": 1.0, "ex": 1.0, "pass_rate": 1.0},
            "medium": {"n": 1, "em": 0.0, "ex": 0.0, "pass_rate": 0.0},
            "hard": {"n": 1, "em": 0.0, "ex": 0.0, "pass_rate": 0.0},
        },
        "by_dim_fail_rate": by_dim_fail_rate or {
            "table":       {"graded": 3, "pass": 3, "flag": 0, "wrong": 0},
            "time_frame":  {"graded": 1, "pass": 0, "flag": 0, "wrong": 1},
            "filters":     {"graded": 2, "pass": 0, "flag": 2, "wrong": 0},
            "aggregation": {"graded": 3, "pass": 3, "flag": 0, "wrong": 0},
            "join":        {"graded": 2, "pass": 1, "flag": 1, "wrong": 0},
        },
        "failures": failures if failures is not None else [
            {
                "query_id": "h01_some_hard_query",
                "difficulty": "hard",
                "trap": None,
                "em": False,
                "ex": False,
                "rubric_wrong_dims": [],
                "error": "SyntaxError: subquery in FROM must have an alias\nLINE 2: FROM (",
                "predicted_sql_excerpt": "SELECT AVG(x) FROM (",
            },
            {
                "query_id": "m01_rubric_only_failure",
                "difficulty": "medium",
                "trap": None,
                "em": True,
                "ex": True,
                "rubric_wrong_dims": ["time_frame"],
                "error": None,
                "predicted_sql_excerpt": "SELECT TO_CHAR(ts, 'YYYY-MM') FROM orders",
            },
        ],
    }


def _per_query() -> list:
    return [
        {
            "query_id": "e01_easy_one",
            "question": "how many orders?",
            "em": 1, "ex": 1,
            "latency_sec": 0.05, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "status": "pass",
            "table": "correct", "time_frame": "NA", "filters": "NA",
            "aggregation": "correct", "join": "NA",
            "difficulty": "easy",
            "gold_sql": "SELECT COUNT(*) FROM orders",
            "predicted_sql": "SELECT COUNT(*) FROM orders",
            "error": "", "ground_truth_rows": "[{\"count\": 99441}]",
        },
        {
            "query_id": "e02_easy_two",
            "question": "top cities",
            "em": 1, "ex": 1,
            "latency_sec": 0.03, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "status": "pass",
            "table": "correct", "time_frame": "NA", "filters": "NA",
            "aggregation": "correct", "join": "NA",
            "difficulty": "easy",
            "gold_sql": "SELECT city, COUNT(*) FROM customers GROUP BY city LIMIT 10",
            "predicted_sql": "SELECT city, COUNT(*) FROM customers GROUP BY city LIMIT 10",
            "error": "", "ground_truth_rows": "[]",
        },
        {
            "query_id": "h01_some_hard_query",
            "question": "average total spend per unique customer",
            "em": 0, "ex": 0,
            "latency_sec": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "status": "error",
            "table": "correct", "time_frame": "NA", "filters": "NA",
            "aggregation": "correct", "join": "NA",
            "difficulty": "hard",
            "gold_sql": "SELECT ROUND(AVG(t), 2) FROM (SELECT SUM(price) AS t FROM order_items GROUP BY order_id) AS sub",
            "predicted_sql": "SELECT ROUND(AVG(t), 2) FROM (SELECT SUM(price) AS t FROM order_items GROUP BY order_id)",
            "error": "SyntaxError: subquery in FROM must have an alias\nLINE 2: FROM (", "ground_truth_rows": "[]",
        },
        {
            "query_id": "m01_rubric_only_failure",
            "question": "monthly order count trend",
            "em": 1, "ex": 1,
            "latency_sec": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "status": "fail",
            "table": "correct", "time_frame": "wrong", "filters": "NA",
            "aggregation": "correct", "join": "NA",
            "difficulty": "medium",
            "gold_sql": "SELECT TO_CHAR(ts, 'YYYY-MM') AS ym, COUNT(*) FROM orders GROUP BY ym",
            "predicted_sql": "SELECT TO_CHAR(ts, 'YYYY-MM') AS ym, COUNT(*) FROM orders GROUP BY ym",
            "error": "", "ground_truth_rows": "[]",
        },
    ]


def _generate(tmp_path: Path, *, summary=None, per_query=None, **kwargs) -> str:
    """Helper: generate report and return its text content."""
    s = summary if summary is not None else _summary()
    pq = per_query if per_query is not None else _per_query()
    out = tmp_path / "report.md"
    rg.generate_report(s, pq, out, **kwargs)
    return out.read_text(encoding="utf-8")


# ── File-level assertions ─────────────────────────────────────────────────


class TestFileCreation:
    def test_file_is_created(self, tmp_path):
        out = tmp_path / "report.md"
        rg.generate_report(_summary(), _per_query(), out)
        assert out.exists()

    def test_file_is_utf8_readable(self, tmp_path):
        content = _generate(tmp_path)
        # If not UTF-8 this would raise; just assert non-empty
        assert len(content) > 0

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "nested" / "deep" / "report.md"
        rg.generate_report(_summary(), _per_query(), out)
        assert out.exists()


# ── Section header presence ───────────────────────────────────────────────


class TestSectionHeaders:
    REQUIRED_HEADERS = [
        "# Eval Report",
        "## Top-Line Metrics",
        "## Rubric Dimension Health",
        "## By-Difficulty Breakdown",
        "## Failures",
    ]

    def test_all_five_section_headers_present(self, tmp_path):
        content = _generate(tmp_path)
        for header in self.REQUIRED_HEADERS:
            assert header in content, f"Missing section: {header!r}"

    def test_run_id_in_header(self, tmp_path):
        s = _summary(run_id="20991231_235959")
        content = _generate(tmp_path, summary=s)
        assert "20991231_235959" in content

    def test_model_name_in_header(self, tmp_path):
        s = _summary(model="gpt-4o-mini")
        content = _generate(tmp_path, summary=s)
        assert "gpt-4o-mini" in content


# ── Formatting invariants ─────────────────────────────────────────────────


class TestFormatting:
    def test_no_trailing_whitespace_per_line(self, tmp_path):
        content = _generate(tmp_path)
        for i, line in enumerate(content.splitlines(), 1):
            assert line == line.rstrip(), f"Trailing whitespace on line {i}: {line!r}"

    def test_ends_with_newline(self, tmp_path):
        out = tmp_path / "report.md"
        rg.generate_report(_summary(), _per_query(), out)
        raw = out.read_bytes()
        assert raw.endswith(b"\n")

    def test_wall_time_rendered_when_provided(self, tmp_path):
        content = _generate(tmp_path, wall_time_sec=42.75)
        assert "42.75" in content

    def test_wall_time_na_when_none(self, tmp_path):
        content = _generate(tmp_path, wall_time_sec=None)
        assert "N/A" in content

    def test_workers_rendered_when_provided(self, tmp_path):
        content = _generate(tmp_path, parallel_workers=8)
        assert "8" in content


# ── Top-line metrics ──────────────────────────────────────────────────────


class TestToplineMetrics:
    def test_em_rate_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "EM rate" in content

    def test_ex_rate_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "EX rate" in content

    def test_rubric_clean_rate_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "Rubric-clean rate" in content

    def test_false_positive_rate_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "False positive rate" in content

    def test_pass_fail_counts_present(self, tmp_path):
        s = _summary(passed=31, failed=2, errors=6, timeouts=0)
        content = _generate(tmp_path, summary=s)
        assert "31" in content
        assert "2" in content
        assert "6" in content


# ── Rubric dimension table ordering ──────────────────────────────────────


class TestRubricTable:
    def test_worst_dimension_appears_before_healthy(self, tmp_path):
        # time_frame has 100% wrong → should appear before table (100% correct)
        content = _generate(tmp_path)
        time_frame_pos = content.index("time_frame")
        table_pos = content.index("| table")
        assert time_frame_pos < table_pos, (
            "time_frame (worst dim) should appear before table (healthy dim) in report"
        )

    def test_all_five_dims_present(self, tmp_path):
        content = _generate(tmp_path)
        for dim in rg.RUBRIC_DIMS:
            assert dim in content, f"Rubric dimension {dim!r} missing from report"


# ── By-difficulty table ───────────────────────────────────────────────────


class TestDifficultyTable:
    def test_easy_medium_hard_rows_present(self, tmp_path):
        content = _generate(tmp_path)
        for diff in ("easy", "medium", "hard"):
            assert diff in content

    def test_zero_n_difficulty_omitted(self, tmp_path):
        # hard n=0 → should not appear in table
        s = _summary(by_difficulty={
            "easy":   {"n": 3, "em": 1.0, "ex": 1.0, "pass_rate": 1.0},
            "medium": {"n": 1, "em": 0.5, "ex": 0.5, "pass_rate": 0.5},
            "hard":   {"n": 0, "em": 0.0, "ex": 0.0, "pass_rate": 0.0},
        })
        content = _generate(tmp_path, summary=s)
        # "hard" only appears if there's a row for it in the table.
        # The section header "## By-Difficulty" is fine, but "| hard" row should not exist.
        assert "| hard" not in content


# ── Failures section ──────────────────────────────────────────────────────


class TestFailuresSection:
    def test_all_pass_run_shows_no_failures_message(self, tmp_path):
        s = _summary(passed=4, failed=0, errors=0, failures=[])
        content = _generate(tmp_path, summary=s)
        assert "No failures in this run" in content

    def test_failure_query_id_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "h01_some_hard_query" in content

    def test_failure_question_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "average total spend per unique customer" in content

    def test_error_excerpt_rendered(self, tmp_path):
        content = _generate(tmp_path)
        assert "subquery in FROM must have an alias" in content

    def test_gold_sql_fenced_block_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "Gold SQL" in content
        assert "```sql" in content

    def test_predicted_sql_fenced_block_present(self, tmp_path):
        content = _generate(tmp_path)
        assert "Predicted SQL" in content

    def test_rubric_only_failure_uses_warning_emoji(self, tmp_path):
        # m01_rubric_only_failure: em=True, ex=True, rubric_wrong_dims=[time_frame] → ⚠️
        content = _generate(tmp_path)
        # Find the subsection for this case
        idx = content.find("m01_rubric_only_failure")
        assert idx != -1
        # The ⚠️ should appear near (before) the query_id in the heading
        heading_start = content.rfind("\n###", 0, idx)
        heading_text = content[heading_start:idx + len("m01_rubric_only_failure")]
        assert "⚠️" in heading_text

    def test_exec_failure_uses_cross_emoji(self, tmp_path):
        # h01: em=False, ex=False → ❌
        content = _generate(tmp_path)
        idx = content.find("h01_some_hard_query")
        assert idx != -1
        heading_start = content.rfind("\n###", 0, idx)
        heading_text = content[heading_start:idx + len("h01_some_hard_query")]
        assert "❌" in heading_text

    def test_em_ex_verdicts_shown(self, tmp_path):
        content = _generate(tmp_path)
        assert "EM:" in content
        assert "EX:" in content

    def test_rubric_dims_shown_inline(self, tmp_path):
        content = _generate(tmp_path)
        assert "Rubric:" in content
        # At least one dim=verdict pattern
        import re
        assert re.search(r"`\w+`=\w+", content)
