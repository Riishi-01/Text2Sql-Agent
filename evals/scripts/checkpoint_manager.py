#!/usr/bin/env python3
"""Checkpoint lifecycle management for resumable eval runs.

Checkpoint format: JSON Lines (one JSON object per completed case),
written incrementally so a crash mid-run loses at most the in-flight
cases, not everything already completed.

    results/checkpoints/eval_run_{run_id}.checkpoint.jsonl

Thread safety: `append()` is guarded by a `threading.Lock` so multiple
worker threads can safely call it as their futures complete.
"""
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class CheckpointManager:
    """Manages checkpoint lifecycle for resumable eval runs."""

    def __init__(self, checkpoint_dir: Path, run_id: str):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.checkpoint_path = self.checkpoint_dir / f"eval_run_{run_id}.checkpoint.jsonl"
        self._lock = threading.Lock()
        self.completed_ids: Set[str] = set()
        self.results: List[Dict[str, Any]] = []

    @classmethod
    def find_latest(cls, checkpoint_dir: Path) -> Optional[Path]:
        """Find the most recent checkpoint file by filename (timestamp-sorted)."""
        checkpoint_dir = Path(checkpoint_dir)
        if not checkpoint_dir.exists():
            return None
        candidates = sorted(checkpoint_dir.glob("eval_run_*.checkpoint.jsonl"))
        return candidates[-1] if candidates else None

    def load_existing(self, path: Path) -> Set[str]:
        """Load completed query_ids (and their results) from a checkpoint file.

        Tolerates a corrupted/partial final line (e.g. from a crash mid-write)
        by skipping lines that fail to parse.
        """
        path = Path(path)
        self.results = []
        self.completed_ids = set()

        if not path.exists():
            return self.completed_ids

        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip corrupted/partial line
                query_id = record.get("query_id")
                if not query_id:
                    continue
                self.completed_ids.add(query_id)
                self.results.append(record)

        # Adopt this path as our own checkpoint file so subsequent appends
        # continue the same run rather than starting a new file.
        self.checkpoint_path = path
        return self.completed_ids

    def append(self, result: Dict[str, Any]) -> None:
        """Thread-safe append of a single result to the checkpoint file."""
        with self._lock:
            with self.checkpoint_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result, default=str) + "\n")
            self.results.append(result)
            query_id = result.get("query_id")
            if query_id:
                self.completed_ids.add(query_id)

    def get_pending_cases(self, all_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out cases whose id is already in completed_ids."""
        return [c for c in all_cases if c.get("id") not in self.completed_ids]

    def finalize(self) -> List[Dict[str, Any]]:
        """Return all accumulated results, sorted by query_id.

        Does NOT delete the checkpoint file — that is the caller's
        responsibility once final outputs have been written successfully,
        so a crash during output-writing still leaves a recoverable
        checkpoint.
        """
        return sorted(self.results, key=lambda r: r.get("query_id", ""))

    def delete(self) -> None:
        """Remove the checkpoint file after a successful run completion."""
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()


def _self_test() -> None:
    import shutil
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp())
    try:
        mgr = CheckpointManager(tmp_dir, run_id="selftest")
        assert mgr.checkpoint_path.parent == tmp_dir

        mgr.append({"query_id": "e01", "status": "pass"})
        mgr.append({"query_id": "e02", "status": "fail"})
        assert mgr.completed_ids == {"e01", "e02"}
        assert len(mgr.results) == 2

        # Simulate resume: fresh manager, load from the same file.
        mgr2 = CheckpointManager(tmp_dir, run_id="selftest2")
        latest = CheckpointManager.find_latest(tmp_dir)
        assert latest == mgr.checkpoint_path
        loaded = mgr2.load_existing(latest)
        assert loaded == {"e01", "e02"}

        pending = mgr2.get_pending_cases([{"id": "e01"}, {"id": "e02"}, {"id": "e03"}])
        assert [c["id"] for c in pending] == ["e03"]

        finalized = mgr2.finalize()
        assert [r["query_id"] for r in finalized] == ["e01", "e02"]

        mgr2.delete()
        assert not mgr2.checkpoint_path.exists()

        print("checkpoint_manager self-test: ALL PASSED")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        _self_test()
    else:
        print("Usage: python3 checkpoint_manager.py --test")
