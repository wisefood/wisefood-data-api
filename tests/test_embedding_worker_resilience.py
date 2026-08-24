"""The embedding worker loop must be unkillable.

A single transient Redis error used to escape ``run_forever`` and end the
daemon thread permanently — after which every backfill click reported
"queued" into a queue nothing consumed. These tests pin the guarantee: loop
errors back off and retry, job failures are recorded per-job, and only the
stop event ends the loop.
"""
import sys
import threading
import types
import unittest
from unittest.mock import patch

# backend.elastic connects to the cluster at import time; none of these tests
# touch Elasticsearch, so stub the module before the worker import pulls it in.
if "backend.elastic" not in sys.modules:
    _fake_elastic = types.ModuleType("backend.elastic")
    _fake_elastic.ELASTIC_CLIENT = None
    sys.modules["backend.elastic"] = _fake_elastic


class _FlakyQueue:
    """pop() raises once (transient Redis error), then serves one bad job,
    then signals shutdown."""

    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event
        self.calls = 0
        self.started = []
        self.completed = []
        self.failed = []

    def pop(self, timeout=5):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("redis blip")
        if self.calls == 2:
            # Missing 'text' → the job itself fails; the loop must survive.
            return {"job_id": "j1", "job_type": "entity_embedding", "urn": "u1"}
        self.stop_event.set()
        return None

    def mark_started(self, job_id):
        self.started.append(job_id)

    def mark_completed(self, job_id, metadata=None):
        self.completed.append(job_id)

    def mark_failed(self, job_id, error):
        self.failed.append((job_id, error))


class EmbeddingWorkerResilienceTests(unittest.TestCase):
    def test_loop_survives_pop_errors_and_job_failures(self):
        from workers import embedding_worker as ew

        stop = threading.Event()
        queue = _FlakyQueue(stop)
        # Skip __init__: the model is irrelevant here and heavy to load.
        worker = ew.EmbeddingWorker.__new__(ew.EmbeddingWorker)

        baseline_loop_errors = ew.WORKER_STATUS["loop_errors"]
        baseline_failed = ew.WORKER_STATUS["failed"]

        with patch.object(ew, "EMBEDDING_QUEUE", queue):
            # Returns (instead of dying) only if the loop survived the blip
            # and the failing job, and honored the stop event.
            worker.run_forever(sleep_when_idle=0, stop_event=stop)

        self.assertGreaterEqual(queue.calls, 3)
        self.assertEqual([job_id for job_id, _ in queue.failed], ["j1"])
        self.assertEqual(queue.completed, [])
        self.assertEqual(
            ew.WORKER_STATUS["loop_errors"], baseline_loop_errors + 1
        )
        self.assertEqual(ew.WORKER_STATUS["failed"], baseline_failed + 1)
        # last_error tracks the most recent failure — here the bad job, which
        # arrived after the transient pop error.
        self.assertIn("text", ew.WORKER_STATUS["last_error"] or "")
        self.assertIsNotNone(ew.WORKER_STATUS["last_poll_at"])

    def test_stop_during_error_backoff_exits_promptly(self):
        from workers import embedding_worker as ew

        stop = threading.Event()

        class _AlwaysBroken:
            def pop(self, timeout=5):
                # Ask for shutdown while the worker is inside its backoff wait.
                stop.set()
                raise RuntimeError("redis down")

        worker = ew.EmbeddingWorker.__new__(ew.EmbeddingWorker)
        with patch.object(ew, "EMBEDDING_QUEUE", _AlwaysBroken()):
            worker.run_forever(sleep_when_idle=0, stop_event=stop)
        # Reaching here at all is the assertion: the backoff wait honored the
        # stop event instead of sleeping blind.


if __name__ == "__main__":
    unittest.main()
