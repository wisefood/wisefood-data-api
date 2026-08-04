"""
Tests for embedding-backfill paging under realistic worker latency.

The backfill queues jobs for an asynchronous worker, so documents do NOT gain
``embedded_at`` during the run. An earlier version filtered the scan on that
field and reset the paging cursor to compensate, which meant the same
unprocessed page was re-queued until the cap was hit — flooding the queue with
duplicates while never reaching the rest of the corpus.

These tests drive the paging logic against a fake index that behaves the way
Elasticsearch actually does: the filter is stable, and nothing gets embedded
while the backfill is running.

Scope note: ``backend.elastic`` connects at import time, so the entity classes
cannot be imported without a live cluster. The paging algorithm is exercised
here as an extracted reference implementation kept deliberately in lockstep with
``Guideline.backfill_embeddings`` / ``Article.backfill_embeddings``; the test
asserts the properties that matter (no duplicates, full coverage, termination).

Run with:  PYTHONPATH=src python -m pytest tests/test_embedding_backfill_paging.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

PAGE_SIZE = 500
MAX_SCAN = 200000


def run_backfill(corpus, *, only_missing=True, max_docs=10000, dry_run=False):
    """
    Reference implementation of the backfill paging loop.

    Mirrors the entity methods: scan a stable set sorted by a unique key, skip
    already-embedded documents in Python, page strictly forward, and guard
    against duplicates with a seen set.
    """
    ordered = sorted(corpus, key=lambda doc: doc["id"])

    queued, failed, skipped, scanned, offset = 0, 0, 0, 0, 0
    seen = set()
    enqueued = []

    while queued + failed < max_docs and scanned < MAX_SCAN:
        page = ordered[offset:offset + PAGE_SIZE]
        if not page:
            break
        scanned += len(page)

        for doc in page:
            if queued + failed >= max_docs:
                break
            identifier = doc["id"]
            if identifier in seen:
                continue
            seen.add(identifier)

            if only_missing and doc.get("embedded_at"):
                skipped += 1
                continue
            if not dry_run:
                enqueued.append(identifier)
            queued += 1

        if len(page) < PAGE_SIZE:
            break
        offset += len(page)

    return {
        "queued": queued,
        "failed": failed,
        "skipped_already_embedded": skipped,
        "scanned": scanned,
        "enqueued": enqueued,
    }


def corpus(total, embedded=0):
    """A corpus of `total` docs where the first `embedded` already have vectors."""
    return [
        {
            "id": f"{index:06d}",
            "embedded_at": "2026-01-01T00:00:00" if index < embedded else None,
        }
        for index in range(total)
    ]


class TestBackfillPaging(unittest.TestCase):
    def test_every_document_is_queued_exactly_once(self):
        """
        The corpus is larger than one page and nothing completes during the
        run — the case that previously produced duplicates.
        """
        result = run_backfill(corpus(2700))

        self.assertEqual(result["queued"], 2700)
        self.assertEqual(len(result["enqueued"]), 2700)
        self.assertEqual(
            len(set(result["enqueued"])), 2700, "the same document was queued twice"
        )

    def test_already_embedded_documents_are_skipped_not_requeued(self):
        result = run_backfill(corpus(2700, embedded=2000))

        self.assertEqual(result["queued"], 700)
        self.assertEqual(result["skipped_already_embedded"], 2000)
        self.assertEqual(len(set(result["enqueued"])), 700)

    def test_a_fully_embedded_corpus_queues_nothing_and_terminates(self):
        result = run_backfill(corpus(2700, embedded=2700))

        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["skipped_already_embedded"], 2700)
        # Termination matters: skips must not stall the cursor.
        self.assertEqual(result["scanned"], 2700)

    def test_max_docs_caps_queueing_without_duplicates(self):
        result = run_backfill(corpus(2700), max_docs=1000)

        self.assertEqual(result["queued"], 1000)
        self.assertEqual(len(set(result["enqueued"])), 1000)

    def test_only_missing_false_requeues_everything(self):
        """Used to force a re-embed after changing the embedding text."""
        result = run_backfill(corpus(1200, embedded=1200), only_missing=False)

        self.assertEqual(result["queued"], 1200)
        self.assertEqual(result["skipped_already_embedded"], 0)

    def test_dry_run_counts_without_enqueueing(self):
        result = run_backfill(corpus(2700), dry_run=True)

        self.assertEqual(result["queued"], 2700)
        self.assertEqual(result["enqueued"], [])

    def test_exact_page_multiple_terminates(self):
        """A corpus that is an exact multiple of the page size must not loop."""
        result = run_backfill(corpus(PAGE_SIZE * 3))

        self.assertEqual(result["queued"], PAGE_SIZE * 3)
        self.assertEqual(len(set(result["enqueued"])), PAGE_SIZE * 3)

    def test_empty_corpus(self):
        result = run_backfill([])

        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["scanned"], 0)


class TestEntityImplementationsMatch(unittest.TestCase):
    """
    The entity methods cannot be imported without Elasticsearch, so guard the
    two properties that made the original version wrong by reading the source.
    """

    def _source(self, relative_path):
        path = Path(__file__).resolve().parents[1] / "src" / relative_path
        return path.read_text(encoding="utf-8")

    def test_neither_backfill_filters_the_scan_on_embedded_at(self):
        for module in ("entities/guidelines.py", "entities/articles.py"):
            with self.subTest(module=module):
                source = self._source(module)
                start = source.index("def backfill_embeddings")
                body = source[start:start + 4000]
                self.assertNotIn(
                    "NOT _exists_:embedded_at",
                    body,
                    "filtering the scan on a field the worker mutates makes "
                    "paging non-deterministic",
                )

    def test_neither_backfill_resets_the_paging_cursor(self):
        for module in ("entities/guidelines.py", "entities/articles.py"):
            with self.subTest(module=module):
                source = self._source(module)
                start = source.index("def backfill_embeddings")
                body = source[start:start + 4000]
                self.assertIn("offset += len(results)", body)
                self.assertNotIn("offset = 0 if only_missing", body)

    def test_both_backfills_guard_against_duplicates(self):
        for module in ("entities/guidelines.py", "entities/articles.py"):
            with self.subTest(module=module):
                source = self._source(module)
                start = source.index("def backfill_embeddings")
                body = source[start:start + 4000]
                self.assertIn("seen", body)


if __name__ == "__main__":
    unittest.main()
