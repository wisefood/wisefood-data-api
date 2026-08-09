"""
Tests for the rule deciding when a write invalidates a stored embedding.

The bug this guards against: `Article.patch` — the path the console uses for
human edits — wrote straight to Elasticsearch and never re-embedded, while
`create` and `enhance` both did. An editor rewriting a title or abstract left
the stored vector describing the old text.

That is worse than a missing embedding. `embedded_at` stays populated, so the
document still reports as embedded, semantic retrieval keeps matching the
previous wording, and `backfill_embeddings(only_missing=True)` skips it — so
the drift never surfaces and never self-heals.

Scope note: `backend.elastic` connects at import time, so `entities.articles`
cannot be imported without a live cluster. The decision itself lives in
`embedding_policy`, which imports nothing, so the real predicate the entity
calls is exercised here rather than a copy of it.

Run with:  PYTHONPATH=src python -m pytest tests/test_embedding_policy.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from embedding_policy import (  # noqa: E402
    EMBEDDED_ARTICLE_FIELDS,
    EMBEDDED_GUIDELINE_FIELDS,
    embedding_is_stale,
    requires_reembedding,
)


class TestArticleFieldSet(unittest.TestCase):
    def test_covers_exactly_what_embed_concatenates(self):
        """
        `Article.embed()` builds its text from these three and nothing else.
        If a field is added there, it must be added here or edits to it will
        silently leave a stale vector.
        """
        self.assertEqual(tuple(EMBEDDED_ARTICLE_FIELDS), ("title", "abstract", "content"))


class TestRequiresReembedding(unittest.TestCase):
    def test_title_only_edit_re_embeds(self):
        self.assertTrue(requires_reembedding({"title": "New"}, EMBEDDED_ARTICLE_FIELDS))

    def test_abstract_only_edit_re_embeds(self):
        self.assertTrue(
            requires_reembedding({"abstract": "Rewritten"}, EMBEDDED_ARTICLE_FIELDS)
        )

    def test_content_only_edit_re_embeds(self):
        self.assertTrue(
            requires_reembedding({"content": "Body"}, EMBEDDED_ARTICLE_FIELDS)
        )

    def test_editorial_only_edit_does_not_re_embed(self):
        """A visibility or tier change costs no embedding work."""
        changed = {
            "reader_visibility": "expert_only",
            "indexing_tier": "prime",
            "status": "active",
        }

        self.assertFalse(requires_reembedding(changed, EMBEDDED_ARTICLE_FIELDS))

    def test_metadata_only_edit_does_not_re_embed(self):
        changed = {"region": "IE", "language": "en", "tags": ["diet"], "license": "CC-BY-4.0"}

        self.assertFalse(requires_reembedding(changed, EMBEDDED_ARTICLE_FIELDS))

    def test_mixed_edit_re_embeds(self):
        """One semantic field among many non-semantic ones is still enough."""
        changed = {"status": "active", "region": "IE", "abstract": "Rewritten"}

        self.assertTrue(requires_reembedding(changed, EMBEDDED_ARTICLE_FIELDS))

    def test_empty_patch_does_not_re_embed(self):
        self.assertFalse(requires_reembedding({}, EMBEDDED_ARTICLE_FIELDS))

    def test_accepts_any_iterable_of_names(self):
        """
        Call sites pass different shapes: `patch` passes the dumped dict (so
        iteration yields keys), `enhance` passes `spec.fields`. Both must work.
        """
        self.assertTrue(requires_reembedding(["title"], EMBEDDED_ARTICLE_FIELDS))
        self.assertTrue(requires_reembedding({"title": "x"}.keys(), EMBEDDED_ARTICLE_FIELDS))
        self.assertTrue(requires_reembedding({"title": "x"}, EMBEDDED_ARTICLE_FIELDS))

    def test_field_sets_are_independent(self):
        """
        A guideline's text fields are not an article's. `rule_text` must not
        trigger on the article set, and `abstract` must not on the guideline set
        — otherwise one entity's edits would drive the other's rule.
        """
        self.assertFalse(
            requires_reembedding({"rule_text": "x"}, EMBEDDED_ARTICLE_FIELDS)
        )
        self.assertFalse(
            requires_reembedding({"abstract": "x"}, EMBEDDED_GUIDELINE_FIELDS)
        )
        self.assertTrue(
            requires_reembedding({"rule_text": "x"}, EMBEDDED_GUIDELINE_FIELDS)
        )


class TestEmbeddingIsStale(unittest.TestCase):
    """
    The recovery half. Before this existed, `only_missing=True` skipped every
    document whose `embedded_at` was set — including the ones whose text had
    since changed — so a stale vector could never be repaired by a backfill,
    only by re-embedding the entire corpus.
    """

    def test_edited_after_embedding_is_stale(self):
        self.assertTrue(
            embedding_is_stale("2026-08-09T12:00:00", "2026-08-09T11:00:00")
        )

    def test_embedded_after_editing_is_current(self):
        self.assertFalse(
            embedding_is_stale("2026-08-09T11:00:00", "2026-08-09T12:00:00")
        )

    def test_identical_timestamps_are_current(self):
        """Embedded in the same instant as the write — not evidence of drift."""
        self.assertFalse(
            embedding_is_stale("2026-08-09T12:00:00", "2026-08-09T12:00:00")
        )

    def test_never_embedded_is_not_stale(self):
        """That is *missing*, which the caller counts separately."""
        self.assertFalse(embedding_is_stale("2026-08-09T12:00:00", None))
        self.assertFalse(embedding_is_stale("2026-08-09T12:00:00", ""))

    def test_no_update_timestamp_is_not_stale(self):
        """Nothing to compare against; do not re-queue on no evidence."""
        self.assertFalse(embedding_is_stale(None, "2026-08-09T12:00:00"))

    def test_unparseable_timestamp_is_treated_as_stale(self):
        """
        Backfill is explicit and capped, so re-embedding on bad data is the
        cheap mistake; keeping a wrong vector silently is the expensive one.
        """
        self.assertTrue(embedding_is_stale("not-a-date", "2026-08-09T12:00:00"))
        self.assertTrue(embedding_is_stale("2026-08-09T12:00:00", "not-a-date"))

    def test_sub_second_precision_is_respected(self):
        """`datetime.now().isoformat()` includes microseconds."""
        self.assertTrue(
            embedding_is_stale(
                "2026-08-09T12:00:00.000002", "2026-08-09T12:00:00.000001"
            )
        )
        self.assertFalse(
            embedding_is_stale(
                "2026-08-09T12:00:00.000001", "2026-08-09T12:00:00.000002"
            )
        )

    def test_a_patched_article_is_recoverable(self):
        """
        The end-to-end shape of the original bug: an article embedded on
        create, then patched by an editor. It must be re-queued.
        """
        article = {
            "urn": "urn:article:x",
            "embedded_at": "2026-08-01T09:00:00",
            "updated_at": "2026-08-09T15:30:00",
        }

        self.assertTrue(
            embedding_is_stale(article["updated_at"], article["embedded_at"])
        )


if __name__ == "__main__":
    unittest.main()
