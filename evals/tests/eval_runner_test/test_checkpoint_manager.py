"""Unit tests for checkpoint_manager.py — resumable-run checkpoint lifecycle."""
import json

import pytest

from checkpoint_manager import CheckpointManager


class TestBasicLifecycle:
    def test_append_and_track_completed_ids(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="t1")
        mgr.append({"query_id": "e01", "status": "pass"})
        mgr.append({"query_id": "e02", "status": "fail"})
        assert mgr.completed_ids == {"e01", "e02"}
        assert len(mgr.results) == 2

    def test_checkpoint_file_created_on_first_append(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="t2")
        assert not mgr.checkpoint_path.exists()
        mgr.append({"query_id": "e01", "status": "pass"})
        assert mgr.checkpoint_path.exists()

    def test_checkpoint_is_jsonlines(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="t3")
        mgr.append({"query_id": "e01", "status": "pass"})
        mgr.append({"query_id": "e02", "status": "fail"})

        lines = mgr.checkpoint_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["query_id"] == "e01"
        assert json.loads(lines[1])["query_id"] == "e02"


class TestFindLatest:
    def test_returns_none_when_no_checkpoints(self, tmp_path):
        assert CheckpointManager.find_latest(tmp_path) is None

    def test_returns_none_when_dir_missing(self, tmp_path):
        missing_dir = tmp_path / "does_not_exist"
        assert CheckpointManager.find_latest(missing_dir) is None

    def test_finds_most_recent_by_name(self, tmp_path):
        (tmp_path / "eval_run_20260101_000000.checkpoint.jsonl").write_text("")
        (tmp_path / "eval_run_20260201_000000.checkpoint.jsonl").write_text("")
        latest = CheckpointManager.find_latest(tmp_path)
        assert latest.name == "eval_run_20260201_000000.checkpoint.jsonl"


class TestLoadExisting:
    def test_load_existing_returns_completed_ids(self, tmp_path):
        mgr1 = CheckpointManager(tmp_path, run_id="load1")
        mgr1.append({"query_id": "e01", "status": "pass"})
        mgr1.append({"query_id": "e02", "status": "pass"})

        mgr2 = CheckpointManager(tmp_path, run_id="load2")
        loaded_ids = mgr2.load_existing(mgr1.checkpoint_path)
        assert loaded_ids == {"e01", "e02"}
        assert mgr2.checkpoint_path == mgr1.checkpoint_path  # adopts the path

    def test_load_existing_missing_file_returns_empty(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="load3")
        result = mgr.load_existing(tmp_path / "nope.checkpoint.jsonl")
        assert result == set()

    def test_load_existing_skips_corrupted_lines(self, tmp_path):
        path = tmp_path / "eval_run_x.checkpoint.jsonl"
        path.write_text(
            json.dumps({"query_id": "e01", "status": "pass"}) + "\n"
            + "{not valid json,,,\n"
            + json.dumps({"query_id": "e02", "status": "pass"}) + "\n"
        )
        mgr = CheckpointManager(tmp_path, run_id="load4")
        loaded_ids = mgr.load_existing(path)
        assert loaded_ids == {"e01", "e02"}

    def test_resume_after_load_continues_same_file(self, tmp_path):
        mgr1 = CheckpointManager(tmp_path, run_id="resume1")
        mgr1.append({"query_id": "e01", "status": "pass"})

        mgr2 = CheckpointManager(tmp_path, run_id="resume2")
        mgr2.load_existing(mgr1.checkpoint_path)
        mgr2.append({"query_id": "e02", "status": "pass"})

        # Both entries should now be in the same physical file.
        lines = mgr1.checkpoint_path.read_text().strip().split("\n")
        assert len(lines) == 2


class TestGetPendingCases:
    def test_filters_out_completed(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="pending1")
        mgr.append({"query_id": "e01", "status": "pass"})
        all_cases = [{"id": "e01"}, {"id": "e02"}, {"id": "e03"}]
        pending = mgr.get_pending_cases(all_cases)
        assert [c["id"] for c in pending] == ["e02", "e03"]

    def test_all_pending_when_nothing_completed(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="pending2")
        all_cases = [{"id": "e01"}, {"id": "e02"}]
        pending = mgr.get_pending_cases(all_cases)
        assert len(pending) == 2

    def test_none_pending_when_all_completed(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="pending3")
        mgr.append({"query_id": "e01", "status": "pass"})
        mgr.append({"query_id": "e02", "status": "pass"})
        pending = mgr.get_pending_cases([{"id": "e01"}, {"id": "e02"}])
        assert pending == []


class TestFinalizeAndDelete:
    def test_finalize_sorts_by_query_id(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="final1")
        mgr.append({"query_id": "e02", "status": "pass"})
        mgr.append({"query_id": "e01", "status": "pass"})
        finalized = mgr.finalize()
        assert [r["query_id"] for r in finalized] == ["e01", "e02"]

    def test_delete_removes_file(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="final2")
        mgr.append({"query_id": "e01", "status": "pass"})
        assert mgr.checkpoint_path.exists()
        mgr.delete()
        assert not mgr.checkpoint_path.exists()

    def test_delete_when_no_file_is_noop(self, tmp_path):
        mgr = CheckpointManager(tmp_path, run_id="final3")
        mgr.delete()  # should not raise even though nothing was ever appended


class TestThreadSafety:
    def test_concurrent_appends_all_recorded(self, tmp_path):
        import threading

        mgr = CheckpointManager(tmp_path, run_id="concurrent1")
        n_threads = 20

        def worker(i):
            mgr.append({"query_id": f"e{i:02d}", "status": "pass"})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(mgr.completed_ids) == n_threads
        lines = mgr.checkpoint_path.read_text().strip().split("\n")
        assert len(lines) == n_threads
        # Every line must be valid, complete JSON (no interleaved writes).
        for line in lines:
            json.loads(line)
