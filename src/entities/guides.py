"""
Guide Entity
------------------
The Guide entity inherits from the base Entity class and provides
methods to manage dietary guide data, including retrieval, creation,
updating, and deletion of dietary guides. Collection operations such as
LIST, FETCH and SEARCH are implemented in the parent class. This class
consolidates and applies schemas specific to dietary guides for data validation
and serialization. It implements the CRUD operations while leveraging
the underlying infrastructure provided by the Entity base class.
"""

from typing import Optional, List, Dict, Any
from backend.elastic import ELASTIC_CLIENT
from exceptions import (
    DataError,
    InternalError,
    NotFoundError,
    ConflictError,
)
import logging
from schemas import (
    GuideCreationSchema,
    GuideUpdateSchema,
    GuideSchema,
    SearchSchema,
)

from entity import Entity
from entities.artifacts import ARTIFACT

logger = logging.getLogger(__name__)


class Guide(Entity):
    def __init__(self):
        super().__init__(
            "guide", 
            "guides", 
            GuideSchema, 
            GuideCreationSchema, 
            GuideUpdateSchema
        )

    def get(self, urn: str) -> Dict[str, Any]:
        entity = ELASTIC_CLIENT.get_entity(index_name=self.collection_name, urn=urn)
        if entity is None:
            raise NotFoundError(f"Guide with URN {urn} not found.")
        else:
            # Fetch and attach artifacts
            artifacts = ARTIFACT.fetch(parent_urn=urn)
            entity["artifacts"] = artifacts
        return entity

    def create(self, spec: GuideCreationSchema, creator: dict) -> Dict[str, Any]:
        # Validate input data
        try:
            guide_data = self.creation_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for creating guide: {e}")

        # Check if guide with same URN already exists
        try:
            self.validate_existence("urn:guide:" + guide_data.urn)

            raise ConflictError(f"Guide with URN {guide_data.urn} already exists.")
        except NotFoundError:
            pass  # Expected if guide does not exist

        # Convert to dict and store in Elasticsearch
        guide_dict = guide_data.model_dump(mode="json")
        guide_dict["creator"] = creator["preferred_username"]
        guide_dict = self.upsert_system_fields(guide_dict, update=False)
        try:
            ELASTIC_CLIENT.index_entity(
                index_name=self.collection_name, document=guide_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to create guide: {e}")

    def patch(self, urn: str, spec: GuideUpdateSchema):
        """Partially update an existing guide."""
        try:
            guide_data = self.update_schema.model_validate(spec)
        except Exception as e:
            raise DataError(f"Invalid data for updating guide: {e}")

        # Check if guide exists
        self.validate_existence(urn)

        # Convert to dict and update in Elasticsearch
        guide_dict = guide_data.model_dump(
            mode="json", exclude_unset=True, exclude_none=True
        )
        guide_dict = self.upsert_system_fields(guide_dict, update=True)
        guide_dict["urn"] = urn
        try:
            ELASTIC_CLIENT.update_entity(
                index_name=self.collection_name, document=guide_dict
            )
        except Exception as e:
            raise InternalError(f"Failed to update guide: {e}")

    def delete(self, urn: str) -> bool:
        # Permanently delete the guide
        try:
            ELASTIC_CLIENT.delete_entity(index_name=self.collection_name, urn=urn)
        except Exception as e:
            raise InternalError(f"Failed to delete guide: {e}")

        return {"deleted": urn}


GUIDE = Guide()
