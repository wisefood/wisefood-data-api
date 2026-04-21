"""
RCollection Entity
------------------
Top-level recipe collection records describing sources of recipes such as
datasets, web portals, manually curated sets, or partner-supplied recipes.
"""

from typing import Dict, Any

from backend.elastic import ELASTIC_CLIENT
from exceptions import DataError, InternalError, NotFoundError, ConflictError
import logging
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

    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"RCollection with URN {urn} not found.")
        return entity

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

    def patch(self, urn: str, spec: Dict[str, Any], updater=None) -> Dict[str, Any]:
        try:
            rc_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating rcollection: {e}")

        self.validate_existence(urn)

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
