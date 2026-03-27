"""
Textbook Entity
------------------
Top-level textbook records with workflow-aware visibility, textbook metadata,
and linked artifacts. Passage extraction is handled by the dependent
textbook_passage entity.
"""

from typing import Optional, List, Dict, Any

import logging

from backend.elastic import ELASTIC_CLIENT
from backend.redis import REDIS
from catalog_access import (
    apply_public_catalog_filter,
    can_view_unapproved_catalog,
    is_publicly_visible,
)
from entity import Entity
from entities.artifacts import ARTIFACT
from exceptions import DataError, InternalError, NotFoundError, ConflictError
from main import config
from schemas import (
    TextbookCreationSchema,
    TextbookSchema,
    TextbookUpdateSchema,
    validate_guide_publication,
    validate_textbook_editorial_state,
)

logger = logging.getLogger(__name__)


class Textbook(Entity):
    def __init__(self):
        super().__init__(
            "textbook",
            "textbooks",
            TextbookSchema,
            TextbookCreationSchema,
            TextbookUpdateSchema,
        )

    @staticmethod
    def _resolve_actor_id(actor: dict | None) -> str | None:
        if not actor:
            return None
        return actor.get("sub") or actor.get("id") or actor.get("preferred_username")

    def _apply_verifier_metadata(
        self,
        textbook_dict: Dict[str, Any],
        actor: dict | None,
        *,
        review_status_explicit: bool,
        current_verifier_user_id: str | None = None,
    ) -> Dict[str, Any]:
        if textbook_dict.get("review_status") == "verified" and (
            review_status_explicit or not current_verifier_user_id
        ):
            verifier_user_id = self._resolve_actor_id(actor)
            if not verifier_user_id:
                raise DataError(
                    "A verifier user ID is required when setting review_status='verified'."
                )
            textbook_dict["verifier_user_id"] = verifier_user_id
        elif review_status_explicit and textbook_dict.get("review_status") != "verified":
            textbook_dict["verifier_user_id"] = None
        elif current_verifier_user_id is not None:
            textbook_dict["verifier_user_id"] = current_verifier_user_id

        return textbook_dict

    @staticmethod
    def _viewer_can_access_all(
        viewer: Dict[str, Any] | None, *, include_unapproved: bool = False
    ) -> bool:
        return include_unapproved or can_view_unapproved_catalog(viewer)

    def _ensure_visible_to_viewer(
        self,
        textbook_dict: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> None:
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) or is_publicly_visible(textbook_dict):
            return
        raise NotFoundError(f"Textbook with URN {textbook_dict['urn']} not found.")

    def _apply_viewer_filter(
        self,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        if self._viewer_can_access_all(viewer, include_unapproved=include_unapproved):
            return query
        return apply_public_catalog_filter(query, exclude_deleted=True)

    def _hydrate_textbook(
        self,
        entity: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        hydrated = dict(entity)
        if "urn" not in hydrated:
            return hydrated
        hydrated["artifacts"] = ARTIFACT.fetch(
            parent_urn=hydrated["urn"],
            viewer=viewer,
            include_unapproved=include_unapproved,
        )
        return hydrated

    def get(
        self,
        urn: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        identifier = self.get_identifier(urn)
        entity = self.get_cached(identifier)
        self._ensure_visible_to_viewer(
            entity, viewer, include_unapproved=include_unapproved
        )
        return self._hydrate_textbook(
            entity, viewer=viewer, include_unapproved=include_unapproved
        )

    def get_cached(self, urn: str) -> Dict[str, Any]:
        identifier = self.get_identifier(urn)
        obj = None

        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(identifier)
            except Exception as e:
                logger.error(f"Failed to get cached textbook {identifier}: {e}")

        if obj is None:
            obj = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=identifier)
            if obj is None:
                raise NotFoundError(f"Textbook with URN {identifier} not found.")
            self.cache(identifier, obj)

        return self.dump_schema.model_validate(
            self._strip_search_metadata(obj)
        ).model_dump(mode="json")

    def get_entity(
        self,
        urn: str,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> Dict[str, Any]:
        identifier = self.get_identifier(urn)
        return self.get(
            identifier, viewer=viewer, include_unapproved=include_unapproved
        )

    def fetch(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        if self._viewer_can_access_all(viewer, include_unapproved=include_unapproved):
            textbooks = super().fetch(limit=limit, offset=offset)
            return [
                self._hydrate_textbook(
                    textbook, viewer=viewer, include_unapproved=include_unapproved
                )
                for textbook in textbooks
            ]

        response = super().search(
            query=self._apply_viewer_filter(
                {"limit": limit or 100, "offset": offset or 0},
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self._hydrate_textbook(
                self._strip_search_metadata(textbook),
                viewer=viewer,
                include_unapproved=include_unapproved,
            )
            for textbook in response.get("results", [])
        ]

    def list(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[str]:
        if self._viewer_can_access_all(viewer, include_unapproved=include_unapproved):
            return super().list(limit=limit, offset=offset)

        response = super().search(
            query=self._apply_viewer_filter(
                {
                    "limit": limit or 100,
                    "offset": offset or 0,
                    "fl": ["urn"],
                },
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self._strip_search_metadata(textbook)["urn"]
            for textbook in response.get("results", [])
            if "urn" in self._strip_search_metadata(textbook)
        ]

    def list_entities(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[str]:
        return self.list(
            limit=limit,
            offset=offset,
            viewer=viewer,
            include_unapproved=include_unapproved,
        )

    def search(
        self,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        response = super().search(
            query=self._apply_viewer_filter(
                query, viewer, include_unapproved=include_unapproved
            )
        )
        response["results"] = [
            self._hydrate_textbook(
                self._strip_search_metadata(textbook),
                viewer=viewer,
                include_unapproved=include_unapproved,
            )
            for textbook in response.get("results", [])
        ]
        return response

    def fetch_entities(
        self,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.fetch(
            limit=limit,
            offset=offset,
            viewer=viewer,
            include_unapproved=include_unapproved,
        )

    def search_entities(
        self,
        query: Dict[str, Any],
        viewer: Dict[str, Any] | None = None,
        *,
        include_unapproved: bool = False,
    ):
        return self.search(
            query=query,
            viewer=viewer,
            include_unapproved=include_unapproved,
        )

    def create_entity(self, spec, creator) -> Dict[str, Any]:
        self.create(spec, creator)
        identifier = self.get_identifier(spec.get("urn", spec.get("id")))
        return self.get_entity(identifier, viewer=creator, include_unapproved=True)

    def create(self, spec: TextbookCreationSchema, creator: dict) -> Dict[str, Any]:
        try:
            textbook_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating textbook: {e}")

        try:
            self.validate_existence("urn:textbook:" + textbook_data.urn)
            raise ConflictError(f"Textbook with URN {textbook_data.urn} already exists.")
        except NotFoundError:
            pass

        textbook_dict = textbook_data.model_dump(mode="json")
        textbook_dict["creator"] = creator["preferred_username"]
        textbook_dict = self.upsert_system_fields(textbook_dict, update=False)
        textbook_dict = self._apply_verifier_metadata(
            textbook_dict, creator, review_status_explicit=True
        )
        validate_textbook_editorial_state(textbook_dict)
        validate_guide_publication(textbook_dict)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=textbook_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create textbook: {e}")

    def patch_entity(
        self, urn: str, spec: Dict[str, Any], actor: dict | None = None
    ):
        identifier = self.get_identifier(urn)
        self.patch(identifier, spec, actor=actor)
        self.invalidate_cache(identifier)
        return self.get_entity(identifier, viewer=actor, include_unapproved=True)

    def patch(self, urn: str, spec: TextbookUpdateSchema, actor: dict | None = None):
        try:
            textbook_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating textbook: {e}")

        current = self.get_cached(urn)

        normalized_update_dict = textbook_data.model_dump(mode="json", exclude_unset=True)
        update_dict = textbook_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )
        if (
            "publication_year" in normalized_update_dict
            and normalized_update_dict["publication_year"] is None
        ):
            update_dict["publication_year"] = None

        merged = {**current, **update_dict, "urn": urn}
        merged = self._apply_verifier_metadata(
            merged,
            actor,
            review_status_explicit="review_status" in update_dict,
            current_verifier_user_id=current.get("verifier_user_id"),
        )
        validate_textbook_editorial_state(merged, partial=True)
        validate_guide_publication(merged, partial=True)

        textbook_dict = self.upsert_system_fields(update_dict, update=True)
        if "verifier_user_id" in merged:
            textbook_dict["verifier_user_id"] = merged.get("verifier_user_id")
        textbook_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=textbook_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update textbook: {e}")

    def delete(self, urn: str) -> bool:
        from entities.textbook_passages import TEXTBOOK_PASSAGE

        TEXTBOOK_PASSAGE.delete_for_textbook(urn)

        for artifact in ARTIFACT.fetch(parent_urn=urn, include_unapproved=True):
            ARTIFACT.delete_entity(artifact["id"])

        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete textbook: {e}")

        return {"deleted": urn}


TEXTBOOK = Textbook()
