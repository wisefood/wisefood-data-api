"""
Tests for guideline enrichment facets, the no-clobber guard, and the bulk
editorial-policy request schema.

The behaviour that matters most here is what happens to the ~2700 guidelines
indexed *before* the facet fields existed: minimal legacy payloads must keep
validating, and a machine enrichment pass must never overwrite a value a human
editor set.

Scope note: `backend.elastic` opens a connection to Elasticsearch at import
time, so `entities.guidelines` (and therefore `Guideline.enrich`) cannot be
imported without a live cluster. These tests cover the layers that import
cleanly — the write-guard helpers in `catalog_access` and schema validation.

Run with:  PYTHONPATH=src python -m pytest tests/test_guideline_enrichment.py
"""

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestSelectEnrichableUpdates(unittest.TestCase):
    def test_empty_fields_are_writable(self):
        from catalog_access import select_enrichable_updates

        current = {"rule_text": "Eat vegetables.", "life_stage": [], "setting": None}
        writable, skipped = select_enrichable_updates(
            current, {"life_stage": ["early_childhood"], "setting": ["home"]}
        )

        self.assertEqual(
            writable, {"life_stage": ["early_childhood"], "setting": ["home"]}
        )
        self.assertEqual(skipped, [])

    def test_human_edited_field_is_skipped(self):
        from catalog_access import select_enrichable_updates

        current = {"life_stage": ["adulthood"], "ai_generated_fields": []}
        writable, skipped = select_enrichable_updates(
            current, {"life_stage": ["early_childhood"]}
        )

        self.assertEqual(writable, {})
        self.assertEqual(skipped, ["life_stage"])

    def test_machine_written_field_is_rewritable(self):
        from catalog_access import select_enrichable_updates

        current = {
            "life_stage": ["adulthood"],
            "ai_generated_fields": ["life_stage"],
        }
        writable, skipped = select_enrichable_updates(
            current, {"life_stage": ["early_childhood"]}
        )

        self.assertEqual(writable, {"life_stage": ["early_childhood"]})
        self.assertEqual(skipped, [])

    def test_force_fields_bypass_the_guard(self):
        from catalog_access import select_enrichable_updates

        current = {"action_type": "choose", "ai_generated_fields": []}
        writable, skipped = select_enrichable_updates(
            current, {"action_type": "limit"}, force_fields=["action_type"]
        )

        self.assertEqual(writable, {"action_type": "limit"})
        self.assertEqual(skipped, [])

    def test_enrichment_metadata_is_always_writable(self):
        from catalog_access import select_enrichable_updates

        current = {"enrichment_version": 1, "enrichment_confidence": 0.4}
        writable, skipped = select_enrichable_updates(
            current, {"enrichment_version": 2, "enrichment_confidence": 0.9}
        )

        self.assertEqual(
            writable, {"enrichment_version": 2, "enrichment_confidence": 0.9}
        )
        self.assertEqual(skipped, [])


class TestRetainHumanEditedFields(unittest.TestCase):
    def test_edited_machine_field_becomes_human_owned(self):
        from catalog_access import retain_human_edited_fields

        remaining = retain_human_edited_fields(
            ["life_stage", "setting"], ["life_stage", "notes"]
        )
        self.assertEqual(remaining, ["setting"])

    def test_no_machine_fields_is_a_noop(self):
        from catalog_access import retain_human_edited_fields

        self.assertEqual(retain_human_edited_fields(None, ["life_stage"]), [])


class TestGuidelineSchemaBackCompat(unittest.TestCase):
    def _minimal_doc(self):
        return {
            "id": str(uuid.uuid4()),
            "guide_urn": "urn:guide:test",
            "rule_text": "Provide portions of red meat twice a week.",
            "sequence_no": 1,
            "action_type": "eat",
        }

    def test_legacy_doc_without_facets_validates(self):
        from schemas import GuidelineSchema

        doc = GuidelineSchema.model_validate(self._minimal_doc())
        self.assertEqual(doc.life_stage, [])
        self.assertEqual(doc.applicable_regions, [])
        self.assertIsNone(doc.enrichment_version)
        self.assertEqual(doc.ai_generated_fields, [])

    def test_facets_and_provenance_round_trip(self):
        from schemas import GuidelineSchema

        payload = self._minimal_doc()
        payload.update(
            {
                "life_stage": ["early_childhood"],
                "age_min_months": 12,
                "age_max_months": 48,
                "setting": ["home"],
                "nutrients": ["iron"],
                "guideline_type": "food_based",
                "topic": ["protein"],
                "audience": ["caregiver"],
                "applicable_regions": ["IE"],
                "extractor_name": "guideline_extractor",
                "extractor_run_id": "run-1",
                "extraction_model": "gpt-5.4",
                "enrichment_version": 1,
                "enrichment_confidence": 0.8,
                "ai_generated_fields": ["life_stage", "setting"],
                "enhancements": [{"agent": "guideline-enricher", "run_id": "x"}],
            }
        )
        doc = GuidelineSchema.model_validate(payload)
        self.assertEqual(doc.life_stage, ["early_childhood"])
        self.assertEqual(doc.age_min_months, 12)

    def test_stored_doc_with_an_embedding_still_validates(self):
        """
        The schema is extra="forbid" and the embedding worker writes `embedding`
        and `embedded_at` straight onto the stored document. If the schema did
        not declare them, every read of an embedded guideline would fail.
        """
        from schemas import GuidelineSchema

        payload = self._minimal_doc()
        payload["embedding"] = [0.1] * 384
        payload["embedded_at"] = "2026-01-01T00:00:00"

        doc = GuidelineSchema.model_validate(payload)
        self.assertIsNotNone(doc.embedded_at)

    def test_embedding_vector_is_never_serialized(self):
        from schemas import GuidelineSchema

        payload = self._minimal_doc()
        payload["embedding"] = [0.1] * 384
        payload["embedded_at"] = "2026-01-01T00:00:00"

        dumped = GuidelineSchema.model_validate(payload).model_dump(mode="json")

        # 384 floats per rule would dominate every list response.
        self.assertNotIn("embedding", dumped)
        # embedded_at is small and is how backfill progress is checked.
        self.assertIn("embedded_at", dumped)

    def test_age_range_is_enforced(self):
        from schemas import GuidelineCreationSchema

        with self.assertRaises(ValueError):
            GuidelineCreationSchema.model_validate(
                {
                    "guide_urn": "urn:guide:test",
                    "rule_text": "Eat vegetables every day.",
                    "age_min_months": 48,
                    "age_max_months": 12,
                }
            )

    def test_update_schema_rejects_provenance_writes(self):
        from schemas import GuidelineUpdateSchema

        for field in (
            "extractor_name",
            "extractor_run_id",
            "extraction_model",
            "enrichment_version",
            "ai_generated_fields",
            "enhancements",
        ):
            with self.assertRaises(ValueError, msg=field):
                GuidelineUpdateSchema.model_validate({field: "x"})

    def test_update_schema_accepts_facet_edits(self):
        from schemas import GuidelineUpdateSchema

        update = GuidelineUpdateSchema.model_validate(
            {"life_stage": ["adolescence"], "setting": ["school"]}
        )
        self.assertEqual(update.life_stage, ["adolescence"])


class TestEnrichableFieldAllowlist(unittest.TestCase):
    def test_editorial_and_text_fields_are_not_enrichable(self):
        from schemas import GuidelineEnrichableField

        values = {field.value for field in GuidelineEnrichableField}
        for forbidden in ("rule_text", "status", "review_status", "visibility",
                          "verifier_user_id", "guide_urn", "sequence_no"):
            self.assertNotIn(forbidden, values)

    def test_facet_fields_are_enrichable(self):
        from schemas import GuidelineEnrichableField

        values = {field.value for field in GuidelineEnrichableField}
        for expected in ("life_stage", "setting", "nutrients", "guideline_type",
                         "topic", "audience", "applicable_regions",
                         "target_populations", "food_groups", "action_type"):
            self.assertIn(expected, values)


class TestEnrichmentRequestSchemas(unittest.TestCase):
    def test_batch_requires_items_and_caps_at_200(self):
        from schemas import GuidelineEnrichmentBatchSchema

        with self.assertRaises(ValueError):
            GuidelineEnrichmentBatchSchema.model_validate(
                {"agent": "guideline-enricher", "items": []}
            )

        items = [
            {"id": str(uuid.uuid4()), "fields": {"life_stage": ["adulthood"]}}
            for _ in range(201)
        ]
        with self.assertRaises(ValueError):
            GuidelineEnrichmentBatchSchema.model_validate(
                {"agent": "guideline-enricher", "items": items}
            )

    def test_unknown_field_keys_are_rejected(self):
        from schemas import GuidelineEnrichmentSchema

        with self.assertRaises(ValueError):
            GuidelineEnrichmentSchema.model_validate(
                {"agent": "guideline-enricher", "fields": {"rule_text": "hacked"}}
            )


class TestGuidelineEditorialPolicySchema(unittest.TestCase):
    def test_selection_is_required(self):
        from schemas import GuidelineEditorialPolicySchema

        with self.assertRaises(ValueError):
            GuidelineEditorialPolicySchema.model_validate({"status": "active"})

    def test_a_change_is_required(self):
        from schemas import GuidelineEditorialPolicySchema

        with self.assertRaises(ValueError):
            GuidelineEditorialPolicySchema.model_validate(
                {"fq": ['guide_urn:"urn:guide:test"']}
            )

    def test_activation_by_guide_is_valid(self):
        from schemas import GuidelineEditorialPolicySchema

        spec = GuidelineEditorialPolicySchema.model_validate(
            {
                "fq": ['guide_urn:"urn:guide:test"', "review_status:verified"],
                "status": "active",
                "dry_run": True,
            }
        )
        self.assertEqual(spec.status, "active")
        self.assertTrue(spec.dry_run)


if __name__ == "__main__":
    unittest.main()
