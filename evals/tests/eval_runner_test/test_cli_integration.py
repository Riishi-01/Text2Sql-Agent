"""End-to-end CLI tests for eval_runner.main(), with run_single_case mocked
out so no live database or OpenAI call is required.

These tests redirect RESULTS_DIR/CHECKPOINTS_DIR/CASES_DIR to temp
directories per-test so they never touch the real evals/results/ folder.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import eval_runner as er


def _fake_run_single_case(case, model, inject_failure, use_agent=False, statement_timeout_ms=15000):
    """Deterministic stand-in for run_single_case — no DB, no network."""
    return {
        "query_id": case["id"],
        "question": case.get("question", ""),
        "em": 1,
        "ex": 1,
        "latency_sec": 0.001,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "status": "pass",
        "table": "NA",
        "time_frame": "NA",
        "filters": "NA",
        "aggregation": "NA",
        "join": "NA",
        "difficulty": case.get("difficulty", ""),
        "gold_sql": case.get("gold_sql", ""),
        "predicted_sql": case.get("gold_sql", ""),
        "error": "",
        "ground_truth_rows": "[]",
    }


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect RESULTS_DIR / CHECKPOINTS_DIR / SUMMARY_DIR to a temp dir for this test."""
    results_dir = tmp_path / "results"
    checkpoints_dir = results_dir / "checkpoints"
    summary_dir = results_dir / "summary"
    monkeypatch.setattr(er, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(er, "CHECKPOINTS_DIR", checkpoints_dir)
    monkeypatch.setattr(er, "SUMMARY_DIR", summary_dir)
    return results_dir, checkpoints_dir


class TestMainSingleCase:
    def test_single_case_produces_one_row_csv(self, isolated_dirs):
        results_dir, _ = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--case", "e04_unique_customers", "--max-workers", "1"])
        assert rc == 0

        # CSV is written to RESULTS_DIR/eval_run.csv (latest copy)
        csv_file = results_dir / "eval_run.csv"
        assert csv_file.exists()

        import csv as csv_mod
        with csv_file.open(newline="", encoding="utf-8") as f:
            rows = list(csv_mod.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["query_id"] == "e04_unique_customers"

    def test_no_match_returns_nonzero(self, isolated_dirs):
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--case", "zzz_nonexistent", "--max-workers", "1"])
        assert rc == 1


class TestMainDifficultyFilter:
    def test_hard_filter_runs_10_cases(self, isolated_dirs):
        results_dir, _ = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--difficulty", "hard", "--max-workers", "4"])
        assert rc == 0

        # Find per_query.json in summary/{run_id}/metrics/
        summary_dir = results_dir / "summary"
        per_query_files = list(summary_dir.glob("*/metrics/per_query.json"))
        assert len(per_query_files) == 1
        data = json.loads(per_query_files[0].read_text())
        assert len(data) == 10
        assert all(r["difficulty"] == "hard" for r in data)


class TestMainOutputFiles:
    def test_all_four_output_files_written(self, isolated_dirs):
        results_dir, _ = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--case", "e04_unique_customers", "--max-workers", "1"])
        assert rc == 0

        # Latest copies are at RESULTS_DIR root
        latest_csv = results_dir / "eval_run.csv"
        latest_summary = results_dir / "eval_run.summary.json"
        latest_report = results_dir / "eval_run.report.md"

        assert latest_csv.exists()
        assert latest_summary.exists()
        assert latest_report.exists()

    def test_summary_json_shape(self, isolated_dirs):
        results_dir, _ = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--difficulty", "easy", "--max-workers", "4"])
        assert rc == 0

        # Latest copy is at RESULTS_DIR root
        summary_file = results_dir / "eval_run.summary.json"
        summary = json.loads(summary_file.read_text())

        for key in ("run_id", "model", "total", "passed", "failed", "errors",
                    "timeouts", "pass_rate", "metrics", "by_difficulty",
                    "by_dim_fail_rate", "failures"):
            assert key in summary

        assert summary["total"] == 16
        assert summary["passed"] == 16
        assert summary["pass_rate"] == 1.0
        assert summary["failures"] == []
        assert summary["model"] == "gold"

    def test_checkpoint_deleted_after_success(self, isolated_dirs):
        _, checkpoints_dir = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--case", "e04_unique_customers", "--max-workers", "1"])
        assert rc == 0

        remaining = list(checkpoints_dir.glob("*.checkpoint.jsonl")) if checkpoints_dir.exists() else []
        assert remaining == []


class TestMainResume:
    def test_resume_skips_completed_cases(self, isolated_dirs):
        results_dir, checkpoints_dir = isolated_dirs
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Simulate a partially-completed prior run for the "easy" cases:
        # pre-populate a checkpoint with all easy case ids except one.
        from checkpoint_manager import CheckpointManager

        easy_cases = er.discover_cases(difficulty_filter="easy")
        run_id = "20260101_000000"
        mgr = CheckpointManager(checkpoints_dir, run_id)
        for case in easy_cases[:-1]:
            mgr.append(_fake_run_single_case(case, None, None))

        call_log = []

        def counting_fake(case, model, inject_failure, use_agent=False, statement_timeout_ms=15000):
            call_log.append(case["id"])
            return _fake_run_single_case(case, model, inject_failure, use_agent, statement_timeout_ms)

        with patch.object(er, "run_single_case", counting_fake):
            rc = er.main(["--difficulty", "easy", "--resume", "--max-workers", "1"])

        assert rc == 0
        # Only the one missing case should have actually been executed.
        assert call_log == [easy_cases[-1]["id"]]

        # Find per_query.json in summary/{run_id}/metrics/
        summary_dir = results_dir / "summary"
        per_query_files = list(summary_dir.glob("*/metrics/per_query.json"))
        data = json.loads(per_query_files[0].read_text())
        assert len(data) == len(easy_cases)

    def test_resume_with_nothing_pending(self, isolated_dirs):
        results_dir, checkpoints_dir = isolated_dirs
        checkpoints_dir.mkdir(parents=True, exist_ok=True)

        from checkpoint_manager import CheckpointManager

        cases = er.discover_cases(case_filter="e04_unique_customers")
        run_id = "20260101_000001"
        mgr = CheckpointManager(checkpoints_dir, run_id)
        for case in cases:
            mgr.append(_fake_run_single_case(case, None, None))

        def failing_fake(*a, **kw):
            raise AssertionError("run_single_case should not be called when nothing is pending")

        with patch.object(er, "run_single_case", failing_fake):
            rc = er.main(["--case", "e04_unique_customers", "--resume", "--max-workers", "1"])

        assert rc == 0


class TestMainInjectFailure:
    def test_inject_flag_passed_through_to_runner(self, isolated_dirs):
        """--inject should surface as a ValueError -> status=error for cases
        whose runner.py only implements no_failure (the generated template).

        connection_scope is mocked (not the DB call itself) so this test
        exercises the real run_single_case() code path — including the
        runner.py dispatch — without requiring a live PostgreSQL database.
        """
        from contextlib import contextmanager

        @contextmanager
        def fake_scope(timeout_ms=15000):
            yield object()

        with patch.object(er, "connection_scope", fake_scope):
            rc = er.main(["--case", "e04_unique_customers", "--inject", "made_up_mode", "--max-workers", "1"])

        assert rc == 0

        results_dir, _ = isolated_dirs
        # Find per_query.json in summary/{run_id}/metrics/
        summary_dir = results_dir / "summary"
        per_query_files = list(summary_dir.glob("*/metrics/per_query.json"))
        data = json.loads(per_query_files[0].read_text())
        assert data[0]["status"] == "error"
        assert "ValueError" in data[0]["error"] or "TypeError" in data[0]["error"]


class TestMainNamedRun:
    def test_name_flag_slugs_run_dir_and_yaml(self, isolated_dirs):
        results_dir, _ = isolated_dirs
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--case", "e04_unique_customers", "--name", "Baseline 4o-mini!",
                          "--max-workers", "1"])
        assert rc == 0

        summary_dir = results_dir / "summary"
        run_dirs = [d for d in summary_dir.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        # slug prefix present
        assert run_dir.name.startswith("baseline_4o_mini_")
        # consolidated {run_id}.yaml exists and holds passes + failures keys
        run_yaml = run_dir / f"{run_dir.name}.yaml"
        assert run_yaml.exists()
        import yaml as _yaml
        doc = _yaml.safe_load(run_yaml.read_text())
        assert doc["name"] == "Baseline 4o-mini!"
        assert "passes" in doc and "failures" in doc
        assert "totals" in doc and doc["totals"]["total"] == 1


class TestMainRunYaml:
    def test_run_yaml_contains_pass_and_fail_sections(self, isolated_dirs):
        results_dir, _ = isolated_dirs

        def mixed_fake(case, model, inject_failure, use_agent=False, statement_timeout_ms=15000):
            r = _fake_run_single_case(case, model, inject_failure, use_agent, statement_timeout_ms)
            # make e02 a failure
            if case["id"].startswith("e02"):
                r["status"] = "fail"
                r["outcome"] = "fail"
                r["ex"] = 0
            return r

        with patch.object(er, "run_single_case", mixed_fake):
            rc = er.main(["--difficulty", "easy", "--max-workers", "4"])
        assert rc == 0

        run_dir = next((results_dir / "summary").iterdir())
        run_yaml = run_dir / f"{run_dir.name}.yaml"
        import yaml as _yaml
        doc = _yaml.safe_load(run_yaml.read_text())
        pass_ids = {p["query_id"] for p in doc["passes"]}
        fail_ids = {f["query_id"] for f in doc["failures"]}
        assert any(i.startswith("e02") for i in fail_ids)
        assert pass_ids and fail_ids
        assert doc["totals"]["failed"] == len(fail_ids)


class TestMainRerunFailures:
    def test_rerun_failures_reruns_only_prior_failures(self, isolated_dirs):
        results_dir, _ = isolated_dirs

        # First run: make e01 and e02 fail, rest pass.
        def first_fake(case, model, inject_failure, use_agent=False, statement_timeout_ms=15000):
            r = _fake_run_single_case(case, model, inject_failure, use_agent, statement_timeout_ms)
            if case["id"].startswith(("e01", "e02")):
                r["status"] = "fail"; r["outcome"] = "fail"; r["ex"] = 0
            return r

        with patch.object(er, "run_single_case", first_fake):
            rc = er.main(["--difficulty", "easy", "--name", "firstrun", "--max-workers", "4"])
        assert rc == 0

        # Second run: --rerun-failures firstrun → only the 2 prior failures execute.
        call_log = []

        def counting_fake(case, model, inject_failure, use_agent=False, statement_timeout_ms=15000):
            call_log.append(case["id"])
            return _fake_run_single_case(case, model, inject_failure, use_agent, statement_timeout_ms)

        with patch.object(er, "run_single_case", counting_fake):
            rc = er.main(["--rerun-failures", "firstrun", "--name", "rerun", "--max-workers", "2"])
        assert rc == 0

        assert len(call_log) == 2
        assert all(cid.startswith(("e01", "e02")) for cid in call_log)

    def test_rerun_unknown_run_returns_nonzero(self, isolated_dirs):
        with patch.object(er, "run_single_case", _fake_run_single_case):
            rc = er.main(["--rerun-failures", "does_not_exist_run", "--max-workers", "1"])
        assert rc == 1
