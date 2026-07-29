"""
Tests for article editorial policy: reader visibility and indexing tier.

The behaviour that matters most here is what happens to articles indexed
*before* these fields existed. They carry no `reader_visibility` and no tier, and
every read path must treat that as "public, untiered" — otherwise introducing the
field would silently hide the entire existing corpus.

Scope note: `backend.elastic` opens a connection to Elasticsearch at import time,
so `entities.articles` (and therefore `Article.set_editorial_policy`) cannot be
imported without a live cluster. These tests cover the layers that import
cleanly — the visibility helpers and request-schema validation.

Run with:  PYTHONPATH=src python -m pytest tests/test_article_editorial_policy.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestReaderVisibilityHelpers(unittest.TestCase):
    def test_legacy_article_without_the_field_is_public(self):
        from catalog_access import is_visible_to_reader

        legacy = {"urn": "urn:article:old", "title": "Indexed before the field existed"}

        self.assertTrue(is_visible_to_reader(legacy, "beginner"))
        self.assertTrue(is_visible_to_reader(legacy, "intermediate"))
        self.assertTrue(is_visible_to_reader(legacy, "expert"))
        self.assertTrue(is_visible_to_reader(legacy, None))

    def test_expert_only_is_hidden_from_non_experts(self):
        from catalog_access import is_visible_to_reader

        article = {"reader_visibility": "expert_only"}

        self.assertFalse(is_visible_to_reader(article, "beginner"))
        self.assertFalse(is_visible_to_reader(article, "intermediate"))
        self.assertFalse(is_visible_to_reader(article, None))
        self.assertTrue(is_visible_to_reader(article, "expert"))

    def test_hidden_is_hidden_from_everyone(self):
        from catalog_access import is_visible_to_reader

        article = {"reader_visibility": "hidden"}

        self.assertFalse(is_visible_to_reader(article, "beginner"))
        self.assertFalse(is_visible_to_reader(article, "expert"))

    def test_explicit_public_is_visible_to_all(self):
        from catalog_access import is_visible_to_reader

        article = {"reader_visibility": "public"}

        self.assertTrue(is_visible_to_reader(article, "beginner"))
        self.assertTrue(is_visible_to_reader(article, "expert"))

    def test_reader_level_matching_is_case_insensitive(self):
        from catalog_access import is_expert_reader

        self.assertTrue(is_expert_reader("Expert"))
        self.assertTrue(is_expert_reader(" expert "))
        self.assertFalse(is_expert_reader("experts"))
        self.assertFalse(is_expert_reader(""))
        self.assertFalse(is_expert_reader(None))

    def test_filter_clauses_are_exclusions_so_legacy_docs_survive(self):
        from catalog_access import reader_visibility_clause

        # A positive clause (reader_visibility:public) would drop every document
        # indexed before the field existed. These must stay exclusions.
        self.assertTrue(reader_visibility_clause("beginner").startswith("NOT "))
        self.assertTrue(reader_visibility_clause("expert").startswith("NOT "))

    def test_non_expert_clause_excludes_expert_only_and_hidden(self):
        from catalog_access import reader_visibility_clause

        clause = reader_visibility_clause("beginner")

        self.assertIn("expert_only", clause)
        self.assertIn("hidden", clause)

    def test_expert_clause_still_excludes_hidden_but_not_expert_only(self):
        from catalog_access import apply_reader_visibility_filter

        query = apply_reader_visibility_filter({"q": "omega 3"}, "expert")

        self.assertIn("NOT reader_visibility:hidden", query["fq"])
        self.assertNotIn("expert_only", " ".join(query["fq"]))
        self.assertEqual(query["q"], "omega 3")

    def test_filter_is_appended_not_replaced(self):
        from catalog_access import apply_reader_visibility_filter

        query = apply_reader_visibility_filter(
            {"fq": ["status:active"]}, "intermediate"
        )

        self.assertIn("status:active", query["fq"])
        self.assertEqual(len(query["fq"]), 2)

    def test_applying_the_filter_twice_does_not_duplicate_it(self):
        from catalog_access import apply_reader_visibility_filter

        query = apply_reader_visibility_filter({}, "beginner")
        query = apply_reader_visibility_filter(query, "beginner")

        self.assertEqual(len(query["fq"]), 1)

    def test_source_query_is_not_mutated(self):
        from catalog_access import apply_reader_visibility_filter

        original = {"q": "iron", "fq": ["status:active"]}
        apply_reader_visibility_filter(original, "beginner")

        self.assertEqual(original["fq"], ["status:active"])


class TestEditorialPolicySchema(unittest.TestCase):
    def test_selection_is_required(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(reader_visibility="hidden")

    def test_a_change_is_required(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(q="omega 3")

    def test_tier_and_clear_are_mutually_exclusive(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(
                q="omega 3", indexing_tier="prime", clear_indexing_tier=True
            )

    def test_unknown_tier_is_rejected(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(q="omega 3", indexing_tier="platinum")

    def test_unknown_visibility_is_rejected(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(q="omega 3", reader_visibility="secret")

    def test_query_selection_is_accepted(self):
        from schemas import ArticleEditorialPolicySchema

        spec = ArticleEditorialPolicySchema(
            q="omega 3",
            fq=['study_type:"Meta-analysis"'],
            indexing_tier="prime",
        )

        self.assertEqual(spec.indexing_tier, "prime")
        self.assertEqual(spec.fq, ['study_type:"Meta-analysis"'])
        self.assertFalse(spec.dry_run)

    def test_urn_selection_is_accepted(self):
        from schemas import ArticleEditorialPolicySchema

        spec = ArticleEditorialPolicySchema(
            urns=["urn:article:a", "urn:article:b"],
            reader_visibility="expert_only",
        )

        self.assertEqual(len(spec.urns), 2)
        self.assertEqual(spec.reader_visibility, "expert_only")

    def test_clear_tier_alone_is_a_valid_change(self):
        from schemas import ArticleEditorialPolicySchema

        spec = ArticleEditorialPolicySchema(
            urns=["urn:article:a"], clear_indexing_tier=True
        )

        self.assertTrue(spec.clear_indexing_tier)
        self.assertIsNone(spec.indexing_tier)

    def test_max_docs_is_bounded(self):
        from schemas import ArticleEditorialPolicySchema

        with self.assertRaises(Exception):
            ArticleEditorialPolicySchema(
                q="omega 3", indexing_tier="core", max_docs=10001
            )


class TestArticleSchemaDefaults(unittest.TestCase):
    def test_reader_visibility_defaults_to_public(self):
        from schemas import ArticleUpdateSchema, ReaderVisibility

        self.assertEqual(ReaderVisibility.public.value, "public")
        # PATCH leaves the field untouched when the caller omits it.
        spec = ArticleUpdateSchema()
        self.assertIsNone(spec.reader_visibility)
        self.assertIsNone(spec.indexing_tier)

    def test_prime_is_editorial_only(self):
        from schemas import IndexingTier

        # The enrichment prompt only emits core..do_not_index, so `prime` can
        # never arrive from the model — it is always a human decision.
        self.assertIn("prime", [t.value for t in IndexingTier])

    def test_ai_indexing_tier_is_an_enhancement_field(self):
        from schemas import AIEnhancedField

        self.assertIn("ai_indexing_tier", [f.value for f in AIEnhancedField])


if __name__ == "__main__":
    unittest.main()
