"""
Guideline Entity
----------------
Dependent guideline records belong to a parent guide and are addressed by UUID.
They do not own artifacts directly; any source references must point to artifacts
already attached to the parent guide.
"""

import re
import threading
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

import logging

from backend.elastic import ELASTIC_CLIENT
from backend.embedding_queue import EMBEDDING_QUEUE
from backend.redis import REDIS
from catalog_access import (
    apply_catalog_visibility_filter,
    can_view_unapproved_catalog,
    is_approved_or_active,
    retain_human_edited_fields,
    select_enrichable_updates,
)
from entity import DependentEntity
from entities.artifacts import ARTIFACT
from exceptions import ConflictError, DataError, InternalError, NotFoundError
from schemas import (
    GuidelineBulkImportSchema,
    GuidelineCreationSchema,
    GuidelineEditorialPolicySchema,
    GuidelineEnrichmentBatchSchema,
    GuidelineEnrichmentSchema,
    GuidelineSchema,
    GuidelineUpdateSchema,
    SearchSchema,
    validate_editorial_state,
)
from main import config

logger = logging.getLogger(__name__)

# Facet fields that contribute to a guideline's embedding text; changing any of
# them invalidates the stored vector.
_GUIDELINE_FACET_FIELDS = (
    "life_stage",
    "setting",
    "target_populations",
    "food_groups",
    "nutrients",
    "health_conditions",
    "topic",
    "audience",
    "guideline_type",
)


class Guideline(DependentEntity):
    LOCKED_TEXT_FIELDS = {"rule_text"}
    DEFAULT_ACTION_TYPE = "do"
    ACTION_TYPE_PREFIXES = {
        "eat": "eat",
        "consume": "eat",
        "include": "eat",
        "drink": "drink",
        "use": "use",
        "do": "do",
        "follow": "do",
        "avoid": "avoid",
        "prevent": "avoid",
        "prepare": "prepare",
        "cook": "prepare",
        "limit": "limit",
        "restrict": "limit",
        "choose": "choose",
        "select": "choose",
        "increase": "increase",
        "boost": "increase",
        "reduce": "reduce",
        "decrease": "reduce",
        "lower": "reduce",
    }

    def __init__(self):
        super().__init__(
            "guideline",
            "guidelines",
            GuidelineSchema,
            GuidelineCreationSchema,
            GuidelineUpdateSchema,
            parent_field="guide_urn",
        )

    @staticmethod
    def _strip_search_metadata(obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Drop the embedding vector before schema validation.

        Every read path validates the stored document, and a guideline search
        can return a hundred rows; parsing 384 floats per row into Python only
        to exclude them from the response is pure waste. The schema still
        declares the field, so any path that bypasses this stays valid.
        """
        cleaned = DependentEntity._strip_search_metadata(obj)
        cleaned.pop("embedding", None)
        return cleaned

    @staticmethod
    def _resolve_actor_id(actor: dict | None) -> str | None:
        if not actor:
            return None
        return actor.get("sub") or actor.get("id") or actor.get("preferred_username")

    def _apply_verifier_metadata(
        self,
        guideline_dict: Dict[str, Any],
        actor: dict | None,
        *,
        review_status_explicit: bool,
        current_verifier_user_id: str | None = None,
    ) -> Dict[str, Any]:
        if guideline_dict.get("review_status") == "verified" and (
            review_status_explicit or not current_verifier_user_id
        ):
            verifier_user_id = self._resolve_actor_id(actor)
            if not verifier_user_id:
                raise DataError(
                    "A verifier user ID is required when setting review_status='verified'."
                )
            guideline_dict["verifier_user_id"] = verifier_user_id
        elif review_status_explicit and guideline_dict.get("review_status") != "verified":
            guideline_dict["verifier_user_id"] = None
        elif current_verifier_user_id is not None:
            guideline_dict["verifier_user_id"] = current_verifier_user_id

        return guideline_dict

    def _ensure_parent_guide_allows_guideline_state(
        self, guide: Dict[str, Any], guideline_dict: Dict[str, Any]
    ) -> None:
        if guide.get("status") == "active" and (
            guideline_dict.get("status") != "active"
            or guideline_dict.get("review_status") != "verified"
            or not guideline_dict.get("verifier_user_id")
        ):
            raise ConflictError(
                "Guidelines under an active guide must be active and verified."
            )

        if (
            guide.get("status") == "active"
            and guide.get("visibility") == "public"
            and guideline_dict.get("visibility") != "public"
        ):
            raise ConflictError(
                "Guidelines under a public guide must also be public."
            )

    def _ensure_text_editable(
        self, current: Dict[str, Any], guide: Dict[str, Any], update_dict: Dict[str, Any]
    ) -> None:
        if not self.LOCKED_TEXT_FIELDS.intersection(update_dict.keys()):
            return

        guide_is_published = (
            guide.get("status") == "active" and guide.get("visibility") == "public"
        )
        if current.get("status") == "active" and guide_is_published:
            raise ConflictError(
                "Guideline text cannot be patched while the parent guide is published. "
                "Unpublish the guide first."
            )

    def _ensure_parent_guide_not_published_for_deletion(
        self, guide: Dict[str, Any]
    ) -> None:
        guide_is_published = (
            guide.get("status") == "active" and guide.get("visibility") == "public"
        )
        if guide_is_published:
            raise ConflictError(
                "Guidelines cannot be deleted while the parent guide is published. "
                "Unpublish the guide first."
            )

    @staticmethod
    def _viewer_can_access_all(
        viewer: Dict[str, Any] | None, *, include_unapproved: bool = False
    ) -> bool:
        """Allow unrestricted reads only for privileged viewers or explicit internal bypasses."""
        return include_unapproved or can_view_unapproved_catalog(viewer)

    def _ensure_visible_to_viewer(
        self,
        guideline_dict: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> None:
        """Raise not found when a caller requests a hidden guideline directly."""
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) or is_approved_or_active(guideline_dict):
            return
        raise NotFoundError(f"Guideline with ID {guideline_dict['id']} not found.")

    def _apply_viewer_filter(
        self,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        """Constrain guideline search-style queries for non-privileged viewers."""
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ):
            return query
        return apply_catalog_visibility_filter(query, exclude_deleted=True)

    def get(
        self,
        id_: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a single guideline and enforce read visibility before returning it."""
        entity = self.get_cached(id_)
        self._ensure_visible_to_viewer(
            entity, viewer, include_unapproved=include_unapproved
        )
        return entity

    def get_cached(self, identifier: str) -> Dict[str, Any]:
        id_ = self.get_identifier(identifier)
        obj = None

        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(id_)
            except Exception as e:
                logger.error(f"Failed to get cached guideline {id_}: {e}")

        if obj is None:
            obj = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=id_)
            if obj is None:
                raise NotFoundError(f"Guideline with ID {id_} not found.")
            self.cache(id_, obj)

        return self.dump_schema.model_validate(
            self._strip_search_metadata(obj)
        ).model_dump(mode="json")

    def _get_guide(self, guide_urn: str) -> Dict[str, Any]:
        guide = ELASTIC_CLIENT.get_entity(index_name="guides", urn=guide_urn)
        if guide is None:
            raise NotFoundError(f"Guide with URN {guide_urn} not found.")
        return guide

    def _validate_sequence_no(
        self, guide_urn: str, sequence_no: int, exclude_id: Optional[str] = None
    ) -> None:
        qspec = SearchSchema.model_validate(
            {
                "limit": 10,
                "offset": 0,
                "fq": [
                    f'guide_urn:"{guide_urn}"',
                    f"sequence_no:{sequence_no}",
                    "NOT status:deleted",
                ],
            }
        )
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )

        for hit in response["results"]:
            if exclude_id and hit.get("id") == exclude_id:
                continue
            raise ConflictError(
                f"Guide {guide_urn} already has a guideline with sequence_no {sequence_no}."
            )

    def _next_sequence_no(self, guide_urn: str) -> int:
        qspec = SearchSchema.model_validate(
            {
                "limit": 1,
                "offset": 0,
                "fq": [f'guide_urn:"{guide_urn}"', "NOT status:deleted"],
                "sort": "sequence_no desc",
            }
        )
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )
        results = response.get("results", [])
        if not results:
            return 1
        return int(results[0].get("sequence_no", 0)) + 1

    def _default_title(self, rule_text: str) -> str:
        return rule_text[:2000]

    def _infer_action_type(self, rule_text: str) -> str:
        for token in re.findall(r"[a-z]+", rule_text.lower()):
            action_type = self.ACTION_TYPE_PREFIXES.get(token)
            if action_type:
                return action_type
        return self.DEFAULT_ACTION_TYPE

    def _apply_creation_defaults(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        hydrated = dict(spec)
        rule_text = hydrated.get("rule_text")
        guide_urn = hydrated.get("guide_urn")

        if rule_text and not hydrated.get("title"):
            hydrated["title"] = self._default_title(rule_text)

        if hydrated.get("sequence_no") is None and guide_urn:
            hydrated["sequence_no"] = self._next_sequence_no(guide_urn)

        if hydrated.get("action_type") is None and rule_text:
            hydrated["action_type"] = self._infer_action_type(rule_text)

        return hydrated

    def _guide_artifact_ids(self, guide_urn: str) -> set:
        """The artifact IDs attached to a guide, as one lookup."""
        artifacts = ARTIFACT.fetch(parent_urn=guide_urn, include_unapproved=True)
        return {str(artifact["id"]) for artifact in artifacts}

    def _normalize_source_refs(
        self,
        guide_urn: str,
        source_refs: List[Dict[str, Any]],
        artifact_ids: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """
        Validate page references against the guide's artifacts.

        ``artifact_ids`` lets a bulk caller resolve the guide's artifacts once
        and reuse them; resolving per item turned a 1000-rule import into 1000
        extra searches.
        """
        if not source_refs:
            return []

        if artifact_ids is None:
            artifact_ids = self._guide_artifact_ids(guide_urn)
        if not artifact_ids:
            raise DataError(
                "source_refs require at least one artifact attached to the parent guide."
            )

        default_artifact_id = next(iter(artifact_ids)) if len(artifact_ids) == 1 else None

        normalized_refs: List[Dict[str, Any]] = []
        for ref in source_refs:
            ref_dict = dict(ref)
            artifact_id = ref_dict.get("artifact_id")

            if artifact_id is None and default_artifact_id is not None:
                ref_dict["artifact_id"] = default_artifact_id
                artifact_id = default_artifact_id

            if artifact_id is None and len(artifact_ids) > 1:
                raise DataError(
                    "artifact_id is required in source_refs when the parent guide has multiple artifacts."
                )

            if artifact_id is not None and str(artifact_id) not in artifact_ids:
                raise DataError(
                    f"Artifact {artifact_id} is not attached to guide {guide_urn}."
                )

            normalized_refs.append(ref_dict)

        return normalized_refs

    def create(self, spec, creator: dict) -> str:
        spec = self._apply_creation_defaults(spec)

        try:
            guideline_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating guideline: {e}")

        guideline_dict = guideline_data.model_dump(mode="json")
        guide = self._get_guide(guideline_dict["guide_urn"])

        self._validate_sequence_no(
            guideline_dict["guide_urn"], guideline_dict["sequence_no"]
        )
        guideline_dict["source_refs"] = self._normalize_source_refs(
            guideline_dict["guide_urn"], guideline_dict.get("source_refs", [])
        )
        guideline_dict["guide_region"] = guide.get("region")
        if not guideline_dict.get("applicable_regions") and guide.get("region"):
            guideline_dict["applicable_regions"] = [guide.get("region")]
        guideline_dict = self._apply_verifier_metadata(
            guideline_dict, creator, review_status_explicit=True
        )
        validate_editorial_state(guideline_dict)
        self._ensure_parent_guide_allows_guideline_state(guide, guideline_dict)

        guideline_dict["creator"] = creator["preferred_username"]
        guideline_dict = self.upsert_system_fields(guideline_dict, update=False)

        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=guideline_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create guideline: {e}")

        self.enqueue_embedding(guideline_dict["id"], guideline_dict)
        return guideline_dict["id"]

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        identifier = self.create(spec, creator)
        return self.get(identifier, viewer=creator, include_unapproved=True)

    def patch_entity_with_actor(self, id_: str, spec: Dict[str, Any], actor: dict):
        identifier = self.get_identifier(id_)
        self.patch(identifier, spec, actor=actor)
        self.invalidate_cache(identifier)
        return self.get(identifier, viewer=actor, include_unapproved=True)

    def patch(self, id_: str, spec, actor: dict | None = None) -> None:
        try:
            guideline_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating guideline: {e}")

        current = self.get_cached(id_)
        update_dict = guideline_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )

        guide = self._get_guide(current["guide_urn"])
        self._ensure_text_editable(current, guide, update_dict)

        merged = {**current, **update_dict}
        merged["guide_urn"] = current["guide_urn"]
        merged["guide_region"] = guide.get("region")
        merged["source_refs"] = self._normalize_source_refs(
            current["guide_urn"], merged.get("source_refs", [])
        )
        merged = self._apply_verifier_metadata(
            merged,
            actor,
            review_status_explicit="review_status" in update_dict,
            current_verifier_user_id=current.get("verifier_user_id"),
        )

        self._validate_sequence_no(
            current["guide_urn"], merged["sequence_no"], exclude_id=id_
        )
        validate_editorial_state(merged)
        self._ensure_parent_guide_allows_guideline_state(guide, merged)

        update_dict["guide_region"] = merged["guide_region"]
        if "verifier_user_id" in merged:
            update_dict["verifier_user_id"] = merged.get("verifier_user_id")
        if "source_refs" in update_dict or current.get("source_refs"):
            update_dict["source_refs"] = merged["source_refs"]

        # A human edit of a machine-written field takes ownership of it, so
        # later enrichment passes will not overwrite the editor's value.
        current_ai_fields = current.get("ai_generated_fields") or []
        if any(field in update_dict for field in current_ai_fields):
            update_dict["ai_generated_fields"] = retain_human_edited_fields(
                current_ai_fields, update_dict.keys()
            )

        update_dict = self.upsert_system_fields(update_dict, update=True)
        update_dict["id"] = id_

        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=update_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update guideline: {e}")

        self.invalidate_cache(id_)

        if any(
            field in update_dict
            for field in ("rule_text", "title", "notes", *_GUIDELINE_FACET_FIELDS)
        ):
            self.enqueue_embedding(id_)

    def delete(self, id_: str) -> bool:
        current = self.get(id_, include_unapproved=True)
        guide = self._get_guide(current["guide_urn"])
        self._ensure_parent_guide_not_published_for_deletion(guide)
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=id_)
        except Exception as e:
            raise InternalError(f"Failed to delete guideline: {e}")

        return {"deleted": id_}

    def bulk_import_for_guide(
        self, guide_urn: str, spec: Dict[str, Any], creator: dict
    ) -> Dict[str, Any]:
        try:
            import_data = GuidelineBulkImportSchema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for bulk importing guidelines: {e}")

        guide = self._get_guide(guide_urn)
        guide_region = guide.get("region")
        creator_username = creator.get("preferred_username")

        # Fetch current max sequence_no once to assign contiguous numbers
        next_seq = self._next_sequence_no(guide_urn)

        # Resolved once for the whole batch. Both of these were previously
        # recomputed per item, which made a 1000-rule import issue 1000 extra
        # searches for the guide's artifacts and 1000 extra gets for the guide.
        artifact_ids = self._guide_artifact_ids(guide_urn)
        guide_title = guide.get("title") or guide.get("short_title")

        documents: List[Dict[str, Any]] = []
        used_sequence_nos: set = set()

        for item in import_data.guidelines:
            guideline_dict = item.model_dump(mode="json")
            guideline_dict["guide_urn"] = guide_urn
            guideline_dict["guide_region"] = guide_region
            if not guideline_dict.get("applicable_regions") and guide_region:
                guideline_dict["applicable_regions"] = [guide_region]

            if guideline_dict.get("title") is None:
                guideline_dict["title"] = self._default_title(guideline_dict["rule_text"])

            if guideline_dict.get("action_type") is None:
                guideline_dict["action_type"] = self._infer_action_type(guideline_dict["rule_text"])

            if guideline_dict.get("sequence_no") is None:
                guideline_dict["sequence_no"] = next_seq
                next_seq += 1
            elif guideline_dict["sequence_no"] in used_sequence_nos:
                raise DataError(
                    f"Duplicate sequence_no {guideline_dict['sequence_no']} within the import batch."
                )

            used_sequence_nos.add(guideline_dict["sequence_no"])

            guideline_dict["source_refs"] = self._normalize_source_refs(
                guide_urn, guideline_dict.get("source_refs") or [], artifact_ids
            )
            guideline_dict = self._apply_verifier_metadata(
                guideline_dict, creator, review_status_explicit=True
            )
            validate_editorial_state(guideline_dict)
            self._ensure_parent_guide_allows_guideline_state(guide, guideline_dict)

            guideline_dict["creator"] = creator_username
            guideline_dict = self.upsert_system_fields(guideline_dict, update=False)
            documents.append(guideline_dict)

        if documents:
            try:
                ELASTIC_CLIENT.bulk_index(
                    index_name=self.collection_name,
                    documents=documents,
                    id_field="id",
                )
            except Exception as e:
                raise InternalError(f"Failed to bulk index guidelines: {e}")

            # Queued with the guide title already in hand, so embedding a batch
            # does not re-read the parent guide once per rule.
            for document in documents:
                self.enqueue_embedding(
                    document["id"], document, guide_title=guide_title
                )

        return {
            "guide_urn": guide_urn,
            "imported_count": len(documents),
        }

    # ------------------------------------------------------------------ #
    # Semantic embedding
    # ------------------------------------------------------------------ #

    def _embedding_text(
        self, guideline: Dict[str, Any], guide_title: Optional[str] = None
    ) -> str:
        """
        The text a guideline is embedded from.

        A rule sentence alone is short and often context-free — "Provide
        portions of red meat twice a week" says nothing about who it is for.
        Appending the guide title and the facet labels gives the vector the
        context the sentence lacks, which is the whole reason those facets were
        derived in the first place.
        """
        parts: List[str] = [guideline.get("rule_text") or ""]

        title = guideline.get("title")
        if title and title != guideline.get("rule_text"):
            parts.append(title)

        # A caller embedding a whole guide passes the title in; only a one-off
        # embed pays for the lookup.
        if guide_title is None and guideline.get("guide_urn"):
            try:
                guide = self._get_guide(guideline["guide_urn"])
                guide_title = guide.get("title") or guide.get("short_title")
            except NotFoundError:
                guide_title = None
        if guide_title:
            parts.append(f"From: {guide_title}")

        for field in (
            "life_stage",
            "setting",
            "target_populations",
            "food_groups",
            "nutrients",
            "health_conditions",
            "topic",
            "audience",
        ):
            values = guideline.get(field) or []
            if values:
                readable = ", ".join(str(value).replace("_", " ") for value in values)
                parts.append(f"{field.replace('_', ' ')}: {readable}")

        guideline_type = guideline.get("guideline_type")
        if guideline_type:
            parts.append(f"type: {str(guideline_type).replace('_', ' ')}")

        return "\n".join(part for part in parts if part).strip()

    def embed(
        self,
        id_: str,
        spec: Dict[str, Any] | None = None,
        creator=None,
        guide_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build an embedding job for a guideline."""
        identifier = self.get_identifier(id_)
        guideline = spec or self.get_cached(identifier)

        text = self._embedding_text(guideline, guide_title)
        if not text:
            raise DataError("No guideline text available for embedding.")

        return {
            "job_id": str(uuid.uuid4()),
            "job_type": "entity_embedding",
            "entity": self.name,
            "urn": identifier,
            "identifier_field": "id",
            "index_name": self.collection_name,
            "vector_field": "embedding",
            "text": text,
            "metadata": {
                "source": "guideline.embed",
                "requested_by": creator.get("preferred_username") if creator else None,
            },
        }

    def enqueue_embedding(
        self,
        id_: str,
        guideline: Dict[str, Any] | None = None,
        guide_title: Optional[str] = None,
    ) -> None:
        """
        Queue a guideline for embedding, without letting a failure break the write.

        Embedding is an enhancement to retrieval, never a precondition for
        storing a rule, so a queue outage degrades search quality rather than
        rejecting the write.
        """
        try:
            EMBEDDING_QUEUE.enqueue(self.embed(id_, guideline, guide_title=guide_title))
        except Exception:
            logger.warning(
                "Could not queue guideline %s for embedding", id_, exc_info=True
            )

    # A guide's rules, bounded well above any real guide so a runaway cannot
    # rewrite the corpus from a single region edit.
    PARENT_SYNC_MAX_DOCS = 50000

    EMBEDDING_BACKFILL_MAX_DOCS = 10000
    # Scanning is bounded separately from queueing: a corpus that is almost
    # fully embedded is mostly skips, and the loop must still terminate.
    EMBEDDING_BACKFILL_MAX_SCAN = 200000

    def backfill_embeddings(
        self,
        *,
        guide_urn: Optional[str] = None,
        only_missing: bool = True,
        max_docs: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Queue existing guidelines for embedding.

        The stored corpus predates guideline embeddings entirely, so every rule
        needs one queued once. ``only_missing`` skips rules that already have a
        vector, which makes the backfill resumable after an interruption.
        """
        # The scan deliberately does NOT filter on `embedded_at`, even though
        # that is what we are looking for. The embedding worker sets that field
        # asynchronously, so filtering on it would make the result set shift
        # under the paging cursor mid-run: pages would be skipped, or — if the
        # cursor were reset to compensate — the same unprocessed documents would
        # be re-queued indefinitely. Scanning a stable set and skipping
        # already-embedded documents in Python keeps the run deterministic.
        fq = ["NOT status:deleted"]
        if guide_urn:
            fq.append(f'guide_urn:"{guide_urn}"')

        limit = min(
            int(max_docs or self.EMBEDDING_BACKFILL_MAX_DOCS),
            self.EMBEDDING_BACKFILL_MAX_DOCS,
        )

        queued = 0
        failed = 0
        skipped = 0
        scanned = 0
        offset = 0
        page_size = 500
        seen: set[str] = set()

        while queued + failed < limit and scanned < self.EMBEDDING_BACKFILL_MAX_SCAN:
            qspec = SearchSchema.model_validate(
                {
                    "limit": page_size,
                    "offset": offset,
                    "fq": list(fq),
                    # A stable, unique sort key: sequence_no repeats across
                    # guides, and ties make offset paging non-deterministic.
                    "sort": "id asc",
                }
            )
            try:
                response = ELASTIC_CLIENT.search_entities(
                    index_name=self.collection_name, qspec=qspec
                )
            except Exception as e:
                raise InternalError(f"Failed to scan guidelines for embedding: {e}")

            results = response.get("results", [])
            if not results:
                break

            scanned += len(results)

            for guideline in results:
                if queued + failed >= limit:
                    break
                guideline = self._strip_search_metadata(guideline)
                identifier = guideline.get("id")
                if not identifier or identifier in seen:
                    continue
                seen.add(identifier)

                if only_missing and guideline.get("embedded_at"):
                    skipped += 1
                    continue
                if dry_run:
                    queued += 1
                    continue
                try:
                    EMBEDDING_QUEUE.enqueue(self.embed(identifier, guideline))
                    queued += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Could not queue guideline %s for embedding",
                        identifier,
                        exc_info=True,
                    )

            if len(results) < page_size:
                break
            offset += len(results)

        return {
            "dry_run": dry_run,
            "guide_urn": guide_urn,
            "only_missing": only_missing,
            "queued": queued,
            "failed": failed,
            "skipped_already_embedded": skipped,
            "scanned": scanned,
            "max_docs": limit,
        }

    # ------------------------------------------------------------------ #
    # Machine enrichment (facets written post-extraction)
    # ------------------------------------------------------------------ #

    def _prepare_enrichment(
        self,
        current: Dict[str, Any],
        fields: Dict[str, Any],
        force_fields: List[str] | None,
    ) -> tuple[Dict[str, Any], List[str]]:
        """Apply the no-clobber guard and validate the resulting facet values."""
        if current.get("status") == "deleted":
            raise ConflictError("Cannot enrich a deleted guideline.")

        normalized = {
            str(getattr(key, "value", key)): value for key, value in fields.items()
        }
        writable, skipped = select_enrichable_updates(
            current, normalized, force_fields
        )

        facet_values = {
            key: value
            for key, value in writable.items()
            if key not in ("enrichment_version", "enrichment_confidence")
        }
        if facet_values:
            try:
                GuidelineUpdateSchema.model_validate(facet_values)
            except Exception as e:
                raise DataError(f"Invalid enrichment values: {e}")

        return writable, skipped

    def enrich(
        self,
        id_: str,
        spec: GuidelineEnrichmentSchema,
        enricher: dict | None = None,
    ) -> Dict[str, Any]:
        """
        Write machine-derived facets onto a guideline.

        Only fields that are empty or previously machine-written are updated
        (unless explicitly forced), so re-runs never overwrite human edits.
        Every pass appends an ``enhancements[]`` audit event.
        """
        identifier = self.get_identifier(id_)
        current = self.get_cached(identifier)

        writable, skipped = self._prepare_enrichment(
            current, spec.fields, list(spec.force_fields or [])
        )

        run_id = str(uuid.uuid4())
        enrichment_event = {
            "agent": spec.agent,
            "run_id": run_id,
            "enhanced_at": datetime.now().isoformat(),
            "fields": list(writable.keys()),
            "skipped_fields": skipped,
            "before": {key: current.get(key) for key in writable},
            "after": dict(writable),
        }

        try:
            ELASTIC_CLIENT.enhance_entity(
                index_name=self.collection_name,
                urn=identifier,
                fields=writable,
                enhancement_event=enrichment_event,
            )
        except Exception as e:
            raise InternalError(f"Failed to enrich guideline {identifier}: {e}")

        self.invalidate_cache(identifier)

        # The facets just written are part of what a guideline is embedded from,
        # so a newly-enriched rule needs a fresh vector to be findable by them.
        facet_fields = {
            key for key in writable
            if key not in ("enrichment_version", "enrichment_confidence")
        }
        if facet_fields:
            self.enqueue_embedding(identifier)

        return {
            "id": identifier,
            "run_id": run_id,
            "agent": spec.agent,
            "enriched_fields": [
                key for key in writable if key not in ("enrichment_version", "enrichment_confidence")
            ],
            "skipped_fields": skipped,
        }

    def enrich_batch(
        self,
        spec: GuidelineEnrichmentBatchSchema,
        enricher: dict | None = None,
    ) -> Dict[str, Any]:
        """Enrich up to 200 guidelines in one call, reporting per-item outcomes."""
        results: List[Dict[str, Any]] = []
        enriched = 0
        failed = 0

        for item in spec.items:
            item_id = str(item.id)
            try:
                if spec.dry_run:
                    current = self.get_cached(item_id)
                    writable, skipped = self._prepare_enrichment(
                        current, item.fields, list(item.force_fields or [])
                    )
                    results.append(
                        {
                            "id": item_id,
                            "ok": True,
                            "dry_run": True,
                            "would_enrich_fields": [
                                key
                                for key in writable
                                if key not in ("enrichment_version", "enrichment_confidence")
                            ],
                            "skipped_fields": skipped,
                        }
                    )
                else:
                    outcome = self.enrich(
                        item_id,
                        GuidelineEnrichmentSchema.model_validate(
                            {
                                "agent": spec.agent,
                                "fields": item.fields,
                                "force_fields": item.force_fields,
                            }
                        ),
                        enricher=enricher,
                    )
                    outcome["ok"] = True
                    results.append(outcome)
                enriched += 1
            except (DataError, ConflictError, NotFoundError) as e:
                failed += 1
                results.append({"id": item_id, "ok": False, "error": str(e)})

        return {
            "dry_run": spec.dry_run,
            "agent": spec.agent,
            "total": len(spec.items),
            "succeeded": enriched,
            "failed": failed,
            "results": results,
        }

    # ------------------------------------------------------------------ #
    # Editorial policy (bulk lifecycle edits, e.g. corpus activation)
    # ------------------------------------------------------------------ #

    # A console click must not be able to rewrite the whole corpus by accident.
    POLICY_MAX_DOCS = 10000
    POLICY_PREVIEW_SIZE = 25

    def _policy_query(
        self,
        *,
        ids: Optional[List[str]] = None,
        q: Optional[str] = None,
        fq: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build the selection query for a batch policy edit (mirrors /guidelines/search)."""
        must: List[Dict[str, Any]] = []
        filters: List[Dict[str, Any]] = [
            {"bool": {"must_not": {"term": {"status": "deleted"}}}}
        ]

        if ids:
            filters.append({"terms": {"id": [str(item) for item in ids]}})
        if q and q.strip():
            must.append(
                {"multi_match": {"query": q.strip(), "fields": ["*"], "operator": "and"}}
            )
        for clause in fq or []:
            if isinstance(clause, str) and clause.strip():
                filters.append({"query_string": {"query": clause.strip()}})

        return {"bool": {"must": must, "filter": filters}}

    def set_editorial_policy(
        self,
        spec: GuidelineEditorialPolicySchema,
        updater: dict | None = None,
    ) -> Dict[str, Any]:
        """
        Bulk-edit lifecycle/editorial state on every matching guideline.

        The tool behind corpus activation: with retrieval gated on
        ``status:active``, this is how a reviewed guide's rules go live in one
        pass. ``dry_run`` reports the match count plus a sample and writes
        nothing — always preview a query-driven edit first.
        """
        changes = {
            "status": spec.status,
            "review_status": spec.review_status,
            "visibility": spec.visibility,
            "applicability_status": spec.applicability_status,
        }
        changes = {key: value for key, value in changes.items() if value is not None}

        # The requested combination must itself be editorially coherent
        # (e.g. visibility=public requires review_status=verified).
        validate_editorial_state(changes, partial=True)

        verifier_user_id = None
        if changes.get("review_status") == "verified":
            verifier_user_id = self._resolve_actor_id(updater)
            if not verifier_user_id:
                raise DataError(
                    "A verifier user ID is required when setting review_status='verified'."
                )

        query = self._policy_query(
            ids=[str(item) for item in spec.ids or []],
            q=spec.q,
            fq=spec.fq,
        )

        try:
            matched = ELASTIC_CLIENT.count_by_query(
                index_name=self.collection_name, query=query
            )
        except Exception as e:
            raise InternalError(f"Failed to count matching guidelines: {e}")

        limit = min(int(spec.max_docs or self.POLICY_MAX_DOCS), self.POLICY_MAX_DOCS)

        affected: List[Dict[str, Any]] = []
        if matched:
            try:
                affected = ELASTIC_CLIENT.search_documents(
                    index_name=self.collection_name,
                    query=query,
                    size=min(matched, limit),
                    source_includes=[
                        "id",
                        "guide_urn",
                        "title",
                        "status",
                        "review_status",
                        "visibility",
                        "applicability_status",
                    ],
                )
            except Exception:
                logger.warning("Could not read guidelines for policy edit", exc_info=True)

        preview = affected[: self.POLICY_PREVIEW_SIZE]

        if spec.dry_run:
            return {
                "dry_run": True,
                "matched": matched,
                "updated": 0,
                "capped": matched > limit,
                "max_docs": limit,
                "changes": changes,
                "sample": preview,
            }

        assignments: List[str] = ["ctx._source.updated_at = params.now"]
        params: Dict[str, Any] = {"now": datetime.now().isoformat()}

        for field, value in changes.items():
            assignments.append(f"ctx._source.{field} = params.{field}")
            params[field] = value

        if verifier_user_id is not None:
            assignments.append("ctx._source.verifier_user_id = params.verifier_user_id")
            params["verifier_user_id"] = verifier_user_id
        elif changes.get("review_status") is not None:
            # Any non-verified review status clears the previous verifier.
            assignments.append("ctx._source.verifier_user_id = null")

        try:
            result = ELASTIC_CLIENT.update_by_query(
                index_name=self.collection_name,
                query=query,
                script_source="; ".join(assignments),
                params=params,
                max_docs=limit,
            )
        except Exception as e:
            raise InternalError(f"Failed to apply guideline editorial policy: {e}")

        for doc in affected:
            doc_id = doc.get("id")
            if doc_id:
                self.invalidate_cache(doc_id)
        for item in spec.ids or []:
            self.invalidate_cache(str(item))

        logger.info(
            "Guideline editorial policy applied by %s: matched=%s updated=%s changes=%s",
            self._resolve_actor_id(updater),
            matched,
            result.get("updated"),
            changes,
        )

        return {
            "dry_run": False,
            "matched": matched,
            "updated": result.get("updated", 0),
            "capped": matched > limit,
            "max_docs": limit,
            "changes": changes,
            "version_conflicts": result.get("version_conflicts", 0),
            "failures": result.get("failures", []),
            "sample": preview,
        }

    def delete_for_guide(self, guide_urn: str) -> None:
        """Bulk-delete all guidelines for a guide in a single delete_by_query call."""
        try:
            ELASTIC_CLIENT.delete_by_query(
                index_name=self.collection_name,
                query={"term": {"guide_urn": guide_urn}},
            )
        except Exception as e:
            raise InternalError(f"Failed to bulk-delete guidelines for guide {guide_urn}: {e}")

    def fetch_for_guide(
        self,
        guide_urn: str,
        limit: int = 1000,
        offset: int = 0,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch visible guidelines for a guide, hiding the whole set if the guide is hidden."""
        response = self.search_for_guide(
            guide_urn=guide_urn,
            query={
                "limit": limit,
                "offset": offset,
                "sort": "sequence_no asc",
            },
            viewer=viewer,
            include_unapproved=include_unapproved,
        )
        return response["results"]

    def search_for_guide(
        self,
        guide_urn: str,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        """Search guidelines scoped to a single guide with pagination, filters, and facets."""
        guide = self._get_guide(guide_urn)
        if not self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) and not is_approved_or_active(guide):
            raise NotFoundError(f"Guide with URN {guide_urn} not found.")

        scoped_query = dict(query)
        fq = [f'guide_urn:"{guide_urn}"', *(scoped_query.get("fq") or [])]
        if "NOT status:deleted" not in fq:
            fq.append("NOT status:deleted")
        scoped_query["fq"] = fq
        scoped_query.setdefault("sort", "sequence_no asc")

        response = super().search(
            query=self._apply_viewer_filter(
                scoped_query,
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        response["results"] = [
            self.dump_schema.model_validate(
                self._strip_search_metadata(guideline)
            ).model_dump(mode="json")
            for guideline in response.get("results", [])
        ]
        return response

    def list(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[str]:
        """List visible guideline UUIDs for the current viewer."""
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ):
            return super().list(limit=limit, offset=offset)

        response = super().search(
            query=self._apply_viewer_filter(
                {
                    "limit": limit or 100,
                    "offset": offset or 0,
                    "fl": ["id"],
                },
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self._strip_search_metadata(guideline)["id"]
            for guideline in response.get("results", [])
            if "id" in self._strip_search_metadata(guideline)
        ]

    def fetch(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch guidelines while enforcing public visibility for non-privileged viewers."""
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ):
            return super().fetch(limit=limit, offset=offset)

        response = super().search(
            query=self._apply_viewer_filter(
                {"limit": limit or 100, "offset": offset or 0},
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self.dump_schema.model_validate(
                self._strip_search_metadata(guideline)
            ).model_dump(mode="json")
            for guideline in response.get("results", [])
        ]

    def search(
        self,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        """Search guidelines and return only the rows visible to the caller."""
        response = super().search(
            query=self._apply_viewer_filter(
                query, viewer, include_unapproved=include_unapproved
            )
        )
        response["results"] = [
            self.dump_schema.model_validate(
                self._strip_search_metadata(guideline)
            ).model_dump(mode="json")
            for guideline in response.get("results", [])
        ]
        return response

    def list_ids_for_guide(
        self,
        guide_urn: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[str]:
        """Return visible guideline IDs for guide hydration and related UI flows."""
        guide = self._get_guide(guide_urn)
        if not self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) and not is_approved_or_active(guide):
            raise NotFoundError(f"Guide with URN {guide_urn} not found.")

        qspec = SearchSchema.model_validate(
            self._apply_viewer_filter(
                {
                    "limit": 1000,
                    "offset": 0,
                    "fl": ["id"],
                    "fq": [f'guide_urn:"{guide_urn}"', "NOT status:deleted"],
                    "sort": "sequence_no asc",
                },
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )
        return [
            self._strip_search_metadata(item)["id"]
            for item in response.get("results", [])
            if "id" in self._strip_search_metadata(item)
        ]

    def has_guidelines_for_guide(self, guide_urn: str) -> bool:
        """Check for linked guidelines without applying public visibility restrictions."""
        return bool(self.list_ids_for_guide(guide_urn, include_unapproved=True))

    def has_non_publishable_for_guide(
        self, guide_urn: str, *, require_public_visibility: bool = False
    ) -> bool:
        """Return True when a linked guideline blocks the parent guide from being published."""
        publishable_clause = (
            "status:active AND review_status:verified AND _exists_:verifier_user_id"
        )
        if require_public_visibility:
            publishable_clause = f"{publishable_clause} AND visibility:public"

        qspec = SearchSchema.model_validate(
            {
                "limit": 1,
                "offset": 0,
                "fl": ["id"],
                "fq": [
                    f'guide_urn:"{guide_urn}"',
                    "NOT status:deleted",
                    f"NOT ({publishable_clause})",
                ],
            }
        )
        response = ELASTIC_CLIENT.search_entities(
            index_name=self.collection_name, qspec=qspec
        )
        return bool(response.get("results"))

    def _sync_parent_metadata_worker(self, guide_urn: str) -> None:
        """
        Push a guide's region down onto its rules.

        Done as two scripted update-by-query passes rather than a read-modify-
        write per rule: a large guide has hundreds of rules, and the per-document
        form issued a GET, an UPDATE and a refresh wait for each one, so a single
        region edit could keep this thread busy for minutes.

        The two passes exist because `applicable_regions` is only resynced when
        it still mirrors the guide — a value an editor or the enrichment agent
        set deliberately is left alone.
        """
        try:
            guide = self._get_guide(guide_urn)
            new_region = guide.get("region")
            base_filter = [
                {"term": {"guide_urn": guide_urn}},
                {"bool": {"must_not": {"term": {"status": "deleted"}}}},
            ]
            now = datetime.now().isoformat()

            # Pass 1: the denormalized guide_region on every rule.
            ELASTIC_CLIENT.update_by_query(
                index_name=self.collection_name,
                query={
                    "bool": {
                        "filter": base_filter,
                        "must_not": [{"term": {"guide_region": new_region}}]
                        if new_region
                        else [],
                    }
                },
                script_source=(
                    "ctx._source.guide_region = params.region; "
                    "ctx._source.updated_at = params.now"
                ),
                params={"region": new_region, "now": now},
                max_docs=self.PARENT_SYNC_MAX_DOCS,
            )

            # Pass 2: applicable_regions, only where it still follows the guide.
            if new_region:
                ELASTIC_CLIENT.update_by_query(
                    index_name=self.collection_name,
                    query={"bool": {"filter": base_filter}},
                    script_source=(
                        "def current = ctx._source.applicable_regions; "
                        "boolean follows = current == null || current.isEmpty() "
                        "|| (current.size() == 1 && !current.contains(params.region)); "
                        "if (follows) { "
                        "  ctx._source.applicable_regions = [params.region]; "
                        "  ctx._source.updated_at = params.now; "
                        "} else { ctx.op = 'noop'; }"
                    ),
                    params={"region": new_region, "now": now},
                    max_docs=self.PARENT_SYNC_MAX_DOCS,
                )

            # The per-URN read cache would otherwise keep serving the old region.
            self._invalidate_guide_children(guide_urn)
        except Exception:
            logger.exception(
                "Failed to sync guideline guide_region for guide %s", guide_urn
            )

    def _invalidate_guide_children(self, guide_urn: str) -> None:
        """Evict every cached guideline under a guide after a bulk write."""
        if not config.settings.get("CACHE_ENABLED", False):
            return

        offset = 0
        page_size = 1000
        while True:
            qspec = SearchSchema.model_validate(
                {
                    "limit": page_size,
                    "offset": offset,
                    "fl": ["id"],
                    "fq": [f'guide_urn:"{guide_urn}"'],
                    "sort": "id asc",
                }
            )
            response = ELASTIC_CLIENT.search_entities(
                index_name=self.collection_name, qspec=qspec
            )
            results = response.get("results", [])
            if not results:
                return
            for item in results:
                identifier = self._strip_search_metadata(item).get("id")
                if identifier:
                    self.invalidate_cache(identifier)
            if len(results) < page_size:
                return
            offset += len(results)

    def sync_parent_metadata(self, guide_urn: str) -> None:
        threading.Thread(
            target=self._sync_parent_metadata_worker,
            args=(guide_urn,),
            daemon=True,
            name=f"guideline-region-sync-{guide_urn}",
        ).start()


GUIDELINE = Guideline()
