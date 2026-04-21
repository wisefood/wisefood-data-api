"""
RCollection Entity
------------------
Top-level recipe collection records describing sources of recipes such as
datasets, web portals, manually curated sets, or partner-supplied recipes.
"""

from typing import Optional, List, Dict, Any

from backend.elastic import ELASTIC_CLIENT
from backend.redis import REDIS
from catalog_access import (
    apply_public_catalog_filter,
    can_view_unapproved_catalog,
    is_publicly_visible,
)
from exceptions import DataError, InternalError, NotFoundError, ConflictError
import logging
from main import config
from schemas import (
    RCollectionCreationSchema,
    RCollectionSchema,
    RCollectionUpdateSchema,
)

from entity import Entity

logger = logging.getLogger(__name__)


class RCollection(Entity):
    def __init__(self):
        super().__init__(
            "rcollection",
            "rcollections",
            RCollectionSchema,
            RCollectionCreationSchema,
            RCollectionUpdateSchema,
        )

    @staticmethod
    def _viewer_can_access_all(
        viewer: Dict[str, Any] | None, *, include_unapproved: bool = False
    ) -> bool:
        return include_unapproved or can_view_unapproved_catalog(viewer)

    def _ensure_visible_to_viewer(
        self,
        rcollection_dict: Dict[str, Any],
        viewer: Dict[str, Any] | None,
        *,
        include_unapproved: bool = False,
    ) -> None:
        if self._viewer_can_access_all(
            viewer, include_unapproved=include_unapproved
        ) or is_publicly_visible(rcollection_dict):
            return
        raise NotFoundError(f"RCollection with URN {rcollection_dict['urn']} not found.")

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
        return entity

    def get_cached(self, urn: str) -> Dict[str, Any]:
        identifier = self.get_identifier(urn)
        obj = None

        if config.settings.get("CACHE_ENABLED", False):
            try:
                obj = REDIS.get(identifier)
            except Exception as e:
                logger.error(f"Failed to get cached rcollection {identifier}: {e}")

        if obj is None:
            obj = ELASTIC_CLIENT.get_entity(
                index_name=self.collection_name, urn=identifier
            )
            if obj is None:
                raise NotFoundError(f"RCollection with URN {identifier} not found.")
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
            return super().fetch(limit=limit, offset=offset)

        response = super().search(
            query=self._apply_viewer_filter(
                {"limit": limit or 100, "offset": offset or 0},
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self._strip_search_metadata(rcollection)
            for rcollection in response.get("results", [])
        ]

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
                {"limit": limit or 100, "offset": offset or 0, "fl": ["urn"]},
                viewer,
                include_unapproved=include_unapproved,
            )
        )
        return [
            self._strip_search_metadata(rcollection)["urn"]
            for rcollection in response.get("results", [])
            if "urn" in self._strip_search_metadata(rcollection)
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
            self._strip_search_metadata(rcollection)
            for rcollection in response.get("results", [])
        ]
        return response

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

    def create(self, spec: RCollectionCreationSchema, creator=None) -> Dict[str, Any]:
        try:
            rc_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating rcollection: {e}")

        try:
            self.validate_existence("urn:rcollection:" + rc_data.urn)
            raise ConflictError(f"RCollection with URN {rc_data.urn} already exists.")
        except NotFoundError:
            pass

        rc_dict = rc_data.model_dump(mode="json")
        rc_dict["creator"] = creator["preferred_username"]
        rc_dict = self.upsert_system_fields(rc_dict, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=rc_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create rcollection: {e}")

    def patch_entity(
        self, urn: str, spec: Dict[str, Any], actor: dict | None = None
    ):
        identifier = self.get_identifier(urn)
        self.patch(identifier, spec, actor=actor)
        self.invalidate_cache(identifier)
        return self.get_entity(identifier, viewer=actor, include_unapproved=True)

    def patch(
        self, urn: str, spec: Dict[str, Any], actor: dict | None = None
    ) -> Dict[str, Any]:
        try:
            rc_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating rcollection: {e}")

        self.get_cached(urn)

        rc_dict = rc_data.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        rc_dict = self.upsert_system_fields(rc_dict, update=True)
        rc_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=rc_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update rcollection: {e}")

    def delete(self, urn: str) -> bool:
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete rcollection: {e}")
        return {"deleted": urn}


RCOLLECTION = RCollection()
