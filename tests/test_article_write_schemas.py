"""
Tests for the article write schemas against what the console actually posts.

Both write schemas are ``extra="forbid"`` with typed values, which makes them
unforgiving: a field the console sends but the schema does not declare is a 422,
not an ignored key. That is exactly how article editing broke — the console's
save payload carried `region` and `language`, which the read schema has but the
write schemas did not.

These tests pin the payload shapes the console builds so the two cannot drift
apart again silently.

Run with:  PYTHONPATH=src python -m pytest tests/test_article_write_schemas.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _create_payload(**overrides):
    """The payload the console's create modal builds with every field filled."""
    payload = {
        "urn": "mediterranean-diet-cardiovascular-outcomes",
        "title": "Mediterranean diet and cardiovascular outcomes",
        "venue": "The Lancet",
        "authors": ["Smith, J.", "Doe, A."],
        "content": "Body text",
        "abstract": "An abstract.",
        "publication_year": "2022-01-01",
        "url": "https://example.org/article",
        "doi": "10.1016/j.example.2022.01.001",
        "category": "Cardiometabolic Health",
        "study_type": "Meta-analysis",
        "reader_group": "Practitioners",
        "age_group": "Adults",
        "region": "Europe",
        "language": "en",
        "license": "CC-BY-4.0",
        "tags": ["diet", "cardiovascular"],
        "topics": ["Nutrition"],
        "open_access": True,
        "reader_visibility": "expert_only",
    }
    payload.update(overrides)
    return payload


class TestRegionAndLanguageAreWritable(unittest.TestCase):
    """
    Both fields exist on ArticleSchema and are indexed, so an editor setting
    them must not be rejected.
    """

    def test_create_accepts_region_and_language(self):
        from schemas import ArticleCreationSchema

        article = ArticleCreationSchema.model_validate(_create_payload())
        self.assertEqual(article.region, "Europe")
        self.assertEqual(article.language, "en")

    def test_update_accepts_region_and_language(self):
        from schemas import ArticleUpdateSchema

        update = ArticleUpdateSchema.model_validate(
            {"title": "T", "venue": "V", "region": "Europe", "language": "en"}
        )
        self.assertEqual(update.region, "Europe")
        self.assertEqual(update.language, "en")


class TestConsolePayloadsValidate(unittest.TestCase):
    def test_full_create_payload_validates(self):
        from schemas import ArticleCreationSchema

        ArticleCreationSchema.model_validate(_create_payload())

    def test_minimal_create_payload_validates(self):
        """Optional fields are omitted, never sent as empty strings."""
        from schemas import ArticleCreationSchema

        ArticleCreationSchema.model_validate(
            {
                "urn": "minimal-article",
                "title": "Minimal",
                "venue": "Journal",
                "authors": ["Solo, H."],
                "content": "Body",
            }
        )

    def test_empty_string_where_a_url_is_expected_is_rejected(self):
        """
        Why the create form omits blank optional fields instead of sending "".
        """
        from schemas import ArticleCreationSchema
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ArticleCreationSchema.model_validate(_create_payload(url=""))

    def test_full_update_payload_validates(self):
        from schemas import ArticleUpdateSchema

        payload = _create_payload()
        payload.pop("urn")
        payload["key_takeaways"] = ["One", "Two"]
        payload["keywords"] = ["omega-3"]
        payload["hard_exclusion_flags"] = []
        ArticleUpdateSchema.model_validate(payload)


class TestLicenseVocabulary(unittest.TestCase):
    """
    The console's licence dropdown must offer enum values, not display labels.
    It previously offered "CC BY 4.0" and five other labels the API rejects.
    """

    # Mirrors app/utils/consoleArticleVocabulary.ts `licenseOptions`.
    CONSOLE_LICENSE_VALUES = [
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "CCBY",
        "CCBYSA",
        "CCBYNC",
        "CCBYNCSA",
        "CCBYNCND",
        "CC0",
        "public-domain",
        "publisher-specific-oa",
        "unspecified-oa",
        "other-oa",
        "implied-oa",
        "publisher-specific, author manuscript",
        "elsevier-specific: oa user license",
        "Proprietary",
        "MIT",
        "Apache-2.0",
        "GPL-3.0",
    ]

    def test_every_console_license_option_is_accepted(self):
        from schemas import ArticleUpdateSchema

        for value in self.CONSOLE_LICENSE_VALUES:
            with self.subTest(license=value):
                update = ArticleUpdateSchema.model_validate({"license": value})
                self.assertEqual(update.license, value)

    def test_display_labels_are_still_rejected(self):
        """Guards against someone putting the labels back."""
        from schemas import ArticleUpdateSchema
        from pydantic import ValidationError

        for label in ("CC BY 4.0", "CC BY-SA 4.0", "All rights reserved"):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                ArticleUpdateSchema.model_validate({"license": label})


class TestArrayFieldConstraints(unittest.TestCase):
    """
    The console holds these as arrays of discrete tokens, so the caps and the
    uniqueness rule are enforced client-side too; these pin the server rules.
    """

    def test_explicit_empty_authors_is_rejected(self):
        """
        `authors` is min_length=1, so a form that always sends the array must
        omit it or send null when there are none.
        """
        from schemas import ArticleUpdateSchema
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ArticleUpdateSchema.model_validate({"authors": []})

    def test_null_authors_is_accepted(self):
        from schemas import ArticleUpdateSchema

        ArticleUpdateSchema.model_validate({"authors": None})

    def test_tags_must_be_case_insensitively_unique(self):
        from schemas import ArticleUpdateSchema
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ArticleUpdateSchema.model_validate({"tags": ["Diet", "diet"]})

    def test_key_takeaways_are_capped_at_ten(self):
        from schemas import ArticleUpdateSchema
        from pydantic import ValidationError

        ArticleUpdateSchema.model_validate(
            {"key_takeaways": [f"Takeaway {i}" for i in range(10)]}
        )
        with self.assertRaises(ValidationError):
            ArticleUpdateSchema.model_validate(
                {"key_takeaways": [f"Takeaway {i}" for i in range(11)]}
            )


class TestPublicationYearNormalization(unittest.TestCase):
    """The console sends `YYYY-01-01`; the API also accepts a bare year."""

    def test_accepted_forms(self):
        from schemas import ArticleUpdateSchema

        for value in (2022, "2022", "2022-04-01", "2022-04-01T00:00:00Z"):
            with self.subTest(value=value):
                update = ArticleUpdateSchema.model_validate(
                    {"publication_year": value}
                )
                self.assertEqual(update.publication_year.year, 2022)

    def test_nonsense_is_rejected(self):
        from schemas import ArticleUpdateSchema
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            ArticleUpdateSchema.model_validate({"publication_year": "last year"})


if __name__ == "__main__":
    unittest.main()
