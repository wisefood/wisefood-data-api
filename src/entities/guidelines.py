"""
Guideline Entity
----------------
Dependent guideline records belong to a parent guide and are addressed by UUID.
They do not own artifacts directly; any source references must point to artifacts
already attached to the parent guide.
"""

import re
from typing import Dict, Any, List, Optional

import logging

from backend.elastic import ELASTIC_CLIENT
from catalog_access import (
    apply_catalog_visibility_filter,
    can_view_unapproved_catalog,
    is_approved_or_active,
)
from entity import DependentEntity
from entities.artifacts import ARTIFACT
from exceptions import ConflictError, DataError, InternalError, NotFoundError
from schemas import (
    GuidelineCreationSchema,
    GuidelineSchema,
    GuidelineUpdateSchema,
    SearchSchema,
    validate_editorial_state,
)

logger = logging.getLogger(__name__)


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
            guideline_dict.get("review_status") != "verified"
            or not guideline_dict.get("verifier_user_id")
        ):
            raise ConflictError(
                "Cannot attach or keep an unverified guideline under an active guide."
            )

    def _apply_activation_visibility(
        self, guideline_dict: Dict[str, Any], guide: Dict[str, Any]
    ) -> Dict[str, Any]:
        if guideline_dict.get("status") == "active":
            guide_is_published = (
                guide.get("status") == "active" and guide.get("visibility") == "public"
            )
            guideline_dict["visibility"] = "public" if guide_is_published else "internal"
        return guideline_dict

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
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=id_)
        if entity is None:
            raise NotFoundError(f"Guideline with ID {id_} not found.")
        self._ensure_visible_to_viewer(
            entity, viewer, include_unapproved=include_unapproved
        )
        return entity

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

    def _normalize_source_refs(
        self, guide_urn: str, source_refs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not source_refs:
            return []

        artifacts = ARTIFACT.fetch(parent_urn=guide_urn, include_unapproved=True)
        if not artifacts:
            raise DataError(
                "source_refs require at least one artifact attached to the parent guide."
            )

        artifact_ids = {str(artifact["id"]) for artifact in artifacts}
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
        guideline_dict = self._apply_verifier_metadata(
            guideline_dict, creator, review_status_explicit=True
        )
        guideline_dict = self._apply_activation_visibility(guideline_dict, guide)
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

        self.invalidate_cache(guideline_dict["guide_urn"])
        return guideline_dict["id"]

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        identifier = self.create(spec, creator)
        return self.get(identifier, viewer=creator, include_unapproved=True)

    def patch_entity_with_actor(self, id_: str, spec: Dict[str, Any], actor: dict):
        identifier = self.get_identifier(id_)
        self.invalidate_cache(identifier)
        self.patch(identifier, spec, actor=actor)
        return self.get(identifier, viewer=actor, include_unapproved=True)

    def patch(self, id_: str, spec, actor: dict | None = None) -> None:
        try:
            guideline_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating guideline: {e}")

        current = self.get(id_, viewer=actor, include_unapproved=True)
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
        merged = self._apply_activation_visibility(merged, guide)

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
        update_dict = self.upsert_system_fields(update_dict, update=True)
        update_dict["id"] = id_

        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=update_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update guideline: {e}")

        self.invalidate_cache(current["guide_urn"])

    def delete(self, id_: str) -> bool:
        current = self.get(id_, include_unapproved=True)
        guide = self._get_guide(current["guide_urn"])
        self._ensure_parent_guide_not_published_for_deletion(guide)
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=id_)
        except Exception as e:
            raise InternalError(f"Failed to delete guideline: {e}")

        self.invalidate_cache(current["guide_urn"])
        return {"deleted": id_}

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
        return [
            item["id"]
            for item in self.fetch_for_guide(
                guide_urn=guide_urn,
                viewer=viewer,
                include_unapproved=include_unapproved,
            )
        ]

    def has_guidelines_for_guide(self, guide_urn: str) -> bool:
        """Check for linked guidelines without applying public visibility restrictions."""
        return bool(self.list_ids_for_guide(guide_urn, include_unapproved=True))

    def sync_parent_metadata(self, guide_urn: str) -> None:
        guide = self._get_guide(guide_urn)
        for guideline in self.fetch_for_guide(
            guide_urn=guide_urn, include_unapproved=True
        ):
            update_dict = self.upsert_system_fields(
                {"id": guideline["id"], "guide_region": guide.get("region")},
                update=True,
            )
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=update_dict
            )

    def sync_publication_state(self, guide_urn: str, *, guide_status: str, guide_visibility: str) -> None:
        guide_is_published = guide_status == "active" and guide_visibility == "public"

        for guideline in self.fetch_for_guide(
            guide_urn=guide_urn, include_unapproved=True
        ):
            if guideline.get("status") != "active":
                continue

            desired_visibility = "public" if guide_is_published else "internal"
            if guideline.get("visibility") == desired_visibility:
                continue

            update_dict = self.upsert_system_fields(
                {"id": guideline["id"], "visibility": desired_visibility},
                update=True,
            )
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=update_dict
            )


GUIDELINE = Guideline()
