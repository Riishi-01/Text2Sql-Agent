"""Tests for CSV/JSON output writers and CSV column contract."""
import csv
import json
from pathlib import Path

import eval_runner as er


def _sample_result(query_id="e01", **overrides):
    base = {
        "query_id": query_id, "question": "how many orders?", "em": 1, "ex": 1,
        "latency_sec": 0.012, "input_tokens": 0, "output_tokens": 0,
        "cost_usd": 0.0, "status": "pass", "table": "correct", "time_frame": "NA",
        "filters": "NA", "aggregation": "correct", "join": "NA",
        "difficulty": "easy", "gold_sql": "SELECT COUNT(*) FROM orders",
        "predicted_sql": "SELECT COUNT(*) FROM orders",
        "error": "", "ground_truth_rows": json.dumps([{"count": 99441}]),
    }
    base.update(overrides)
    return base


class TestWriteCsv:
    def test_writes_header_with_exactly_19_columns(self, tmp_path):
        path = tmp_path / "out.csv"
        er.write_csv([_sample_result()], path)

        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

        assert header == er.CSV_COLUMNS
        assert len(header) == 19

    def test_row_count_matches_input(self, tmp_path):
        path = tmp_path / "out.csv"
        results = [_sample_result(f"e{i:02d}") for i in range(5)]
        er.write_csv(results, path)

        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 5
        assert {r["query_id"] for r in rows} == {f"e{i:02d}" for i in range(5)}

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "out.csv"
        er.write_csv([_sample_result()], path)
        assert path.exists()

    def test_column_order_exact(self, tmp_path):
        expected_order = [
            "query_id", "question", "em", "ex", "latency_sec", "input_tokens",
            "output_tokens", "cost_usd", "status", "table", "time_frame",
            "filters", "aggregation", "join", "difficulty", "gold_sql",
            "predicted_sql", "error", "ground_truth_rows",
        ]
        path = tmp_path / "out.csv"
        er.write_csv([_sample_result()], path)
        with path.open(newline="", encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert header == expected_order


class TestWritePerQueryJson:
    def test_writes_valid_json_list(self, tmp_path):
        path = tmp_path / "out.per_query.json"
        results = [_sample_result("e01"), _sample_result("e02")]
        er.write_per_query_json(results, path)

        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, list)
        assert len(loaded) == 2
        assert loaded[0]["query_id"] == "e01"

    def test_matches_csv_data(self, tmp_path):
        results = [_sample_result("e01", em=1, ex=0, status="fail")]
        json_path = tmp_path / "out.json"
        csv_path = tmp_path / "out.csv"

        er.write_per_query_json(results, json_path)
        er.write_csv(results, csv_path)

        loaded_json = json.loads(json_path.read_text(encoding="utf-8"))
        with csv_path.open(newline="", encoding="utf-8") as f:
            loaded_csv = list(csv.DictReader(f))

        assert loaded_json[0]["query_id"] == loaded_csv[0]["query_id"]
        assert str(loaded_json[0]["em"]) == loaded_csv[0]["em"]
